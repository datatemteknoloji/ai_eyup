"""Groq/OpenAI/OpenRouter hedef ve chat_sync tool yolu."""
from app.core.config import settings
from app.services import llm_gateway
from app.services.llm_external import detect_provider, resolve_external_chat_target


def test_detect_provider_names():
    assert detect_provider("llama-3.3-70b-versatile") == "groq"
    assert detect_provider("groq:llama-3.1-70b-versatile") == "groq"
    assert detect_provider("gpt-4o-mini") == "openai"
    assert detect_provider("anthropic/claude-3.5-sonnet") == "anthropic"
    assert detect_provider("mistralai/mistral-large") == "openrouter"
    assert detect_provider("gpt-oss:20b") == "ollama"
    assert detect_provider("gpt-oss-120b") == "ollama"
    assert detect_provider("llama3.1:8b") == "ollama"


def test_no_target_without_keys(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")
    assert resolve_external_chat_target("llama-3.3-70b-versatile") is None
    assert resolve_external_chat_target("gpt-4o-mini") is None
    assert resolve_external_chat_target("openai/gpt-4o") is None


def test_groq_target_when_key_set(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "gsk_test")
    monkeypatch.setattr(settings, "GROQ_API_URL", "https://api.groq.com/openai/v1/chat/completions")
    t = resolve_external_chat_target("groq:llama-3.3-70b-versatile")
    assert t is not None
    assert t.provider == "groq"
    assert t.model == "llama-3.3-70b-versatile"
    assert t.headers()["Authorization"] == "Bearer gsk_test"


def test_chat_sync_posts_tools_to_groq(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "gsk_test")
    monkeypatch.setattr(settings, "GROQ_API_URL", "https://example.test/groq")
    monkeypatch.setattr(settings, "REMOTE_LLM_ENABLED", False)

    captured = {}

    class _Resp:
        status_code = 200
        text = "{}"

        def json(self):
            return {
                "choices": [{
                    "message": {
                        "content": "",
                        "tool_calls": [{
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "infra_overview",
                                "arguments": "{}",
                            },
                        }],
                    }
                }],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4},
            }

    def _post(url, headers=None, json=None, timeout=None, verify=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return _Resp()

    monkeypatch.setattr(llm_gateway.requests, "post", _post)

    resp = llm_gateway.chat_sync(
        "llama-3.3-70b-versatile",
        [{"role": "user", "content": "kaç sunucu var"}],
        tools=[{"type": "function", "function": {"name": "infra_overview", "parameters": {}}}],
    )
    assert resp.status_code == 200
    msg = resp.json()["message"]
    assert msg["tool_calls"][0]["function"]["name"] == "infra_overview"
    assert captured["url"] == "https://example.test/groq"
    assert captured["json"]["model"] == "llama-3.3-70b-versatile"
    assert captured["json"]["tools"]
    assert captured["headers"]["Authorization"] == "Bearer gsk_test"


def test_chat_sync_prefers_groq_over_remote(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "gsk_test")
    monkeypatch.setattr(settings, "GROQ_API_URL", "https://example.test/groq")
    monkeypatch.setattr(settings, "REMOTE_LLM_ENABLED", True)
    monkeypatch.setattr(settings, "REMOTE_LLM_URL", "https://example.test/remote")

    urls = []

    class _Resp:
        status_code = 200
        text = "{}"

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    def _post(url, headers=None, json=None, timeout=None, verify=None):
        urls.append(url)
        return _Resp()

    monkeypatch.setattr(llm_gateway.requests, "post", _post)
    llm_gateway.chat_sync("llama-3.3-70b-versatile", [{"role": "user", "content": "hi"}])
    assert urls == ["https://example.test/groq"]


def test_ollama_model_does_not_use_groq_key(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "gsk_test")
    monkeypatch.setattr(settings, "REMOTE_LLM_ENABLED", False)
    assert resolve_external_chat_target("gpt-oss:20b") is None
