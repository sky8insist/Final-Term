from app.runtime import model_factory


def test_dayend_model_routing_stays_on_the_configured_siliconflow_provider(monkeypatch):
    monkeypatch.setattr(model_factory.settings, "dayend_orchestrator_model", "deepseek-ai/DeepSeek-V4-Flash")
    monkeypatch.setattr(model_factory.settings, "dayend_specialist_model", "Qwen/Qwen3-8B")
    monkeypatch.setattr(model_factory.settings, "dayend_critic_model", "deepseek-ai/DeepSeek-V4-Flash")
    assert model_factory.get_dayend_model_name("supervisor_agent") == "deepseek-ai/DeepSeek-V4-Flash"
    assert model_factory.get_dayend_model_name("closure_agent") == "Qwen/Qwen3-8B"
    assert model_factory.get_dayend_model_name("critic_agent") == "deepseek-ai/DeepSeek-V4-Flash"
