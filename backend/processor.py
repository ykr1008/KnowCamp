import os
from dotenv import load_dotenv
from langchain_huggingface import HuggingFaceEmbeddings
from pinecone import Pinecone

load_dotenv()

# Embeddings model (same as before)
embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-mpnet-base-v2")

# Pinecone client
pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
pinecone_index = pc.Index(host=os.getenv("PINECONE_HOST"))

# Keep CHROMA_PATH for any legacy code (won't be used)
CHROMA_PATH = "chroma_db"