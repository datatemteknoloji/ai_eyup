"""Gerçek sohbet uç noktalarına istemci (SSE). Üç hedef: virt, ocp, admin."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# hedef → (yol, mesaj gövdesi üretici, oturum silme yolu)
TARGETS: Dict[str, Dict[str, Any]] = {
    "virt": {
        "path": "/hypervisors/ask/stream",
        "body": lambda msg, sid: {"question": msg, **({"session_id": sid} if sid else {})},
        "del": "/hypervisors/ask/sessions/{sid}",
    },
    "ocp": {
        "path": "/chat/stream",
        "body": lambda msg, sid: {"message": msg, "platform": "openshift", **({"session_id": sid} if sid else {})},
        "del": "/chat/sessions/{sid}",
    },
    "admin": {
        "path": "/unified-chat/stream",
        "body": lambda msg, sid: {"message": msg, **({"session_id": sid} if sid else {})},
        "del": "/unified-chat/sessions/{sid}",
    },
    # Donanım (Adım 12): aynı Unified uç nokta; ayrı küme yalnız raporlama/soru seti içindir.
    "hw": {
        "path": "/unified-chat/stream",
        "body": lambda msg, sid: {"message": msg, **({"session_id": sid} if sid else {})},
        "del": "/unified-chat/sessions/{sid}",
    },
}


# True ise istekler `debug_trace` bayrağıyla gider (admin hesabı); iz out["trace"] içine yazılır.
TRACE = False


def api_base() -> str:
    return (os.environ.get("AINEW_API") or "http://127.0.0.1:8000").rstrip("/") + "/api/v1"


def _dotenv(name: str) -> str:
    path = os.path.join(ROOT, ".env")
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.startswith(name + "="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def login() -> str:
    user = os.environ.get("AINEW_USER") or "admin"
    pw = os.environ.get("AINEW_PASS") or _dotenv("ADMIN_DEFAULT_PASSWORD")
    req = urllib.request.Request(
        api_base() + "/auth/login",
        data=json.dumps({"username": user, "password": pw}).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())["access_token"]


def ask(target: str, token: str, message: str, session_id: Optional[int] = None,
        timeout: int = 420, now_override: Optional[str] = None) -> Dict[str, Any]:
    """Tek tur sor. Dönüş: answer, session_id, plan, tools, events, error, wall_s, from_cache..."""
    spec = TARGETS[target]
    req = urllib.request.Request(
        api_base() + spec["path"],
        data=json.dumps({**spec["body"](message, session_id), **({"debug_trace": True} if TRACE else {}),
                         **({"now_override": now_override} if (now_override and TRACE) else {})}).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"}, method="POST",
    )
    out: Dict[str, Any] = {
        "answer": "", "session_id": session_id, "plan": None, "tools": [], "error": None,
        "from_cache": False, "evidence": None, "phases": [], "first_token_s": None, "needs_confirmation": False,
        "trace": None, "trace_events": 0, "max_gap_s": 0.0, "tokens_n": 0, "done_gap_s": None,
        # Adım 10: ilk token ÖNCESİ ardışık SSE olayları arası en uzun boşluk + ilerleme olayı sayısı/adımları
        "max_pre_token_gap_s": 0.0, "progress_n": 0, "progress_steps": [],
    }
    _last_ev = time.perf_counter()
    t0 = time.perf_counter()
    last_tok = None
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw in resp:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                try:
                    d = json.loads(line[5:].strip())
                except Exception:
                    continue
                _now_ev = time.perf_counter()
                if out["first_token_s"] is None:
                    out["max_pre_token_gap_s"] = max(out["max_pre_token_gap_s"], round(_now_ev - _last_ev, 2))
                _last_ev = _now_ev
                if d.get("type") == "progress":
                    out["progress_n"] += 1
                    if d.get("step") and d["step"] not in out["progress_steps"]:
                        out["progress_steps"].append(d["step"])
                if d.get("session_id"):
                    out["session_id"] = d["session_id"]
                if d.get("plan"):
                    out["plan"] = d["plan"]
                if d.get("error"):
                    out["error"] = d["error"]
                if d.get("phase") and d["phase"] not in out["phases"]:
                    out["phases"].append(d["phase"])
                if d.get("type") == "tool_call" and d.get("tool"):
                    out["tools"].append(d["tool"])
                if d.get("type") == "debug_trace":
                    out["trace"] = d.get("trace")
                    out["trace_events"] += 1
                    for t in (d.get("trace") or {}).get("tools", []):
                        if t.get("tool") and t["tool"] not in out["tools"]:
                            out["tools"].append(t["tool"])
                if d.get("done"):
                    # `done` olayı gecikmesi: son token ile done arasındaki süre (tur sonu işleri)
                    if last_tok is not None and out["done_gap_s"] is None:
                        out["done_gap_s"] = round(time.perf_counter() - last_tok, 2)
                if d.get("from_cache"):
                    out["from_cache"] = True
                if d.get("needs_confirmation"):
                    out["needs_confirmation"] = True
                if d.get("evidence"):
                    out["evidence"] = d["evidence"]
                if d.get("replace_answer"):
                    # UI (chatStreamStore.ts) bu olayda birikmiş metni atar; bench de aynısını yapmalı (Adım 8)
                    out["answer"] = ""
                if d.get("token"):
                    if out["first_token_s"] is None:
                        out["first_token_s"] = round(time.perf_counter() - t0, 2)
                    now = time.perf_counter()
                    if last_tok is not None:
                        out["max_gap_s"] = max(out["max_gap_s"], round(now - last_tok, 3))
                    last_tok = now
                    out["tokens_n"] += 1
                    out["answer"] += d["token"]
    except urllib.error.HTTPError as e:
        out["error"] = f"HTTP {e.code}"
    except Exception as e:  # zaman aşımı vb.
        out["error"] = f"{type(e).__name__}: {e}"
    out["wall_s"] = round(time.perf_counter() - t0, 2)
    return out


def delete_session(target: str, token: str, sid: int) -> bool:
    path = TARGETS[target]["del"].format(sid=sid)
    req = urllib.request.Request(api_base() + path, headers={"Authorization": f"Bearer {token}"}, method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=30):
            return True
    except Exception:
        return False
