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
@app.post("/create_user/")
def create_user(user: UserCreate, db: Session = Depends(get_db)):
    existing_user = db.query(models.User).filter(models.User.username == user.username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already registered!")
    
    assigned_role = "student"
    
    if user.secret_key == ADMIN_KEY:
        assigned_role = "admin"
    else:
        approved = db.query(models.ApprovedEmail).filter(models.ApprovedEmail.email == user.username).first()
        if not approved:
            raise HTTPException(status_code=403, detail="Your email is not on the approved list. Please contact the administrator.")
        assigned_role = approved.assigned_role 

    hashed_password = security.get_password_hash(user.password)
    new_user = models.User(username=user.username, password_hash=hashed_password, role=assigned_role)
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    return {"message": f"User {user.username} created successfully as a {assigned_role}!"}

@app.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == form_data.username).first()
    if not user or not security.verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    
    access_token = security.create_access_token(data={"sub": user.username, "role": user.role})
    
    return {
        "access_token": access_token, 
        "token_type": "bearer",
        "role": user.role,
        "user_id": user.id
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
    existing_doc = db.query(models.Document).filter(models.Document.filename == file.filename).first()
    if existing_doc:
        raise HTTPException(status_code=400, detail=f"The file '{file.filename}' already exists! Please rename your file and try again.")

    # 1. Save to PostgreSQL
    new_doc = models.Document(
        filename=file.filename, 
        uploaded_by=user.username,
        subject_id=subject_id 
    )
    db.add(new_doc)
    db.commit()

    # 2. Read the file content safely
    content = await file.read()

    # --- THE MISSING LINK: SAVE THE PHYSICAL FILE TO THE FOLDER! ---
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_path, "wb") as f:
        f.write(content)

    text = ""
    filename = file.filename.lower()
    
    try:
        # --- PDF FILES (THE LAYOUT PRESERVER) ---
        if filename.endswith(".pdf"):
            import pdfplumber
            try:
                # PLAN A: Extract text while preserving the exact visual layout!
                with pdfplumber.open(file_path) as pdf:
                    for page in pdf.pages:
                        # layout=True forces the computer to respect column spacing
                        extracted_text = page.extract_text(layout=True)
                        if extracted_text:
                            text += extracted_text + "\n\n"
            except Exception as e:
                print(f"pdfplumber layout extraction failed: {e}")
            
            # PLAN C: THE NUCLEAR OPTION (OpenCV + OCR)
            if not text.strip():
                print("PDF text is blank. Deploying OpenCV + Tesseract OCR...")
                import pytesseract
                import pdfplumber
                import cv2
                import numpy as np
                
                try:
                    with pdfplumber.open(file_path) as pdf:
                        for page in pdf.pages:
                            # 1. Get the raw image
                            pil_image = page.to_image(resolution=300).original
                            
                            # 2. Convert to OpenCV format
                            img_cv = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
                            
                            # 3. Wash the Image (Grayscale)
                            gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
                            
                            # 4. Remove Watermarks (Binarization/Thresholding)
                            # This turns anything darker than a certain gray into pure black, and the rest to pure white.
                            _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
                            
                            # 5. Scan the clean image (psm 6 tells it to read it as a uniform block of text/table)
                            custom_config = r'--oem 3 --psm 6'
                            clean_text = pytesseract.image_to_string(thresh, config=custom_config)
                            
                            text += clean_text + "\n\n"
                except Exception as e:
                    print(f"OpenCV/OCR failed: {e}")
                    
        # --- MICROSOFT WORD FILES ---
        elif filename.endswith(".docx"):
            doc = docx.Document(io.BytesIO(content))
            text = "\n".join([paragraph.text for paragraph in doc.paragraphs])
            
        # --- EXCEL SPREADSHEETS ---
        elif filename.endswith((".xlsx", ".xls")):
            # pandas reads the Excel file in memory and converts it to a clean string table
            df = pd.read_excel(io.BytesIO(content))
            text = df.to_string(index=False)

        # --- IMAGES (OCR) ---
        elif filename.endswith((".png", ".jpg", ".jpeg")):
            img = Image.open(io.BytesIO(content))
            # Tesseract scans the image pixels and extracts the text
            text = pytesseract.image_to_string(img)
            
        # --- PLAIN TEXT & CSV ---
        elif filename.endswith((".txt", ".md", ".csv")):
            text = content.decode("utf-8")
            
        else:
            raise ValueError(f"Unsupported file extension: {filename}")
            
    except Exception as e:
        db.delete(new_doc) # Rollback the database if reading fails
        db.commit()
        raise HTTPException(status_code=400, detail=f"Failed to read file format: {str(e)}")

    # 3. Split and tag the text

    # --- ADD THIS DEBUG LINE ---
    print("\n" + "="*50)
    print("DEBUG: THIS IS WHAT THE AI SEES:")
    print(text)
    print("="*50 + "\n")
    # ---------------------------

    # --- THE SAFETY NET (ADD THIS) ---
    if not text.strip():
        db.delete(new_doc)
        db.commit()
        raise HTTPException(status_code=400, detail="Could not read any text from this file. It might be an image-only PDF.")

    from langchain_text_splitters import RecursiveCharacterTextSplitter
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=3000, chunk_overlap=800)
    chunks = text_splitter.split_text(text)
    
    metadata_tag = "global" if subject_id is None else str(subject_id)
    metadatas = [{"source": file.filename, "subject_id": metadata_tag} for _ in chunks]
    
    # 4. Save to Vector Database
    from processor import CHROMA_PATH, embeddings
    from langchain_community.vectorstores import Chroma
    vector_db = Chroma(persist_directory=CHROMA_PATH, embedding_function=embeddings)
    vector_db.add_texts(texts=chunks, metadatas=metadatas)
    
    return {"message": f"Successfully uploaded {file.filename}"}

@app.get("/documents/")
def get_documents(subject_id: Optional[int] = None, db: Session = Depends(get_db)):
    if subject_id:
        docs = db.query(models.Document).filter(models.Document.subject_id == subject_id).all()
    else:
        docs = db.query(models.Document).filter(models.Document.subject_id == None).all()
        
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
    
    doc = db.query(models.Document).filter(models.Document.id == doc_id).first()
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
        messages = db.query(models.ChatMessage).filter(models.ChatMessage.session_id == session_id).order_by(models.ChatMessage.created_at).all()
        return {"messages": [{"role": m.role, "content": m.content, "sources": m.sources or []} for m in messages]}
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
            new_session = models.ChatSession(user_id=user.id, title=question[:30])
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
        
        # Build the exact filter ChromaDB demands
        if filename:
            search_filter = {
                "$and": [
                    {"subject_id": target_subject},
                    {"source": filename}
                ]
            }
        else:
            search_filter = {
                "subject_id": target_subject
            }

        # 👉 THIS IS THE ONLY SEARCH COMMAND WE NEED NOW
        raw_results = vector_db.similarity_search_with_score(search_query, k=15, filter=search_filter)

        # Quality Control Filter
        docs = []
        for doc, score in raw_results:
            print(f"DEBUG - File: {os.path.basename(doc.metadata.get('source', 'Unknown'))}, Score: {score}") 
            if score < 1.8:  # Keep it relaxed, Groq will filter the garbage!
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
        
        # --- THE DYNAMIC BRAIN SWAP ---
        if ai_mode:
            # 🧠 GENERAL AI MODE: Relaxed rules, allowed to use internet knowledge
            system_prompt = (
                "You are KnowCamp AI, an advanced and highly intelligent academic tutor. "
                "You have access to the user's uploaded documents as Context, but you are ALSO allowed to use your vast general world knowledge.\n\n"
                "INSTRUCTIONS:\n"
                "1. If the user's question can be answered using the Context, prioritize using that specific information.\n"
                "2. If the user asks you to 'expand', 'explain more', or asks a general question not found in the Context, seamlessly use your general knowledge to provide a highly detailed, comprehensive, and helpful answer.\n"
                "3. You must maintain the context of the ongoing conversation.\n"
                "4. CITATION REQUIREMENT: If you pull specific facts from the provided context, end your response with 'SOURCES: filename1.ext'. "
                "If your answer relies primarily on your general knowledge, you MUST end your response with EXACTLY 'SOURCES: General World Knowledge'. Do not omit the SOURCES line.\n\n"
                f"Context:\n{context}"
            )
        else:
            # 📚 STRICT DOC MODE: The original closed-book exam rules
            system_prompt = (
                "You are KnowCamp AI. You are taking a strict closed-book exam. "
                "You MUST answer the user's question using ONLY the provided Context. "
                "UNDER NO CIRCUMSTANCES are you allowed to use general knowledge. "
                "If the answer cannot be logically deduced from the Context, you must reply with EXACTLY: 'Information not found in the uploaded documents.'\n\n"
                "CRITICAL REASONING GUIDELINES:\n"
                "1. Tabular Data: Logically connect row and column headers.\n"
                "2. Academic Synonyms: Treat Roman numerals and numbers identically.\n"
                "3. CITATION REQUIREMENT: If you use the provided context to answer the question, you MUST append a line at the very end of your response exactly like this: 'SOURCES: filename1.ext, filename2.ext'. "
                "Only list the EXACT filenames of the documents you actually used.\n\n"
                f"Context:\n{context}"
            )
        # -----------------------------------------------

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
            
            if "Information not found" in raw_answer:
                # Force a clean answer and wipe out any confused LLM citations!
                final_answer = "I couldn't find any relevant information in the uploaded documents."
                sources_list = []
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

    existing = db.query(models.ApprovedEmail).filter(models.ApprovedEmail.email == request.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email is already on the whitelist.")

    new_approval = models.ApprovedEmail(email=request.email, assigned_role=request.assigned_role)
    db.add(new_approval)
    db.commit()
    return {"message": f"Added {request.email} as {request.assigned_role}"}

@app.get("/admin/whitelist/")
def get_whitelist(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    payload = jwt.decode(token, security.SECRET_KEY, algorithms=[security.ALGORITHM])
    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only admins can do this.")
        
    emails = db.query(models.ApprovedEmail).all()
    return {"whitelist": [{"id": e.id, "email": e.email, "role": e.assigned_role} for e in emails]}

@app.delete("/admin/whitelist/{email_id}")
def remove_from_whitelist(email_id: int, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    payload = jwt.decode(token, security.SECRET_KEY, algorithms=[security.ALGORITHM])
    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only admins can do this.")
        
    record = db.query(models.ApprovedEmail).filter(models.ApprovedEmail.id == email_id).first()
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

    users = db.query(models.User).all()
    return {"users": [{"id": u.id, "username": u.username, "role": u.role} for u in users]}

@app.delete("/admin/users/{user_id}")
def delete_active_user(user_id: int, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    payload = jwt.decode(token, security.SECRET_KEY, algorithms=[security.ALGORITHM])
    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only admins can do this.")

    user = db.query(models.User).filter(models.User.id == user_id).first()
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
        faculty_id=user.id 
    )
    db.add(new_subject)
    db.commit()
    db.refresh(new_subject)
    
    return {"message": "Class created!", "invite_code": invite_code}

@app.post("/subjects/join/")
def join_subject(req: JoinSubject, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    payload = jwt.decode(token, security.SECRET_KEY, algorithms=[security.ALGORITHM])
    user = db.query(models.User).filter(models.User.username == payload.get("sub")).first()
    
    subject = db.query(models.Subject).filter(models.Subject.invite_code == req.invite_code).first()
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
        subjects = db.query(models.Subject).all()
        
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
        import jwt
        payload = jwt.decode(token, security.SECRET_KEY, algorithms=[security.ALGORITHM])
        username = payload.get("sub")
        current_user = db.query(models.User).filter(models.User.username == username).first()
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid Authentication Token")

    if not current_user:
        raise HTTPException(status_code=401, detail="User not found")

    # (Authorization block removed so Students can view the roster)

    subject = db.query(models.Subject).filter(models.Subject.id == subject_id).first()
    if not subject:
        raise HTTPException(status_code=404, detail="Class not found")

    enrollments = db.query(models.Enrollment).filter(models.Enrollment.subject_id == subject_id).all()
    
    student_list = []
    for enrollment in enrollments:
        student = db.query(models.User).filter(models.User.id == enrollment.student_id).first()
        if student:
            student_list.append({
                "id": student.id,
                "username": student.username,
                "role": student.role
            })

    return {"students": student_list}

# ---> YOUR @app.delete("/subjects/{subject_id}/students/{student_id}") STARTS RIGHT HERE <---

@app.delete("/subjects/{subject_id}/students/{student_id}")
def remove_student_from_class(
    subject_id: int, 
    student_id: int, 
    token: str = Depends(oauth2_scheme), 
    db: Session = Depends(get_db)
):
    # 1. Authenticate the User
    try:
        import jwt
        # Adjust 'security.SECRET_KEY' and 'security.ALGORITHM' to match your actual imports
        payload = jwt.decode(token, security.SECRET_KEY, algorithms=[security.ALGORITHM])
        username = payload.get("sub")
        current_user = db.query(models.User).filter(models.User.username == username).first()
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid Authentication Token")

    if not current_user:
        raise HTTPException(status_code=401, detail="User not found")

    # ... [Step 1: Authenticate User remains the same] ...

    # 2. Check Authorization & Ownership (Strict RBAC)
    # Block students immediately
    if current_user.role == "student":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Access Denied. Students cannot remove users."
        )

    # Fetch the class
    subject = db.query(models.Subject).filter(models.Subject.id == subject_id).first()
    if not subject:
        raise HTTPException(status_code=404, detail="Class not found.")

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
    # 1. Authenticate the User
    try:
        import jwt
        payload = jwt.decode(token, security.SECRET_KEY, algorithms=[security.ALGORITHM])
        username = payload.get("sub")
        current_user = db.query(models.User).filter(models.User.username == username).first()
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid Authentication Token")

    # 2. Strict Admin-Only Authorization
    if not current_user or current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Absolute Access Denied. Only Admins can remove faculty from a class."
        )

    # 3. Fetch the Subject
    subject = db.query(models.Subject).filter(models.Subject.id == subject_id).first()
    if not subject:
        raise HTTPException(status_code=404, detail="Class not found.")

    if subject.faculty_id is None:
        return {"message": "This class currently has no faculty assigned."}

    # 4. Safely remove the faculty member (DOES NOT delete their account)
    try:
        subject.faculty_id = None  # Erase the professor from the class
        db.commit()
        return {"message": f"Successfully removed faculty from {subject.name}."}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")