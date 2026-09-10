import httpx
from langchain_openai import ChatOpenAI

from app.config.settings import settings


def get_dayend_model(agent_name: str) -> ChatOpenAI:
    """Create an agent model through the project's SiliconFlow-compatible API."""
    if not settings.openai_api_key:
        raise RuntimeError("DAYEND multi-agent mode requires EXAMAI_OPENAI_API_KEY")
    default_model = settings.dayend_model or settings.llm_model
    if agent_name == "supervisor_agent":
        model = settings.dayend_orchestrator_model or default_model
    elif agent_name == "critic_agent":
        model = settings.dayend_critic_model or settings.dayend_orchestrator_model or default_model
    elif agent_name == "safety_agent":
        model = settings.dayend_safety_model or settings.dayend_orchestrator_model or default_model
    else:
        model = settings.dayend_specialist_model or default_model
    # LangChain's default OpenAI client trusts HTTP_PROXY. The existing project
    # provider does not, so pass matching clients explicitly.
    timeout = httpx.Timeout(120.0)
    return ChatOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        model=model,
        temperature=0,
        max_retries=0,
        http_client=httpx.Client(timeout=timeout, trust_env=settings.model_provider_trust_env),
        http_async_client=httpx.AsyncClient(timeout=timeout, trust_env=settings.model_provider_trust_env),
    )


def get_dayend_model_name(agent_name: str) -> str:
    """Expose the resolved SiliconFlow model for trace metadata and tests."""
    default_model = settings.dayend_model or settings.llm_model
    if agent_name == "supervisor_agent":
        return settings.dayend_orchestrator_model or default_model
    if agent_name == "critic_agent":
        return settings.dayend_critic_model or settings.dayend_orchestrator_model or default_model
    if agent_name == "safety_agent":
        return settings.dayend_safety_model or settings.dayend_orchestrator_model or default_model
    return settings.dayend_specialist_model or default_model
