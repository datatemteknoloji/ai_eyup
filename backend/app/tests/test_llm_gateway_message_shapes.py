"""
İki sağlayıcı, iki zıt sözleşme:
  * OpenAI/LiteLLM → tool_calls.function.arguments STRING, tool_call_id ZORUNLU
  * native Ollama  → arguments OBJE, tool_call_id yok

Aynı transcript her ikisine de gönderildiği için dönüşüm tek noktada yapılır.
Ollama'ya string argüman gidince HTTP 400 ("Value looks like object, but can't
find closing '}' symbol") dönüyor ve araç çağıran her sohbet ilk turdan sonra
kopuyordu.
"""
from app.services.llm_gateway import (
    _normalize_messages_ollama, _normalize_messages_openai,
)

TRANSCRIPT = [
    {"role": "system", "content": "sistem"},
    {"role": "user", "content": "vCenter sağlıklı mı?"},
    {
        "role": "assistant",
        "content": "",
        "tool_calls": [{
            "id": "call_1",
            "type": "function",
            "function": {"name": "virt_health_overview",
                         "arguments": '{"limit": 20, "include_logs": true}'},
        }],
    },
    {"role": "tool", "tool_call_id": "call_1", "name": "virt_health_overview",
     "content": '{"ok": true}'},
]


def test_ollama_shape_uses_object_arguments_and_drops_ids():
    out = _normalize_messages_ollama(TRANSCRIPT)
    fn = out[2]["tool_calls"][0]["function"]
    assert fn["arguments"] == {"limit": 20, "include_logs": True}
    assert "id" not in out[2]["tool_calls"][0]
    assert "tool_call_id" not in out[3]


def test_openai_shape_uses_string_arguments_and_keeps_ids():
    out = _normalize_messages_openai(TRANSCRIPT)
    fn = out[2]["tool_calls"][0]["function"]
    assert isinstance(fn["arguments"], str)
    assert out[3]["tool_call_id"] == "call_1"


def test_ollama_shape_tolerates_dict_arguments_and_broken_json():
    messages = [{
        "role": "assistant",
        "tool_calls": [
            {"function": {"name": "a", "arguments": {"x": 1}}},
            {"function": {"name": "b", "arguments": '{"kırık'}},
            {"function": {"name": "c", "arguments": None}},
        ],
    }]
    calls = _normalize_messages_ollama(messages)[0]["tool_calls"]
    assert calls[0]["function"]["arguments"] == {"x": 1}
    assert calls[1]["function"]["arguments"] == {}
    assert calls[2]["function"]["arguments"] == {}


def test_normalizers_do_not_mutate_caller_transcript():
    original = TRANSCRIPT[2]["tool_calls"][0]["function"]["arguments"]
    _normalize_messages_ollama(TRANSCRIPT)
    _normalize_messages_openai(TRANSCRIPT)
    assert TRANSCRIPT[2]["tool_calls"][0]["function"]["arguments"] == original
