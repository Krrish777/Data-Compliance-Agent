from typing import List, Dict, Any, Optional
import json
import uuid

# Replaced pymilvus with qdrant_client for local support on Windows
from qdrant_client import QdrantClient, models
from src.embedding.embedding import EmbeddedChunk
from src.utils.logger import setup_logger

log = setup_logger(__name__)


class LocalVectorDB:
    def __init__(
        self, 
        db_path: str = "./qdrant_db",
        collection_name: str = "document_chunks",
        embedding_dim: int = 384
    ):
        self.db_path = db_path
        self.collection_name = collection_name
        self.embedding_dim = embedding_dim
        self.client = None
        self.collection_exists = False
        
        self._initialize_client()
        self._setup_collection()
    
    def _initialize_client(self):
        try:
            # Initialize Qdrant for local storage
            self.client = QdrantClient(path=self.db_path)
            log.info(f"Qdrant client initialized with database: {self.db_path}")
            
        except Exception as e:
            log.error(f"Failed to initialize Qdrant client: {str(e)}")
            raise
    
    def _setup_collection(self):
        try:
            if not self.client:
                log.error("Qdrant client is not initialized")
                raise
            
            if self.client.collection_exists(collection_name=self.collection_name):
                log.info(f"Collection '{self.collection_name}' already exists")
                self.collection_exists = True
                return
            
            # Create collection with vector parameters
            # Using Euclidean distance to match previous L2 metric
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(
                    size=self.embedding_dim,
                    distance=models.Distance.EUCLID 
                )
            )
            
            log.info(f"Collection '{self.collection_name}' created successfully")
            self.collection_exists = True
            
        except Exception as e:
            log.error(f"Error setting up collection: {str(e)}")
            raise
    
    def create_index(
        self,
        use_binary_quantization: bool = False,
        nlist: int = 1024,
        enable_refine: bool = False,
        refine_type: str = "SQ8"
    ):
        # Qdrant handles indexing automatically (HNSW).
        # Keeping this method for interface compatibility.
        log.info("Index configuration is handled by Qdrant (HNSW by default).")
        pass
    
    def insert_embeddings(self, embedded_chunks: List[EmbeddedChunk]) -> List[str]:
        if not embedded_chunks:
            return []
        try:
            points = []
            inserted_ids = []
            
            for embedded_chunk in embedded_chunks:
                chunk_data = embedded_chunk.to_vector_db_format()  
                
                # Get ID and generate deterministic UUID for Qdrant
                original_id = chunk_data.get('id')
                if original_id:
                    # Create a deterministic UUID from the string ID
                    p_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, str(original_id)))
                else:
                    p_id = str(uuid.uuid4())
                
                vector = chunk_data.get('embedding') or chunk_data.get('vector')
                
                # Skip chunks without embeddings
                if not vector:
                    log.warning(f"Skipping chunk {original_id}: no embedding vector found")
                    continue
                
                # Prepare payload
                payload = {k: v for k, v in chunk_data.items() if k not in ['id', 'vector', 'embedding']}
                payload['chunk_id'] = original_id # Store original ID in payload
                
                # Ensure fields are present
                payload['page_number'] = payload.get('page_number') or -1
                payload['start_char'] = payload.get('start_char') or -1
                payload['end_char'] = payload.get('end_char') or -1
                
                if isinstance(payload.get('metadata'), str):
                     try:
                        payload['metadata'] = json.loads(payload['metadata'])
                     except Exception as e:
                        log.warning(f"Failed to parse metadata for chunk {original_id}: {str(e)}")
                        payload['metadata'] = {}

                points.append(models.PointStruct(
                    id=p_id,
                    vector=vector,
                    payload=payload
                ))
                inserted_ids.append(p_id)
            
            self.client.upsert( # type: ignore
                collection_name=self.collection_name,
                points=points
            )
            
            log.info(f"Inserted {len(inserted_ids)} embeddings into database")
            
            return inserted_ids
            
        except Exception as e:
            log.error(f"Error inserting embeddings: {str(e)}")
            raise
    
    def search(
        self,
        query_vector: List[float],
        limit: int = 10,
        nprobe: int = 128,
        rbq_query_bits: int = 0,
        refine_k: float = 1.0,
        filter_expr: Optional[str] = None,
        use_binary_quantization: bool = False
    ) -> List[Dict[str, Any]]:
        try:
            # Handle filter if necessary. For now ignoring simple string filters as Qdrant uses Filter objects.
            query_filter = None
            if filter_expr:
                log.warning(f"Filter expression '{filter_expr}' ignored in Qdrant implementation.")

            results = self.client.query_points( # type: ignore
                collection_name=self.collection_name,
                query=query_vector,
                limit=limit,
                query_filter=query_filter,
                with_payload=True
            ).points
            
            formatted_results = []
            if results:
                for result in results:
                    payload = result.payload
                    formatted_result = {
                        'id': result.id,
                        'score': result.score,
                        'content': payload.get('content'), # type: ignore
                    'citation': {
                        'source_file': payload.get('source_file'), # type: ignore
                        'source_type': payload.get('source_type'), # type: ignore
                        'page_number': payload.get('page_number') if payload.get('page_number') != -1 else None, # pyright: ignore[reportOptionalMemberAccess]
                        'chunk_index': payload.get('chunk_index'), # type: ignore
                        'start_char': payload.get('start_char') if payload.get('start_char') != -1 else None, # type: ignore
                        'end_char': payload.get('end_char') if payload.get('end_char') != -1 else None, # type: ignore
                    },
                    'metadata': payload.get('metadata'), # type: ignore
                    'embedding_model': payload.get('embedding_model') # type: ignore
                    }
                    formatted_results.append(formatted_result)
            
            log.info(f"Search completed: {len(formatted_results)} results found")
            return formatted_results
            
        except Exception as e:
            log.error(f"Error during search: {str(e)}")
            raise
    
    def delete_collection(self):
        try:
            if self.client.collection_exists(collection_name=self.collection_name): # type: ignore
                self.client.delete_collection(collection_name=self.collection_name) # type: ignore
                log.info(f"Collection '{self.collection_name}' deleted")
                self.collection_exists = False
            else:
                log.info(f"Collection '{self.collection_name}' does not exist")
                
        except Exception as e:
            log.error(f"Error deleting collection: {str(e)}")
            raise
    
    def get_chunk_by_id(self, chunk_id: str) -> Optional[Dict[str, Any]]:
        try:
            if not self.collection_exists:
                log.warning("Collection does not exist")
                return None
            
            log.info(f"Attempting to retrieve chunk with ID: {chunk_id}")
            
            results = self.client.retrieve( # type: ignore
                collection_name=self.collection_name,
                ids=[chunk_id],
                with_payload=True
            )
            
            log.info(f"Query returned {len(results) if results else 0} results")
            
            if results:
                point = results[0]
                payload = point.payload
                log.info(f"Successfully retrieved chunk: {point.id}")
                
                return {
                    "id": point.id,
                    "content": payload.get("content"), # type: ignore
                    "metadata": payload.get("metadata"), # type: ignore
                    "source_file": payload.get("source_file"), # type: ignore
                    "source_type": payload.get("source_type"), # type: ignore
                    "page_number": payload.get("page_number"), # type: ignore
                    "chunk_index": payload.get("chunk_index") # type: ignore
                }
            
            log.warning(f"No chunk found with ID: {chunk_id}")
            return None
            
        except Exception as e:
            log.error(f"Error retrieving chunk by ID {chunk_id}: {str(e)}")
            return None
    
    def close(self):
        try:
            if hasattr(self.client, 'close'):
                self.client.close() # type: ignore
                log.info("Qdrant client connection closed")
        except Exception as e:
            log.error(f"Error closing connection: {str(e)}")