from pathlib import Path


def test_supervisor_uses_langchain_structured_runtime_without_rule_fallback():
    source = Path("app/agents/supervisor.py").read_text(encoding="utf-8")
    runtime = Path("app/runtime/agent_factory.py").read_text(encoding="utf-8")
    assert "invoke_structured_agent" in source
    assert "with_structured_output(schema, include_raw=True)" in runtime
    assert "_fallback" not in source
