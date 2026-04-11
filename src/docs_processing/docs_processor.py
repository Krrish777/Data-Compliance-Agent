"""
This module defines the DocumentProcessor class which processes PDF documents into chunks with metadata for rule extraction.
It includes:
- DocumentChunk dataclass to represent individual chunks of text with associated metadata.
- DocumentProcessor class to handle PDF processing, text extraction, chunking, and metadata enrichment.
The processor uses PyMuPDF for PDF handling and includes robust logging for tracing the processing steps.
"""
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from pathlib import Path
import hashlib
from datetime import datetime
import re
import pymupdf
from src.utils.logger import setup_logger
from src.utils.document_cache import CacheManager

log = setup_logger(__name__)

MAX_PAGES = 200
MAX_FILE_MB = 50

@dataclass
class DocumentChunk:
    """Represents a processed document chunk with metadata"""
    content: str
    source_file: str
    page_number: Optional[int] = None
    chunk_index: int = 0
    start_chunks: Optional[int] = None
    end_chunks: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None
    chunk_id: str = ""
    
    def __post_init__(self):
        if not self.chunk_id:
            self.chunk_id = self._generate_chunk_id()
        if self.metadata is None:
            self.metadata = {}
            
    def _generate_chunk_id(self) -> str:
        content_hash = hashlib.md5(self.content.encode('utf-8')).hexdigest()[:8]
        return f"{self.source_file}_{self.chunk_index}_{content_hash}"
    
    def get_citation_info(self) -> Dict[str, Any]:
        citation = {
            'source': self.source_file,
            'chunk_id': self.chunk_id,
            'chunk_index': self.chunk_index
        }
        if self.page_number is not None:
            citation['page_number'] = self.page_number
        if self.start_chunks or self.end_chunks:
            citation['char_range'] = f"{self.start_chunks}-{self.end_chunks}"
            
        if self.metadata:
            citation.update(self.metadata)
        return citation

class DocumentProcessor:
    """Processes PDF documents into chunks with metadata"""
    def __init__(
        self, 
        chunk_size: int = 1000, 
        chunk_overlap: int = 200,
        cache_manager: Optional[CacheManager] = None,
        use_cache: bool = True
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.cache_manager = cache_manager
        self.use_cache = use_cache and cache_manager is not None
        
        if self.use_cache:
            log.info("DocumentProcessor: Cache ENABLED")
        else:
            log.info("DocumentProcessor: Cache DISABLED")
    
    def _detect_section(self, text: str) -> Optional[str]:
        """Detect if chunk starts with a section/article header"""
        patterns = [
            r'^Article\s+\d+',
            r'^Section\s+\d+[.:]?',
            r'^\d+\.\s+[A-Z][a-z]+',
            r'^Chapter\s+\d+',
            r'^Part\s+[IVX]+',
        ]
        text_stripped = text.strip()
        for pattern in patterns:
            match = re.match(pattern, text_stripped, re.MULTILINE)
            if match:
                return match.group(0)
        return None
    
    def get_aggregated_context(
        self, 
        chunks: List[DocumentChunk], 
        chunk_index: int, 
        context_window: int = 1
    ) -> str:
        """Get chunk with surrounding context for better rule extraction"""
        start_idx = max(0, chunk_index - context_window)
        end_idx = min(len(chunks), chunk_index + context_window + 1)
        
        context_chunks = chunks[start_idx:end_idx]
        return "\n\n".join([c.content for c in context_chunks])
    
    # PDF processing unit    
    def process_pdf(self, file_path: str) -> List[DocumentChunk]:
        file_path_obj = Path(file_path)
        
        if not file_path_obj.exists() or not file_path_obj.is_file():
            log.error(f"File not found: {file_path}")
            raise FileNotFoundError(f"File not found: {file_path}")
            
        if file_path_obj.suffix.lower() != '.pdf':
            log.error(f"Unsupported file type: {file_path_obj.suffix}")
            raise ValueError(f"Unsupported file type: {file_path_obj.suffix}")
        
        # Try cache first
        if self.use_cache and self.cache_manager:
            cached_chunks = self.cache_manager.get_document_chunks(
                file_path=str(file_path_obj.absolute()),
                chunk_size=self.chunk_size,
                chunk_overlap=self.chunk_overlap
            )
            if cached_chunks:
                log.info(f"📦 Loaded {len(cached_chunks)} chunks from cache: {file_path_obj.name}")
                return cached_chunks
        
        log.info(f"Processing PDF: {file_path_obj.name}")
    
        try:
            chunks = self._process_pdf(file_path_obj)
            
            # Cache the results
            if self.use_cache and self.cache_manager:
                self.cache_manager.set_document_chunks(
                    file_path=str(file_path_obj.absolute()),
                    chunks=chunks,
                    chunk_size=self.chunk_size,
                    chunk_overlap=self.chunk_overlap
                )
            
            return chunks
        except Exception as e:
            log.error(f"Error processing PDF: {e}")
            raise
        
        
    def _process_pdf(self, file_path: Path) -> List[DocumentChunk]:
        # Guard: reject files that exceed the size limit
        size_mb = file_path.stat().st_size / 1024 / 1024
        if size_mb > MAX_FILE_MB:
            raise ValueError(
                f"PDF too large: {size_mb:.1f} MB (limit {MAX_FILE_MB} MB)"
            )

        chunks = []
        try:
            with pymupdf.open(file_path) as doc:
                total_pages = len(doc)
                log.info(f"Total pages in document: {total_pages}")

                if total_pages > MAX_PAGES:
                    log.warning(
                        f"Truncating PDF to {MAX_PAGES} pages (was {total_pages})"
                    )
                    total_pages = MAX_PAGES

                for page_num in range(total_pages):
                    page = doc.load_page(page_num)
                    text = page.get_text()
                    log.info(f"Extracted text from page {page_num + 1}")

                    # Ensure text is a string
                    if not isinstance(text, str):
                        text = str(text)

                    if not text.strip():
                        log.warning(f"No text found on page {page_num + 1}")
                        continue

                    page_metadata = {
                        'total_pages': total_pages,
                        'page_width': page.rect.width,
                        'page_height': page.rect.height,
                        'extracted_at': datetime.now().isoformat()
                    }
                    page_chunks = self._chunk_text(
                        text,
                        file_path.name,
                        page_num=page_num+1,
                        additional_metadata=page_metadata
                    )
                    chunks.extend(page_chunks)

            log.info(f"Finished processing PDF: {len(chunks)} chunks from {total_pages} pages")

        except Exception as e:
            log.error(f"Error processing PDF {file_path}: {e}")
            raise

        log.info(f"Chunk details: {[chunk.get_citation_info() for chunk in chunks]}")

        return chunks
    
    # Chunking unit
    def _chunk_text(
        self,
        text: str,
        source_file: str,
        page_num: Optional[int] = None,
        additional_metadata: Optional[Dict[str, Any]] = None
    ) -> List[DocumentChunk]:
        
        if not text.strip():
            log.warning(f"No text to chunk for {source_file} page {page_num}")
            return []
        
        chunks = []
        start = 0
        chunk_index = 0
        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            if end < len(text):
                last_period = text.rfind('.', start, end)
                last_newline = text.rfind('\n', start, end)
                boundary = max(last_period, last_newline)
                if boundary > start + self.chunk_size * 0.5:
                    end = boundary + 1
                    
            chunk_text = text[start:end].strip()
            
            if chunk_text:
                chunk_metadata = additional_metadata.copy() if additional_metadata else {}
                
                # Add rule extraction metadata
                chunk_metadata['section_header'] = self._detect_section(chunk_text)
                chunk_metadata['has_obligation_language'] = any(
                    word in chunk_text.lower() 
                    for word in ['must', 'shall', 'required to', 'prohibited', 'obligation']
                )
                
                chunk = DocumentChunk(
                    content=chunk_text,
                    source_file=source_file,
                    page_number=page_num,
                    chunk_index=chunk_index,
                    start_chunks=start,
                    end_chunks=end-1,
                    metadata=chunk_metadata
                )
                
                chunks.append(chunk)
                log.info(f"Created chunk {chunk.chunk_id} from {source_file} page {page_num} (chars {start}-{end-1})")
                chunk_index += 1
                
            start = max(start + self.chunk_size - self.chunk_overlap, end)
            if start >= len(text):
                log.info(f"Reached end of text for {source_file} page {page_num}")
                break
            
        return chunks
    
    # Batch processing unit
    def batch_process(self, file_paths: List[str]) -> Dict[str, List[DocumentChunk]]:
        all_chunks = {}
        for file_path in file_paths:
            try:
                chunks = self.process_pdf(file_path)
                all_chunks[file_path] = chunks
                log.info(f"Processed {file_path}: {len(chunks)} chunks")
            except Exception as e:
                log.error(f"Failed to process {file_path}: {e}")
                continue
        
        log.info(f"Batch processing complete: {len(all_chunks)} files processed")
        return all_chunks
