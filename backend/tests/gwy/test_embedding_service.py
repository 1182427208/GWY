import pytest

from app.gwy.llm.embedding_service import EmbeddingService


class FakeEmbeddingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], int | None]] = []

    def embeddings(
        self, texts: list[str], dimensions: int | None = None
    ) -> list[list[float]]:
        self.calls.append((texts, dimensions))
        return [[1.0, 2.0, 3.0] for _ in texts]


def test_embedding_service_returns_vectors() -> None:
    client = FakeEmbeddingClient()
    service = EmbeddingService(client=client, embedding_dim=3)

    vector = service.embed_text("你好")

    assert vector == [1.0, 2.0, 3.0]
    assert client.calls == [(["你好"], 3)]


def test_embedding_service_rejects_blank_text() -> None:
    client = FakeEmbeddingClient()
    service = EmbeddingService(client=client, embedding_dim=3)

    with pytest.raises(ValueError, match="Embedding input contains empty text"):
        service.embed_texts(["", "有效文本"])
