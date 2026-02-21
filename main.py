from src.docs_processing.docs_processor import DocumentProcessor
from src.embedding.embedding import EmbeddingGenerator
from src.vector_database.qdrant_vectordb import LocalVectorDB
from src.agents.tools.database.sqlite_connector import SQLiteConnector
from rich.traceback import install
install()

def main():
    processor = DocumentProcessor()
    embedding = EmbeddingGenerator()
    qdrant = LocalVectorDB()
    chunks = processor.process_pdf("data/raft.pdf")
    embedded_chunks = embedding.generate_embedding(chunks)
    qdrant.insert_embeddings(embedded_chunks)
    
    # Test SQLite connector
    sqlite = SQLiteConnector(db_path="data/HI-Small_Trans.db")
    sqlite.connect()
    sensitive_columns = sqlite.identify_sensitive_columns(sqlite.discover_schema())
    print(f"Total sensitive columns identified: {len(sensitive_columns)}")
    if sensitive_columns:
            print(f"\n{'Table':<15} | {'Column':<25} | {'Data Type':<15} | {'Category':<15}")
            print(f"{'-'*80}")
            for col in sensitive_columns:
                print(f"{col['table']:<15} | {col['column']:<25} | {col['data_type']:<15} | {col['category']:<15}")
        
    
    sqlite.close()
    
if __name__ == "__main__":
    main()