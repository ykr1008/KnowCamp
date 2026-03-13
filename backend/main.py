import os
import shutil
import random
import string
import docx
import datetime
from typing import Optional, List
import pandas as pd
from PIL import Image
import pytesseract
import pdfplumber
# IMPORTANT: If Tesseract isn't in your system PATH, uncomment and set this line!
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
from fastapi.staticfiles import StaticFiles
from fastapi import FastAPI, Depends, HTTPException, File, UploadFile, status, Form
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import desc
from pydantic import BaseModel
import jwt
from groq import Groq

import models
import security
from database import engine, get_db

# Import specific tools from your processor
# The corrected imports:
from processor import CHROMA_PATH, embeddings
from langchain_community.vectorstores import Chroma
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, TextLoader, CSVLoader, UnstructuredExcelLoader, UnstructuredImageLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from dotenv import load_dotenv

# Load environment variables from the .env file
load_dotenv()

# ==========================================
# INITIALIZATION & SETUP
# ==========================================
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="KnowCamp API", version="2.0.0")

ADMIN_KEY = os.getenv("ADMIN_KEY")
API_KEY = os.getenv("API_KEY")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

model = Groq(api_key=API_KEY)

# We define the specific model name as a string to use in the chat function
AI_ENGINE = "llama-3.3-70b-versatile"


UPLOAD_DIR = "uploads"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)
    
# Expose the uploads folder so the React frontend can download/view the files
# NOTE: Change "uploaded_docs" to whatever your actual folder variable is!
app.mount("/files", StaticFiles(directory=UPLOAD_DIR), name="files")

# ==========================================
# PYDANTIC SCHEMAS
# ==========================================
class UserCreate(BaseModel):
    username: str
    password: str
    institution_name: str
    secret_key: Optional[str] = None

class WhitelistRequest(BaseModel):
    email: str
    assigned_role: str

class SubjectCreate(BaseModel):
    name: str
    year: str

class JoinSubject(BaseModel):
    invite_code: str

class ChatRenameRequest(BaseModel):
    title: str

def generate_invite_code(length=6):
    letters_and_digits = string.ascii_uppercase + string.digits
    return ''.join(random.choice(letters_and_digits) for i in range(length))

@app.get("/")
def read_root():
    return {"message": "Welcome to the KnowCamp API. Database connected!"}

# ==========================================
# AUTHENTICATION & SECURITY
# ==========================================
# ==========================================
# AUTHENTICATION & SECURITY (SaaS Upgraded)
# ==========================================
@app.post("/create_user/")
def create_user(user: UserCreate, db: Session = Depends(get_db)):
    # 1. Check if user already exists globally
    existing_user = db.query(models.User).filter(models.User.username == user.username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already registered!")
    
    # 2. SAAS TENANT PROVISIONING
    institution = db.query(models.Institution).filter(models.Institution.name == user.institution_name).first()
    assigned_role = "student"

    if user.secret_key == ADMIN_KEY:
        assigned_role = "admin"
        # If the admin is registering a new college, create the Institution workspace!
        if not institution:
            institution = models.Institution(name=user.institution_name)
            db.add(institution)
            db.commit()
            db.refresh(institution)
    else:
        # If a student/faculty is registering, the college MUST exist already
        if not institution:
            raise HTTPException(status_code=404, detail="Institution not found. Please ask your admin to register it first.")
        
        # Check the whitelist ONLY for this specific institution
        approved = db.query(models.ApprovedEmail).filter(
            models.ApprovedEmail.email == user.username,
            models.ApprovedEmail.institution_id == institution.id
        ).first()
        
        if not approved:
            raise HTTPException(status_code=403, detail="Your email is not on this institution's approved list.")
        assigned_role = approved.assigned_role 

    # 3. Create the user and lock them to the Tenant
    hashed_password = security.get_password_hash(user.password)
    new_user = models.User(
        username=user.username, 
        password_hash=hashed_password, 
        role=assigned_role,
        institution_id=institution.id # <-- LOCKED TO TENANT
    )
    
    db.add(new_user)
    db.commit()
    
    return {"message": f"User {user.username} created successfully in {institution.name} as a {assigned_role}!"}

@app.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == form_data.username).first()
    if not user or not security.verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    
    # INJECT THE TENANT ID INTO THE JWT TOKEN
    access_token = security.create_access_token(
        data={"sub": user.username, "role": user.role, "inst_id": user.institution_id}
    )
    
    return {
        "access_token": access_token, 
        "token_type": "bearer",
        "role": user.role,
        "user_id": user.id,
        "institution_id": user.institution_id # Let the frontend know where they are
    }

# ==========================================
# DOCUMENT UPLOAD & MANAGEMENT
# ==========================================
import io


@app.post("/upload_document/")
async def upload_document(
    file: UploadFile = File(...),
    subject_id: Optional[int] = Form(None), 
    token: str = Depends(oauth2_scheme), 
    db: Session = Depends(get_db)
):
    payload = jwt.decode(token, security.SECRET_KEY, algorithms=[security.ALGORITHM])
    user = db.query(models.User).filter(models.User.username == payload.get("sub")).first()
    
    if user.role not in ["admin", "faculty"]:
        raise HTTPException(status_code=403, detail="Not authorized to upload.")

    # --- FIX 1: GRACEFUL DUPLICATE CHECK ---
    existing_doc = db.query(models.Document).filter(models.Document.filename == file.filename, models.Document.institution_id == user.institution_id).first()
    if existing_doc:
        raise HTTPException(status_code=400, detail=f"The file '{file.filename}' already exists! Please rename your file and try again.")

    # 1. Save to PostgreSQL
    new_doc = models.Document(
        filename=file.filename, 
        uploaded_by=user.username,
        subject_id=subject_id,
        institution_id=user.institution_id # <-- LOCKED TO TENANT
    )
    db.add(new_doc)
    db.commit()

    # 2. Read the file content safely and save it
    content = await file.read()
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_path, "wb") as f:
        f.write(content)

    text = ""
    filename = file.filename.lower()
    
    try:
        # --- THE LLAMAPARSE UPGRADE (Built for Research Papers) ---
        print(f"Deploying LlamaParse Vision AI on {file.filename}...")
        
        from llama_parse import LlamaParse
        
        # Initialize the advanced layout-aware parser
        parser = LlamaParse(
            api_key=os.getenv("LLAMA_CLOUD_API_KEY"), 
            result_type="markdown", # This forces it to format tables and headers perfectly!
            verbose=True,
            language="en"
        )
        
        # Parse the saved file directly
        parsed_docs = parser.load_data(file_path)
        
        # Combine the parsed pages into one beautifully formatted Markdown string
        text = "\n\n".join([doc.text for doc in parsed_docs])
        
        print(f"Successfully extracted {file.filename} with layout preserved!")
            
    except Exception as e:
        db.delete(new_doc) # Rollback the database if reading fails
        db.commit()
        raise HTTPException(status_code=400, detail=f"Failed to parse document: {str(e)}")

    # 3. Split and tag the text
    print("\n" + "="*50)
    print("DEBUG: THIS IS WHAT THE AI SEES:")
    print(text)
    print("="*50 + "\n")

    if not text.strip():
        db.delete(new_doc)
        db.commit()
        raise HTTPException(status_code=400, detail="Could not read any text from this file.")

    from langchain_text_splitters import RecursiveCharacterTextSplitter
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=3000, chunk_overlap=800)
    chunks = text_splitter.split_text(text)
    
    metadata_tag = "global" if subject_id is None else str(subject_id)
    metadatas = [
        {
            "source": file.filename, 
            "subject_id": metadata_tag,
            "inst_id": str(user.institution_id) # <-- CRITICAL ISOLATION TAG
        } for _ in chunks
    ]
    
    # 4. Save to Vector Database
    from processor import CHROMA_PATH, embeddings
    from langchain_community.vectorstores import Chroma
    vector_db = Chroma(persist_directory=CHROMA_PATH, embedding_function=embeddings)
    vector_db.add_texts(texts=chunks, metadatas=metadatas)
    
    return {"message": f"Successfully uploaded {file.filename}"}

@app.get("/documents/")
def get_documents(
    subject_id: Optional[int] = None, 
    db: Session = Depends(get_db), 
    token: str = Depends(oauth2_scheme)
):
    # 1. Decode the token to get the user's details
    payload = jwt.decode(token, security.SECRET_KEY, algorithms=[security.ALGORITHM])
    
    # 🚨 THIS IS THE LINE THAT WAS MISSING! Grabbing the ID from the token:
    user_inst_id = payload.get("inst_id")
    if subject_id:
        docs = db.query(models.Document).filter(
            models.Document.subject_id == subject_id,
            models.Document.institution_id == user_inst_id).all()
    else:
        docs = db.query(models.Document).filter(
            models.Document.subject_id == None,
            models.Document.institution_id == user_inst_id).all()
        
    return {"documents": [{"id": d.id, "filename": d.filename, "uploaded_by": d.uploaded_by} for d in docs]}

@app.delete("/documents/{doc_id}/")
def delete_document(
    doc_id: int, 
    token: str = Depends(oauth2_scheme), 
    db: Session = Depends(get_db)
):
    # 1. Verify user and find the document in PostgreSQL
    payload = jwt.decode(token, security.SECRET_KEY, algorithms=[security.ALGORITHM])
    user = db.query(models.User).filter(models.User.username == payload.get("sub")).first()
    
    doc = db.query(models.Document).filter(models.Document.id == doc_id, models.Document.institution_id == user.institution_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # (Optional Security Check: Ensure only admins or the uploader can delete)
    if user.role != "admin" and doc.uploaded_by != user.username:
        raise HTTPException(status_code=403, detail="Not authorized to delete this document")

    # 2. Delete the memories from ChromaDB FIRST!
    try:
        vector_db = Chroma(persist_directory=CHROMA_PATH, embedding_function=embeddings)
        
        # We need to tell Chroma exactly which file to forget.
        # We use the filename AND the subject_id so it doesn't accidentally delete 
        # the same file from a different classroom!
        doc_subject_id = str(doc.subject_id) if doc.subject_id else "global"
        
        # Access the raw Chroma collection to delete by metadata
        vector_db._collection.delete(
            where={
                "$and": [
                    {"source": doc.filename},
                    {"subject_id": doc_subject_id}
                ]
            }
        )
    except Exception as e:
        print(f"🚨 Warning: Failed to delete from ChromaDB: {e}")
        # We continue anyway to ensure the SQL database stays clean

    # 3. Delete from PostgreSQL
    db.delete(doc)
    db.commit()

    return {"message": f"Successfully deleted {doc.filename} from database and AI memory."}

# ==========================================
# CHAT SYSTEM (GEMINI + RAG)
# ==========================================
@app.get("/my_chats/")
def get_my_chats(subject_id: Optional[int] = None, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    payload = jwt.decode(token, security.SECRET_KEY, algorithms=[security.ALGORITHM])
    user = db.query(models.User).filter(models.User.username == payload.get("sub")).first()
    
    if subject_id:
        chats = db.query(models.ChatSession).filter(models.ChatSession.user_id == user.id, models.ChatSession.subject_id == subject_id).order_by(models.ChatSession.created_at.desc()).all()
    else:
        chats = db.query(models.ChatSession).filter(models.ChatSession.user_id == user.id, models.ChatSession.subject_id == None).order_by(models.ChatSession.created_at.desc()).all()
        
    return {"chats": [{"id": c.id, "title": c.title} for c in chats]}

@app.get("/chat_history/{session_id}")
def get_chat_history(session_id: int, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        # 1. Decode the token to figure out who is asking
        payload = jwt.decode(token, security.SECRET_KEY, algorithms=[security.ALGORITHM])
        user = db.query(models.User).filter(models.User.username == payload.get("sub")).first()
        
        if not user:
            raise HTTPException(status_code=401, detail="User not found")

        # 2. 🚨 THE FIX: Check if this user actually OWNS this chat session!
        session = db.query(models.ChatSession).filter(
            models.ChatSession.id == session_id,
            models.ChatSession.user_id == user.id # <-- The Privacy Wall
        ).first()
        
        if not session:
            # If they don't own it (or it doesn't exist), deny access
            raise HTTPException(status_code=403, detail="Unauthorized access to chat.")

        # 3. If they passed the check, fetch their messages
        messages = db.query(models.ChatMessage).filter(models.ChatMessage.session_id == session_id).order_by(models.ChatMessage.created_at).all()
        return {"messages": [{"role": m.role, "content": m.content, "sources": m.sources or []} for m in messages]}
        
    except HTTPException:
        raise # Let our specific 401/403 errors pass through to the frontend
    except Exception as e:
        raise HTTPException(status_code=500, detail="Could not load chat history")

@app.delete("/my_chats/{session_id}")
def delete_chat_session(session_id: int, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, security.SECRET_KEY, algorithms=[security.ALGORITHM])
        user = db.query(models.User).filter(models.User.username == payload.get("sub")).first()

        session_to_delete = db.query(models.ChatSession).filter(
            models.ChatSession.id == session_id,
            models.ChatSession.user_id == user.id
        ).first()

        if not session_to_delete:
            raise HTTPException(status_code=404, detail="Chat session not found")

        db.delete(session_to_delete)
        db.commit()
        return {"message": "Chat deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Could not delete chat")

@app.put("/my_chats/{session_id}")
def rename_chat_session(
    session_id: int, 
    request: ChatRenameRequest, 
    token: str = Depends(oauth2_scheme), 
    db: Session = Depends(get_db)
):
    try:
        payload = jwt.decode(token, security.SECRET_KEY, algorithms=[security.ALGORITHM])
        user = db.query(models.User).filter(models.User.username == payload.get("sub")).first()

        session_to_rename = db.query(models.ChatSession).filter(
            models.ChatSession.id == session_id,
            models.ChatSession.user_id == user.id
        ).first()

        if not session_to_rename:
            raise HTTPException(status_code=404, detail="Chat session not found")

        session_to_rename.title = request.title
        db.commit()
        return {"message": "Chat renamed successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Could not rename chat")

@app.get("/chat/")
def chat(
    question: str, 
    ai_mode: bool = False,
    session_id: Optional[int] = None, 
    subject_id: Optional[int] = None,
    filename: Optional[str] = None,
    token: str = Depends(oauth2_scheme), 
    db: Session = Depends(get_db)
):
    try:
        payload = jwt.decode(token, security.SECRET_KEY, algorithms=[security.ALGORITHM])
        user = db.query(models.User).filter(models.User.username == payload.get("sub")).first()

        # --- THE GHOST BUSTER ---
        if session_id:
            session_record = db.query(models.ChatSession).filter(models.ChatSession.id == session_id).first()
            if not session_record:
                print(f"DEBUG: Frontend sent a ghost session_id ({session_id}). Creating a new one.")
                session_id = None

        # 1. Establish the session
        if not session_id:
            new_session = models.ChatSession(user_id=user.id, subject_id=subject_id, title=question[:30])
            db.add(new_session)
            db.commit()
            db.refresh(new_session)
            session_id = new_session.id

        # Fetch past messages
        past_messages = db.query(models.ChatMessage).filter(models.ChatMessage.session_id == session_id).order_by(models.ChatMessage.id.asc()).all()
        
        # Create a "Smart Search" query
        search_query = question
        if past_messages:
            last_user_messages = [msg.content for msg in past_messages if msg.role == 'user']
            if last_user_messages:
                search_query = f"{last_user_messages[-1]} {question}"

        # 2. Search ChromaDB
        vector_db = Chroma(persist_directory=CHROMA_PATH, embedding_function=embeddings)
        
        target_subject = str(subject_id) if subject_id else "global"
        
        # Build the exact filter ChromaDB demands (Locked to the Tenant)
        search_filter = {
            "$and": [
                {"inst_id": str(user.institution_id)}, # <-- AI CAN ONLY SEE THIS COLLEGE
                {"subject_id": target_subject}
            ]
        }
        
        if filename:
            search_filter["$and"].append({"source": filename})

        # Search the database securely
        raw_results = vector_db.similarity_search_with_score(search_query, k=15, filter=search_filter)

        # Quality Control Filter
        docs = []
        for doc, score in raw_results:
            print(f"DEBUG - File: {os.path.basename(doc.metadata.get('source', 'Unknown'))}, Score: {score}") 
            docs.append(doc)

        # If database is empty or nothing passes
        if not docs:
            fallback_answer = "I couldn't find any relevant information in the uploaded documents."
            db.add(models.ChatMessage(session_id=session_id, role="user", content=question))
            db.add(models.ChatMessage(session_id=session_id, role="ai", content=fallback_answer))
            db.commit()
            return {"answer": fallback_answer, "sources": [], "session_id": session_id}

        # Format the ALL retrieved sources initially
        unique_sources = {}
        for doc in docs:
            filename = os.path.basename(doc.metadata.get('source', 'Unknown'))
            doc_subject_id = str(doc.metadata.get('subject_id', 'global'))
            unique_key = f"{filename}_{doc_subject_id}"
            
            if unique_key not in unique_sources:
                if doc_subject_id == 'global':
                    classname = "Global Docs"
                else:
                    subject_record = db.query(models.Subject).filter(models.Subject.id == int(doc_subject_id)).first()
                    classname = subject_record.name if subject_record else f"Class {doc_subject_id}"
                
                unique_sources[unique_key] = {"filename": filename, "classname": classname}
        
        sources_list = list(unique_sources.values())

        # --- SMART RAG UPGRADE 1: Tag the Context ---
        context_parts = []
        for doc in docs:
            filename_meta = os.path.basename(doc.metadata.get('source', 'Unknown'))
            context_parts.append(f"--- START OF DOCUMENT: {filename_meta} ---\n{doc.page_content}\n--- END OF DOCUMENT ---")
        
        context = "\n\n".join(context_parts)
        
        # --- THE DYNAMIC BRAIN SWAP (V2: Million-Dollar SaaS Edition) ---
        
        # This block defines the "Persona" rules that apply to BOTH modes
        personality_rules = (
            "PERSONALITY & STYLE GUIDE:\n"
            "1. SENTIMENT AWARENESS: Detect the user's emotion. If they are stressed/sad (e.g., about a claim), be extra empathetic and calming. If they are happy/excited, be encouraging. If they are professional/neutral, be concise and efficient.\n"
            "2. VISUAL HIERARCHY: Use Markdown heavily. Use '###' for section headers and '---' for dividers.\n"
            "3. EMOJIS: Use emojis professionally to categorize information (e.g., 🏥 for hospitals, 💰 for money, ⚠️ for warnings, ✅ for steps).\n"
            "4. NO REPETITION: Never start multiple bullet points with the same phrase. Keep it fresh.\n"
            "5. BOLDING: Bold numbers, dates, and 'Must-Know' terms so they pop out.\n"
        )

        if ai_mode:
            system_prompt = (
                f"You are KnowCamp AI, a world-class premium academic and professional advisor. {personality_rules}\n"
                "MODE: GENERAL AI (You may use Context + Your General Knowledge).\n\n"
                f"Context:\n{context}\n\n"
                "CITATION: End with 'SOURCES: filename.ext' or 'SOURCES: General World Knowledge'."
            )
        else:
            system_prompt = (
                f"You are the KnowCamp Strict Data Vault. {personality_rules}\n\n"
                f"--- BEGIN UPLOADED DOCUMENT CONTEXT ---\n"
                f"{context}\n"
                f"--- END UPLOADED DOCUMENT CONTEXT ---\n\n"
                "### FINAL MANDATORY INSTRUCTIONS BEFORE ANSWERING ###\n"
                "1. You are operating in STRICT DOC MODE. You have ZERO outside knowledge.\n"
                "2. You MUST check the text between the BEGIN and END tags above. If the exact answer is not there, you do not know it.\n"
                "3. If the user asks for a comparison involving companies, policies, or facts NOT explicitly written in the Context above, you MUST refuse to answer.\n"
                "4. Do NOT invent generic comparisons. Do NOT try to be helpful with outside knowledge.\n"
                "5. If the answer requires outside knowledge, you MUST begin your response with the exact token: [NO_RELEVANT_DATA]. After that token, you may politely explain that you cannot answer the question.'\n"
            )
        # -----------------------------------------------

        groq_messages = [{"role": "system", "content": system_prompt}]

        groq_messages = [{"role": "system", "content": system_prompt}]
        for msg in past_messages[-4:]:
            role = "assistant" if msg.role == "ai" else "user"
            groq_messages.append({"role": role, "content": msg.content})
            
        groq_messages.append({"role": "user", "content": question})

        try:
            response = model.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=groq_messages, 
            )
            raw_answer = response.choices[0].message.content
            
            # --- SMART RAG UPGRADE 3: Intercept and Filter ---
            final_answer = raw_answer
            
            if "[NO_RELEVANT_DATA]" in raw_answer:
                # Clean the token out so the user doesn't see it
                final_answer = raw_answer.replace("[NO_RELEVANT_DATA]", "").strip()
                sources_list = [] # Wipe the sources!
            elif "SOURCES:" in raw_answer:
                # Split the text to remove the ugly 'SOURCES:' line from the UI
                parts = raw_answer.split("SOURCES:")
                final_answer = parts[0].strip() # The clean chat answer
                llm_cited_files = parts[1].strip() # The raw string of filenames
                
                # Filter the massive 'sources_list' to ONLY include what Groq actually used
                smart_sources = []
                for src in sources_list:
                    if src["filename"] in llm_cited_files:
                        smart_sources.append(src)
                
                sources_list = smart_sources
            # -------------------------------------------------
                
        except Exception as ai_err:
            print(f"Groq API Error: {ai_err}")
            final_answer = f"🔍 Groq Error: {str(ai_err)}"
            sources_list = []

        # 4. Save to PostgreSQL
        db.add(models.ChatMessage(session_id=session_id, role="user", content=question))
        db.add(models.ChatMessage(session_id=session_id, role="ai", content=final_answer, sources=sources_list))
        db.commit()

        return {"answer": final_answer, "sources": sources_list, "session_id": session_id}

    except Exception as e:
        error_msg = str(e)
        print(f"🚨 ACTUAL CRITICAL ERROR: {error_msg}")
        fallback_answer = f"🔍 DEBUG ERROR: {error_msg}"
        return {"answer": fallback_answer, "sources": [], "session_id": session_id or 0}

@app.post("/reset")
def reset_chat():
    global chat_session
    chat_session = model.start_chat(history=[])
    return {"status": "success", "message": "Chat history cleared"}


# ==========================================
# ADMIN DASHBOARD & WHITELIST
# ==========================================
@app.post("/admin/whitelist/")
def add_to_whitelist(request: WhitelistRequest, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    payload = jwt.decode(token, security.SECRET_KEY, algorithms=[security.ALGORITHM])
    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only admins can do this.")

    # 1. Grab the short token key
    admin_inst_id = payload.get("inst_id")

    existing = db.query(models.ApprovedEmail).filter(
        models.ApprovedEmail.email == request.email,
        models.ApprovedEmail.institution_id == admin_inst_id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email is already on the whitelist.")

    # 2. Assign it to the full database column
    new_approval = models.ApprovedEmail(
        email=request.email, 
        assigned_role=request.assigned_role,
        institution_id=admin_inst_id 
    )
    db.add(new_approval)
    db.commit()
    return {"message": f"Added {request.email} as {request.assigned_role}"}

@app.get("/admin/whitelist/")
def get_whitelist(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    payload = jwt.decode(token, security.SECRET_KEY, algorithms=[security.ALGORITHM])
    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only admins can do this.")
        
    admin_inst_id = payload.get("inst_id")
    emails = db.query(models.ApprovedEmail).filter(models.ApprovedEmail.institution_id == admin_inst_id).all()
    return {"whitelist": [{"id": e.id, "email": e.email, "role": e.assigned_role} for e in emails]}

@app.delete("/admin/whitelist/{email_id}")
def remove_from_whitelist(email_id: int, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    payload = jwt.decode(token, security.SECRET_KEY, algorithms=[security.ALGORITHM])
    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only admins can do this.")

    admin_inst_id = payload.get("inst_id")
        
    record = db.query(models.ApprovedEmail).filter(models.ApprovedEmail.id == email_id, models.ApprovedEmail.institution_id == admin_inst_id).first()
    if record:
        db.delete(record)
        db.commit()
    return {"message": "Removed from whitelist"}


# ==========================================
# ACTIVE USER MANAGEMENT (ADMIN ONLY)
# ==========================================
@app.get("/admin/users/")
def get_all_users(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    payload = jwt.decode(token, security.SECRET_KEY, algorithms=[security.ALGORITHM])
    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only admins can do this.")

    admin_inst_id = payload.get("inst_id")

    users = db.query(models.User).filter(models.User.institution_id == admin_inst_id).all()
    return {"users": [{"id": u.id, "username": u.username, "role": u.role} for u in users]}

@app.delete("/admin/users/{user_id}")
def delete_active_user(user_id: int, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    payload = jwt.decode(token, security.SECRET_KEY, algorithms=[security.ALGORITHM])
    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only admins can do this.")

    admin_inst_id = payload.get("inst_id")

    user = db.query(models.User).filter(models.User.id == user_id, models.User.institution_id == admin_inst_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.username == payload.get("sub"):
        raise HTTPException(status_code=400, detail="You cannot delete your own admin account!")

    try:
        user_sessions = db.query(models.ChatSession).filter(models.ChatSession.user_id == user_id).all()
        for session in user_sessions:
            db.delete(session) 
        
        db.delete(user)
        db.commit()
        return {"message": "User permanently deleted."}
        
    except Exception as e:
        db.rollback() 
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


# ==========================================
# CLASSROOM / SUBJECT MANAGEMENT
# ==========================================
@app.post("/subjects/")
def create_subject(subject: SubjectCreate, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    payload = jwt.decode(token, security.SECRET_KEY, algorithms=[security.ALGORITHM])
    user = db.query(models.User).filter(models.User.username == payload.get("sub")).first()
    
    if user.role not in ["admin", "faculty"]:
        raise HTTPException(status_code=403, detail="Only Admins and Faculty can create classes.")
        
    invite_code = generate_invite_code()
    
    while db.query(models.Subject).filter(models.Subject.invite_code == invite_code).first():
        invite_code = generate_invite_code()
        
    new_subject = models.Subject(
        name=subject.name,
        year=subject.year,
        invite_code=invite_code,
        faculty_id=user.id,
        institution_id=user.institution_id
    )
    db.add(new_subject)
    db.commit()
    db.refresh(new_subject)
    
    return {"message": "Class created!", "invite_code": invite_code}

@app.post("/subjects/join/")
def join_subject(req: JoinSubject, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    payload = jwt.decode(token, security.SECRET_KEY, algorithms=[security.ALGORITHM])
    user = db.query(models.User).filter(models.User.username == payload.get("sub")).first()
    
    subject = db.query(models.Subject).filter(models.Subject.invite_code == req.invite_code, models.Subject.institution_id == user.institution_id).first()
    if not subject:
        raise HTTPException(status_code=404, detail="Invalid invite code. Please check and try again.")
        
    existing = db.query(models.Enrollment).filter(
        models.Enrollment.student_id == user.id, 
        models.Enrollment.subject_id == subject.id
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="You are already enrolled in this class.")
        
    enrollment = models.Enrollment(student_id=user.id, subject_id=subject.id)
    db.add(enrollment)
    db.commit()
    return {"message": f"Successfully joined {subject.name}!"}

@app.get("/subjects/")
def get_my_subjects(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    payload = jwt.decode(token, security.SECRET_KEY, algorithms=[security.ALGORITHM])
    user = db.query(models.User).filter(models.User.username == payload.get("sub")).first()
    
    if user.role == "admin":
        # Admins see everything
        subjects = db.query(models.Subject).filter(models.Subject.institution_id == user.institution_id).all()
        
    elif user.role == "faculty":
        # 1. Fetch classes they created
        created_subjects = db.query(models.Subject).filter(models.Subject.faculty_id == user.id).all()
        
        # 2. Fetch classes they joined
        enrollments = db.query(models.Enrollment).filter(models.Enrollment.student_id == user.id).all()
        enrolled_ids = [e.subject_id for e in enrollments]
        joined_subjects = db.query(models.Subject).filter(models.Subject.id.in_(enrolled_ids)).all()
        
        # Combine lists and remove duplicates
        all_faculty_subjects = {s.id: s for s in (created_subjects + joined_subjects)}.values()
        subjects = list(all_faculty_subjects)
        
    else:
        # Students only see what they joined
        enrollments = db.query(models.Enrollment).filter(models.Enrollment.student_id == user.id).all()
        subject_ids = [e.subject_id for e in enrollments]
        subjects = db.query(models.Subject).filter(models.Subject.id.in_(subject_ids)).all()
        
    # Add Creator Name and Faculty ID to the frontend response!
    subject_list = []
    for s in subjects:
        faculty_user = db.query(models.User).filter(models.User.id == s.faculty_id).first()
        creator_name = faculty_user.username if faculty_user else "Admin"
        
        subject_list.append({
            "id": s.id, 
            "name": s.name, 
            "year": s.year, 
            "invite_code": s.invite_code,
            "creator_name": creator_name,
            "faculty_id": s.faculty_id
        })
        
    return {"subjects": subject_list}

@app.get("/subjects/{subject_id}/students")
def get_class_students(
    subject_id: int, 
    token: str = Depends(oauth2_scheme), 
    db: Session = Depends(get_db)
):
    try:
        payload = jwt.decode(token, security.SECRET_KEY, algorithms=[security.ALGORITHM])
        username = payload.get("sub")
        current_user = db.query(models.User).filter(models.User.username == username).first()
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid Authentication Token")

    if not current_user:
        raise HTTPException(status_code=401, detail="User not found")

    subject = db.query(models.Subject).filter(
        models.Subject.id == subject_id, 
        models.Subject.institution_id == current_user.institution_id
    ).first()
    
    if not subject:
        raise HTTPException(status_code=404, detail="Class not found")

    # --- THE ROSTER MERGE FIX ---
    roster_list = []
    
    # 1. Fetch and Add the Faculty/Creator First (Pinned to the top)
    if subject.faculty_id:
        faculty = db.query(models.User).filter(models.User.id == subject.faculty_id).first()
        if faculty:
            roster_list.append({
                "id": faculty.id,
                "username": faculty.username,
                "role": "instructor" # Special tag for your frontend!
            })

    # 2. Fetch and Add the Enrolled Students
    enrollments = db.query(models.Enrollment).filter(models.Enrollment.subject_id == subject_id).all()
    for enrollment in enrollments:
        student = db.query(models.User).filter(models.User.id == enrollment.student_id).first()
        if student:
            roster_list.append({
                "id": student.id,
                "username": student.username,
                "role": student.role
            })

    # Note: Returning under the key "students" so your React state doesn't break
    return {"students": roster_list}

@app.delete("/subjects/{subject_id}/students/{student_id}")
def remove_student_from_class(
    subject_id: int, 
    student_id: int, 
    token: str = Depends(oauth2_scheme), 
    db: Session = Depends(get_db)
):
    # 1. Decode the Token ONLY
    try:
        payload = jwt.decode(token, security.SECRET_KEY, algorithms=[security.ALGORITHM])
        username = payload.get("sub")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid Authentication Token")

    # 2. Fetch the User Safely (Outside the try/except!)
    current_user = db.query(models.User).filter(models.User.username == username).first()
    
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found")

    # 3. Check Authorization & Ownership (Strict RBAC)
    if current_user.role == "student":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Access Denied. Students cannot remove users."
        )

    # Fetch the class and ensure it belongs to the same institution
    subject = db.query(models.Subject).filter(
        models.Subject.id == subject_id,
        models.Subject.institution_id == current_user.institution_id
    ).first()
    
    if not subject:
        raise HTTPException(status_code=404, detail="Class not found.")

    # ... The rest of your existing logic (faculty check, enrollment delete) stays the same ...

    # THE CRITICAL CHECK: Enforce Faculty Boundaries
    if current_user.role == "faculty":
        # If the class has no assigned faculty OR is assigned to someone else (like an admin)
        if subject.faculty_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, 
                detail="Access Denied. You can only manage your own classes. Admin-created classes can only be modified by Admins."
            )
            
    # Note: If current_user.role == "admin", it skips the faculty check completely and proceeds!

    # 3. Target the invisible "Bridge" (The Enrollment Table)
    enrollment = db.query(models.Enrollment).filter(
        models.Enrollment.subject_id == subject_id,
        models.Enrollment.student_id == student_id
    ).first()

    # 4. Safely sever the connection
    try:
        db.delete(enrollment)  # ONLY deletes the link, the user account is 100% safe
        db.commit()
        return {"message": "Successfully removed student from the class."}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@app.put("/subjects/{subject_id}/remove_faculty")
def remove_faculty_from_class(
    subject_id: int, 
    token: str = Depends(oauth2_scheme), 
    db: Session = Depends(get_db)
):
    # 1. Decode the Token ONLY (inside the try/except)
    try:
        payload = jwt.decode(token, security.SECRET_KEY, algorithms=[security.ALGORITHM])
        username = payload.get("sub")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid Authentication Token")

    # 2. Fetch the User Safely (Outside the try/except!)
    current_user = db.query(models.User).filter(models.User.username == username).first()
    
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found")

    # 3. Strict Admin-Only Authorization
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Absolute Access Denied. Only Admins can remove faculty from a class."
        )

    # 4. Fetch the Subject and verify it belongs to this institution
    subject = db.query(models.Subject).filter(
        models.Subject.id == subject_id,
        models.Subject.institution_id == current_user.institution_id
    ).first()
    
    if not subject:
        raise HTTPException(status_code=404, detail="Class not found.")

    if subject.faculty_id is None:
        return {"message": "This class currently has no faculty assigned."}

    # 5. Safely remove the faculty member (DOES NOT delete their account)
    try:
        subject.faculty_id = None  # Erase the professor from the class
        db.commit()
        return {"message": f"Successfully removed faculty from {subject.name}."}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@app.delete("/subjects/{subject_id}")
def delete_subject(
    subject_id: int, 
    token: str = Depends(oauth2_scheme), 
    db: Session = Depends(get_db)
):
    # 1. Authenticate
    try:
        import jwt
        payload = jwt.decode(token, security.SECRET_KEY, algorithms=[security.ALGORITHM])
        username = payload.get("sub")
        current_user = db.query(models.User).filter(models.User.username == username).first()
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    if not current_user:
        raise HTTPException(status_code=401, detail="User not found")

    # 2. Find the Class
    subject = db.query(models.Subject).filter(models.Subject.id == subject_id, models.Subject.institution_id == current_user.institution_id).first()
    if not subject:
        raise HTTPException(status_code=404, detail="Class not found")

    # 3. RBAC Check: Must be an Admin OR the Faculty who created it
    if current_user.role != "admin" and subject.faculty_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Access Denied. Only Admins or the class creator can delete this class."
        )

    # 4. Wipe Vector Data (Preventing "Ghost Data" in the AI)
    try:
        from processor import CHROMA_PATH, embeddings
        from langchain_community.vectorstores import Chroma
        vector_db = Chroma(persist_directory=CHROMA_PATH, embedding_function=embeddings)
        # Delete all document chunks tagged with this specific subject_id
        vector_db._collection.delete(where={"subject_id": str(subject_id)})
    except Exception as e:
        print(f"Warning: Failed to clean ChromaDB vectors: {e}")

    # 5. Delete from PostgreSQL (Cascades will handle the rest!)
    try:
        db.delete(subject)
        db.commit()
        return {"message": "Classroom and all associated data permanently deleted."}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error during deletion: {str(e)}")


@app.delete("/subjects/{subject_id}/leave")
def leave_class(
    subject_id: int, 
    token: str = Depends(oauth2_scheme), 
    db: Session = Depends(get_db)
):
    # 1. Safe Authentication
    try:
        payload = jwt.decode(token, security.SECRET_KEY, algorithms=[security.ALGORITHM])
        username = payload.get("sub")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid Authentication Token")

    current_user = db.query(models.User).filter(models.User.username == username).first()
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found")

    subject = db.query(models.Subject).filter(
        models.Subject.id == subject_id, 
        models.Subject.institution_id == current_user.institution_id
    ).first()
    
    if not subject:
        raise HTTPException(status_code=404, detail="Class not found")

    # 2. Scenario A: The Creator/Instructor is leaving
    if subject.faculty_id == current_user.id:
        subject.faculty_id = None # They step down, but the class remains
        db.commit()
        return {"message": "You have exited the class as the instructor."}

    # 3. Scenario B: A Student (or a faculty enrolled as a student) is leaving
    enrollment = db.query(models.Enrollment).filter(
        models.Enrollment.subject_id == subject_id,
        models.Enrollment.student_id == current_user.id
    ).first()

    if enrollment:
        db.delete(enrollment)
        db.commit()
        return {"message": "You have successfully left the class."}

    raise HTTPException(status_code=400, detail="You are not a member of this class.")


@app.post("/subjects/{subject_id}/claim")
def claim_orphaned_class(
    subject_id: int, 
    token: str = Depends(oauth2_scheme), 
    db: Session = Depends(get_db)
):
    # 1. Authenticate safely
    try:
        payload = jwt.decode(token, security.SECRET_KEY, algorithms=[security.ALGORITHM])
        username = payload.get("sub")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid Authentication Token")

    user = db.query(models.User).filter(models.User.username == username).first()
    
    # 2. Strict Role Check
    if not user or user.role != "faculty":
        raise HTTPException(status_code=403, detail="Only faculty members can claim a class.")
        
    subject = db.query(models.Subject).filter(
        models.Subject.id == subject_id, 
        models.Subject.institution_id == user.institution_id
    ).first()
    
    if not subject:
        raise HTTPException(status_code=404, detail="Class not found")
        
    if subject.faculty_id is not None:
        raise HTTPException(status_code=400, detail="This class already has an instructor.")
        
    # 3. Hand over the crown
    subject.faculty_id = user.id
    
    # 4. Clean up: If they joined via invite code, they are in the student enrollments table. Remove them.
    enrollment = db.query(models.Enrollment).filter(
        models.Enrollment.student_id == user.id, 
        models.Enrollment.subject_id == subject.id
    ).first()
    
    if enrollment:
        db.delete(enrollment)
        
    db.commit()
    return {"message": "You are now the instructor of this class!"}