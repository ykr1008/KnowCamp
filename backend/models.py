from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean, JSON
from sqlalchemy.orm import relationship
from database import Base
import datetime

# ==========================================
# 0. SAAS FOUNDATION (Tenant Isolation)
# ==========================================

class Institution(Base):
    """The 'Tenant' in our SaaS model. Every user and class belongs to one institution."""
    __tablename__ = "institutions"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True) # e.g., "MIT", "Stanford"
    domain = Column(String, unique=True, index=True, nullable=True) # Optional: for custom login URLs
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    # Relationships: If an institution is deleted, ALL their data is wiped (Cascade)
    users = relationship("User", back_populates="institution", cascade="all, delete-orphan")
    subjects = relationship("Subject", back_populates="institution", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="institution", cascade="all, delete-orphan")
    approved_emails = relationship("ApprovedEmail", back_populates="institution", cascade="all, delete-orphan")


# ==========================================
# 1. SECURITY & USERS
# ==========================================

class ApprovedEmail(Base):
    """Admin Whitelist: Only emails in this table can register for an account."""
    __tablename__ = "approved_emails"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    assigned_role = Column(String) # 'admin', 'faculty', or 'student'
    
    institution_id = Column(Integer, ForeignKey("institutions.id")) # <-- SAAS UPGRADE
    institution = relationship("Institution", back_populates="approved_emails")

class User(Base):
    """The main user table for Admin, Faculty, and Students."""
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True) # This acts as their email
    password_hash = Column(String)
    role = Column(String) # 'admin', 'faculty', or 'student'
    
    institution_id = Column(Integer, ForeignKey("institutions.id")) # <-- SAAS UPGRADE
    institution = relationship("Institution", back_populates="users")
    
    # Relationships
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
    
    institution_id = Column(Integer, ForeignKey("institutions.id")) # <-- SAAS UPGRADE
    institution = relationship("Institution", back_populates="subjects")
    
    faculty_id = Column(Integer, ForeignKey("users.id"))
    faculty = relationship("User", back_populates="subjects_taught")
    
    enrollments = relationship("Enrollment", back_populates="subject", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="subject", cascade="all, delete-orphan")
    chat_sessions = relationship("ChatSession", back_populates="subject", cascade="all, delete-orphan")

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
    filename = Column(String, unique=True, index=True) 
    uploaded_by = Column(String)
    upload_date = Column(DateTime, default=datetime.datetime.utcnow)
    category = Column(String) # 'general' (Admin Circulars) OR 'subject_notes' (Faculty)
    
    institution_id = Column(Integer, ForeignKey("institutions.id")) # <-- SAAS UPGRADE
    institution = relationship("Institution", back_populates="documents")
    
    subject_id = Column(Integer, ForeignKey("subjects.id"), nullable=True)
    subject = relationship("Subject", back_populates="documents")


# ==========================================
# 4. CHAT HISTORY (The AI Memory)
# ==========================================

class ChatSession(Base):
    """Represents one conversation thread."""
    __tablename__ = "chat_sessions"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    subject_id = Column(Integer, ForeignKey("subjects.id"), nullable=True) 
    title = Column(String, default="New Chat")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    user = relationship("User", back_populates="chat_sessions")
    subject = relationship("Subject", back_populates="chat_sessions") 
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete")

class ChatMessage(Base):
    """Individual bubbles inside a ChatSession."""
    __tablename__ = "chat_messages"
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id"))
    role = Column(String) # 'user' or 'ai'
    content = Column(Text)
    sources = Column(JSON, default=list, nullable=True) 
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    session = relationship("ChatSession", back_populates="messages")