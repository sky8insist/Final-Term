import asyncio

import pytest

from pydantic import BaseModel

from app.runtime import agent_factory


class Output(BaseModel):
    value: str


class RawResponse:
    usage_metadata = {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}
    response_metadata = {}


class StructuredModel:
    async def ainvoke(self, _messages):
        return {"raw": RawResponse(), "parsed": Output(value="ok"), "parsing_error": None}


class Model:
    def with_structured_output(self, schema, include_raw=False):
        assert schema is Output
        assert include_raw is True
        return StructuredModel()


def test_structured_agent_records_provider_token_usage(monkeypatch):
    monkeypatch.setattr(agent_factory, "get_dayend_model", lambda _: Model())
    monkeypatch.setattr(agent_factory, "get_dayend_model_name", lambda _: "test-model")

    envelope, trace = asyncio.run(agent_factory.invoke_structured_agent(
        agent_name="closure_agent", schema=Output, system_prompt="system", user_prompt="user",
        run_id="run", input_refs=["user_input"],
    ))

    assert envelope.data == Output(value="ok")
    assert trace.token_usage == {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}


class SlowStructuredModel:
    async def ainvoke(self, _messages):
        await asyncio.sleep(1)


class SlowModel:
    def with_structured_output(self, _schema, include_raw=False):
        assert include_raw is True
        return SlowStructuredModel()


def test_structured_agent_applies_a_hard_timeout_and_preserves_failure_trace(monkeypatch):
    monkeypatch.setattr(agent_factory, "get_dayend_model", lambda _: SlowModel())
    monkeypatch.setattr(agent_factory, "get_dayend_model_name", lambda _: "test-model")
    monkeypatch.setattr(agent_factory.settings, "dayend_agent_timeout_seconds", 0.01)
    monkeypatch.setattr(agent_factory.settings, "dayend_max_retries", 0)

    with pytest.raises(agent_factory.AgentRunFailed, match="timeout") as error:
        asyncio.run(agent_factory.invoke_structured_agent(
            agent_name="critic_agent", schema=Output, system_prompt="system", user_prompt="user",
            run_id="run", input_refs=["user_input"],
        ))

    assert error.value.trace is not None
    assert error.value.trace.status == "failed"
    assert error.value.failure_type == "TimeoutError"
