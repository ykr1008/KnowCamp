from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean, JSON
from sqlalchemy.orm import relationship
from database import Base
import datetime

# ==========================================
# 1. SECURITY & USERS
# ==========================================

class ApprovedEmail(Base):
    """Admin Whitelist: Only emails in this table can register for an account."""
    __tablename__ = "approved_emails"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    assigned_role = Column(String) # 'admin', 'faculty', or 'student'

class User(Base):
    """The main user table for Admin, Faculty, and Students."""
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True) # This acts as their email
    password_hash = Column(String)
    role = Column(String) # 'admin', 'faculty', or 'student'
    
    # Relationships (Allows us to easily fetch a user's chats or classes)
    chat_sessions = relationship("ChatSession", back_populates="user")
    enrollments = relationship("Enrollment", back_populates="student")
    subjects_taught = relationship("Subject", back_populates="faculty")


# ==========================================
# 2. ACADEMICS (The "Google Classroom" logic)
# ==========================================

class Subject(Base):
    """Represents a specific class, e.g., 'Java Programming - 2nd Year'"""
    __tablename__ = "subjects"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    year = Column(String) # e.g., "1st Year", "2nd Year"
    invite_code = Column(String, unique=True, index=True) # The 6-digit code to join
    
    faculty_id = Column(Integer, ForeignKey("users.id"))
    faculty = relationship("User", back_populates="subjects_taught")
    
    enrollments = relationship("Enrollment", back_populates="subject", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="subject", cascade="all, delete-orphan")
    chat_sessions = relationship("ChatSession", back_populates="subject", cascade="all, delete-orphan") # <-- THIS IS THE CRUCIAL LINE

class Enrollment(Base):
    """Linking table: Connects a Student to a Subject using the invite code."""
    __tablename__ = "enrollments"
    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("users.id"))
    subject_id = Column(Integer, ForeignKey("subjects.id"))
    
    student = relationship("User", back_populates="enrollments")
    subject = relationship("Subject", back_populates="enrollments")


# ==========================================
# 3. KNOWLEDGE BASE (The RAG Engine)
# ==========================================

class Document(Base):
    """Stores the files uploaded by Admins and Faculty."""
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, unique=True, index=True) # Block duplicates!
    uploaded_by = Column(String)
    upload_date = Column(DateTime, default=datetime.datetime.utcnow)
    
    category = Column(String) # 'general' (Admin Circulars) OR 'subject_notes' (Faculty)
    
    # If it's a faculty note, it gets linked to a specific Subject ID
    subject_id = Column(Integer, ForeignKey("subjects.id"), nullable=True)
    subject = relationship("Subject", back_populates="documents")


# ==========================================
# 4. CHAT HISTORY (The AI Memory)
# ==========================================

class ChatSession(Base):
    """Represents one conversation thread (Shows up in the left sidebar)."""
    __tablename__ = "chat_sessions"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    subject_id = Column(Integer, ForeignKey("subjects.id"), nullable=True) # <-- NEW COLUMN
    title = Column(String, default="New Chat")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    user = relationship("User", back_populates="chat_sessions")
    subject = relationship("Subject", back_populates="chat_sessions") # <-- MATCHING RELATIONSHIP
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete")

class ChatMessage(Base):
    """Individual bubbles inside a ChatSession."""
    __tablename__ = "chat_messages"
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id"))
    role = Column(String) # 'user' or 'ai'
    content = Column(Text)

    sources = Column(JSON, default=list, nullable=True) # New column to store source documents for RAG responses
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    session = relationship("ChatSession", back_populates="messages")