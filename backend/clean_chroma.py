from langchain_community.vectorstores import Chroma
from processor import CHROMA_PATH, embeddings

def clean_ghost_vectors():
    print("🔌 Connecting to ChromaDB...")
    vector_db = Chroma(persist_directory=CHROMA_PATH, embedding_function=embeddings)
    
    # 1. Pull EVERYTHING out of the database
    all_data = vector_db.get()
    metadatas = all_data.get('metadatas', [])
    
    if not metadatas:
        print("Database is completely empty.")
        return

    # 2. Extract all the unique "source" names currently inside
    unique_sources = set()
    for meta in metadatas:
        if meta and 'source' in meta:
            unique_sources.add(meta['source'])
            
    print("\n📄 FILES CURRENTLY STUCK IN CHROMADB:")
    print("-" * 40)
    for src in unique_sources:
        print(f" -> {src}")
    print("-" * 40)
    
    # 3. Allow manual surgical deletion
    target = input("\nCopy and paste the exact UUID or filename you want to delete (or press Enter to cancel): ").strip()
    
    if target:
        try:
            vector_db._collection.delete(where={"source": target})
            print(f"\n✅ SUCCESS: All chunks for '{target}' have been surgically removed!")
        except Exception as e:
            print(f"\n❌ Error deleting: {e}")
    else:
        print("\nOperation cancelled.")

if __name__ == "__main__":
    clean_ghost_vectors()