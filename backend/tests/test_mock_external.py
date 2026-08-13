import asyncio

from app.config.settings import settings
from app.services import embedding_service, external_search_service, llm_service, multimodal_service


def test_mock_external_contracts(monkeypatch):
    monkeypatch.setattr(settings, "mock_external_apis", True)
    assert len(embedding_service.embed_texts(["矩阵"])[0]) == settings.mock_embedding_dimensions
    assert "Mock" in asyncio.run(llm_service.generate_text_async("解释矩阵"))
    intent = asyncio.run(llm_service.generate_json_async("识别期末复习助手意图。用户消息：生成思维导图"))
    assert intent["primaryIntent"] == "generate_mind_map"
    assert multimodal_service.analyze_image(b"image", content_type="image/png", filename="chart.png")["confidence"] > 0
    assert multimodal_service.transcribe_audio(b"audio", content_type="audio/mpeg", filename="lecture.mp3")["segments"]
    rows = asyncio.run(external_search_service.search_public_knowledge_async("线性代数"))
    assert rows[0]["provider"] == "mock"
