import pytest
from src.embedding.embedding import EmbeddingGenerator
from src.docs_processing.docs_processor import DocumentChunk


def test_generate_embedding_without_model_raises_clear_error():
    svc = EmbeddingGenerator.__new__(EmbeddingGenerator)  # bypass __init__
    svc.model = None
    svc.use_cache = False
    svc.cache_manager = None
    chunk = DocumentChunk(content="hello world", source_file="test.pdf")
    with pytest.raises(RuntimeError, match="model"):
        svc.generate_embedding([chunk])


def test_batch_generate_without_model_raises_clear_error():
    svc = EmbeddingGenerator.__new__(EmbeddingGenerator)
    svc.model = None
    svc.use_cache = False
    svc.cache_manager = None
    with pytest.raises(RuntimeError, match="model"):
        svc.generate_query_embedding("hello world")
