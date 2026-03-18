# 🎓 KnowCamp LMS: AI-Powered Enterprise Learning Management System

![React](https://img.shields.io/badge/React-20232A?style=for-the-badge&logo=react&logoColor=61DAFB)
![Vite](https://img.shields.io/badge/Vite-B73BFE?style=for-the-badge&logo=vite&logoColor=FFD62E)
![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi)
![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-316192?style=for-the-badge&logo=postgresql&logoColor=white)

KnowCamp is a next-generation Learning Management System (LMS) that bridges the gap between traditional file sharing and advanced Artificial Intelligence. Built with a modern React frontend and a blazing-fast Python/FastAPI backend, KnowCamp allows educational institutions to upload course materials and instantly generate a hallucination-free, AI-powered teaching assistant based *strictly* on their own documents.

## ✨ Key Features

### 🧠 Enterprise RAG (Retrieval-Augmented Generation) Pipeline
* **Dual-Mode AI:** Users can toggle between **Strict Doc Mode** (The AI acts as a secure data vault, answering *only* from uploaded documents and refusing outside knowledge) and **General AI Mode** (The AI acts as an advisor, combining document context with general world knowledge).
* **The "Relevance Bouncer":** Advanced similarity-score thresholding ensures that the AI only retrieves highly relevant context, completely eliminating "ghost sources" and cross-document contamination.
* **Instant Smart Citations:** The AI dynamically cites the exact uploaded files it used to generate its answers.

### 🔐 Granular Role-Based Access Control (RBAC)
Secure, JWT-driven authentication with three distinct permission tiers:
* **Admins (Global God Mode):** Can manage global documents, oversee all classrooms, and have absolute delete authority.
* **Faculty (Classroom God Mode):** Can create or "claim" orphaned classes, generate invite codes, and manage their proprietary course materials.
* **Students:** Read-only access to classroom materials and AI chat sessions.

### 📂 Advanced Document Management
* **Sequential Bulk Upload Queue:** A sleek, drag-and-drop React dropzone that queues multiple files (PDF, DOCX, CSV) and uploads them sequentially to protect server memory.
* **Lightning-Fast Local Parsing:** Utilizes LangChain's local document loaders to extract and chunk text in milliseconds before vectorizing.
* **Smart Caching:** Cache-busting architecture ensures the UI updates dynamically without requiring hard browser reloads.

## 🛠️ Technology Stack

**Frontend:**
* React.js (Vite)
* Axios (Network Requests)
* Lucide-React (UI Iconography)
* JWT Decoding (Client-side role rendering)

**Backend:**
* Python / FastAPI
* PostgreSQL (Relational Database)
* SQLAlchemy (ORM)
* JSON Web Tokens (JWT) for secure, stateless sessions

**AI & Data Pipeline:**
* LangChain (Document processing and LLM orchestration)
* ChromaDB (Local Vector Database for semantic search)
* Groq Cloud API (Running Llama-3.3-70b-versatile for high-speed inference)

---

## 🚀 Getting Started (Local Development)

### Prerequisites
* Python 3.9+
* Node.js 18+
* PostgreSQL installed and running locally
* A Groq API Key

### 1. Backend Setup (FastAPI)
Navigate to the backend directory, set up your virtual environment, and install dependencies:

```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows use: venv\Scripts\activate
pip install -r requirements.txt

### 🐳 Docker Deployment (Recommended)

To avoid local dependency conflicts (especially with document parsing libraries like `llama-parse`), KnowCamp is fully containerized.

**Prerequisites:**
* Docker Desktop installed and running.

**1. Spin up the Environment:**
Ensure your `.env` file is properly configured, then run the following command from the root directory to build and start all services in detached mode:

```bash
docker-compose up --build -d