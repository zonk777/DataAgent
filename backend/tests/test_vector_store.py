from app.config import Settings
from app.services.vector_store import _collection_name, _embedding_url, _qdrant_store_label


def test_embedding_url_accepts_full_endpoint() -> None:
    settings = Settings(
        embedding_api_key="test",
        embedding_base_url="https://example.com/v1/embeddings",
        embedding_model="example/model",
    )
    assert _embedding_url(settings) == "https://example.com/v1/embeddings"


def test_embedding_url_appends_endpoint_to_base_url() -> None:
    settings = Settings(
        embedding_api_key="test",
        embedding_base_url="https://example.com/v1",
        embedding_model="example/model",
    )
    assert _embedding_url(settings) == "https://example.com/v1/embeddings"


def test_collection_is_stable_and_model_specific() -> None:
    assert _collection_name("model-a") == _collection_name("model-a")
    assert _collection_name("model-a") != _collection_name("model-b")


def test_qdrant_store_label_distinguishes_server_and_local() -> None:
    local = Settings(embedding_api_key="test", embedding_base_url="https://example.com/v1", qdrant_url="")
    server = Settings(embedding_api_key="test", embedding_base_url="https://example.com/v1", qdrant_url="http://127.0.0.1:6333")

    assert _qdrant_store_label(local) == "qdrant-local"
    assert _qdrant_store_label(server) == "qdrant-server"

