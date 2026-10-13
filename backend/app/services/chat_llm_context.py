"""LLM'e giden araç sonuçlarının küçültülmesi (Adım 6b).

Yalnızca MODELE giden metin kısaltılır; UI bileşenleri / `structured_results` tam veriyle
üretilmeye devam eder. Kurallar:
  - özet (skaler) alanlar önce, listeler sonra (sayılabilir sorularda sayı ilk görünür)
  - aynı kayıtları tekrar eden listeler (ör. automic_active items == over_p95) tekilleştirilir
  - satır sınırı (varsayılan 20) + "toplam N kayıt, ilk K gösteriliyor" notu
  - gereksiz / boş kolonlar çıkarılır, zaman damgaları saniyeye indirilir
  - tek sonuç token sınırı + istek başına toplam sınır
"""
from __future__ import annotations

import json
import logging
import contextvars
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Modele faydası olmayan / başka alanlardan türetilebilen kolonlar
DROP_ROW_KEYS = frozenset({
    "user_idnr", "user_name_at_run", "top_run_id", "parent_run_id", "snapshot_at",
    "ert_calc", "mrt_sec", "srt_sec", "restart_ref_run_id", "activation_time_utc",
})
DROP_TOP_KEYS = frozenset({"system_id", "snapshot_at", "freshness_note", "within_p95_count"})

_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.\d+)?(\+\d{2}:\d{2}|Z)?$")
_MAX_STR = 400


def _est_tokens(text: str) -> int:
    try:
        from app.services.llm_context_budget import estimate_tokens
        return int(estimate_tokens(text))
    except Exception:
        return max(1, len(text) // 3)


def _setting_int(key: str, default: int) -> int:
    try:
        from app.services.runtime_settings import get_setting
        v = get_setting(key)
        return int(v) if v not in (None, "") else default
    except Exception:
        return default


_DURATION_KEYS = frozenset({
    "duration_sec", "run_time_sec", "ert_sec", "avg_sec", "p95_sec", "max_sec", "running_sec",
    "avg_duration_sec", "max_p95_sec", "p95_duration_sec", "min_running_sec",
})
_TZ_CV: contextvars.ContextVar = contextvars.ContextVar("llm_ctx_tz", default=None)  # ToolResultCompactor ayarlar


def fmt_duration(sec: Any) -> str:
    """Saniye → '1sa 23dk 05sn' (modelin dönüşüm hatası yapmaması için araç sonucunda hazır verilir)."""
    try:
        s = int(round(float(sec)))
    except (TypeError, ValueError):
        return ""
    if s < 0:
        return ""
    if s < 60:
        return f"{s}sn"
    if s < 3600:
        return f"{s // 60}dk {s % 60:02d}sn"
    return f"{s // 3600}sa {(s % 3600) // 60:02d}dk {s % 60:02d}sn"


def _to_local(v: str, tz: Any) -> Optional[str]:
    """ISO zaman damgasını kullanıcı saat dilimine çevirir ('YYYY-AA-GG SS:dd:ss+03:00'); çevrilemezse None."""
    try:
        from datetime import datetime, timezone
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        d = d.astimezone(tz)
        off = d.strftime("%z")
        return d.strftime("%Y-%m-%d %H:%M:%S") + (off[:3] + ":" + off[3:] if off else "")
    except Exception:
        return None


def _slim_scalar(v: Any) -> Any:
    if isinstance(v, float):
        return round(v, 1)
    if isinstance(v, str):
        m = _TS_RE.match(v)
        if m:
            _tz = _TZ_CV.get()
            if _tz is not None:
                loc = _to_local(v, _tz)
                if loc:
                    return loc
            tz = m.group(3) or ""
            return f"{m.group(1)} {m.group(2)}{tz}"
        if len(v) > _MAX_STR:
            return v[:_MAX_STR] + "…"
    return v


def _slim_row(row: Any) -> Any:
    if not isinstance(row, dict):
        return _slim_scalar(row)
    out: Dict[str, Any] = {}
    dur = row.get("duration_sec")
    for k, v in row.items():
        if k in DROP_ROW_KEYS:
            continue
        if k == "run_time_sec" and dur is not None and v == dur:   # duration_sec ile aynı: token tasarrufu
            continue
        if v is None or v == [] or v == {} or v == "":
            continue
        if isinstance(v, (dict, list)):
            out[k] = v if len(json.dumps(v, default=str)) < 300 else str(v)[:300] + "…"
        else:
            out[k] = _slim_scalar(v)
            if (k in _DURATION_KEYS or k.endswith("_sec")) and isinstance(v, (int, float)) and not isinstance(v, bool):
                txt = fmt_duration(v)
                if txt:
                    out[k[:-4] + "_text" if k.endswith("_sec") else k + "_text"] = txt
    return out


# Sayılabilir sorular için LLM'e hazır dağılım: yalnız bu kategorik anahtarlar
_COUNT_KEYS = (
    "state", "status_class", "status", "agent", "user", "queue", "platform",
    "object_type", "client", "severity",
)
_COUNT_MAX_DISTINCT = 12


def _category_counts(rows: List[Any]) -> Dict[str, Dict[str, int]]:
    """Listenin TAMAMI üzerinden kategorik dağılım (LLM kısaltılmış satırlardan sayım uydurmasın)."""
    out: Dict[str, Dict[str, int]] = {}
    dict_rows = [r for r in rows if isinstance(r, dict)]
    if not dict_rows:
        return out
    for key in _COUNT_KEYS:
        counts: Dict[str, int] = {}
        for r in dict_rows:
            v = r.get(key)
            if v is None or isinstance(v, (dict, list)):
                continue
            counts[str(v)] = counts.get(str(v), 0) + 1
        if 1 < len(counts) <= _COUNT_MAX_DISTINCT:
            out[key] = dict(sorted(counts.items(), key=lambda kv: -kv[1]))
    return out


def _row_sig(rows: List[Any]) -> str:
    try:
        return json.dumps(rows, sort_keys=True, default=str)
    except Exception:
        return str(id(rows))


def _has_nonzero_return_code(obj: Any, _depth: int = 0) -> bool:
    if _depth > 3:
        return False
    if isinstance(obj, dict):
        rc = obj.get("return_code")
        if isinstance(rc, (int, float)) and not isinstance(rc, bool) and rc != 0:
            return True
        return any(_has_nonzero_return_code(v, _depth + 1) for v in obj.values() if isinstance(v, (dict, list)))
    if isinstance(obj, list):
        return any(_has_nonzero_return_code(v, _depth + 1) for v in obj[:50])
    return False


def compact_result(result: Any, *, max_rows: int, notes: Optional[List[str]] = None) -> Any:
    """Araç sonucunu LLM için küçült (yeni nesne; orijinal değişmez)."""
    if not isinstance(result, dict):
        return result
    scalars: Dict[str, Any] = {}
    lists: Dict[str, Any] = {}
    seen: Dict[str, str] = {}
    for k, v in result.items():
        if k in DROP_TOP_KEYS or v is None:
            continue
        if isinstance(v, list):
            if not v:
                continue
            sig = _row_sig(v)
            if sig in seen:
                lists[k] = f"'{seen[sig]}' ile aynı kayıtlar ({len(v)})"
                continue
            seen[sig] = k
            total = len(v)
            shown = [_slim_row(r) for r in v[:max_rows]]
            if total > max_rows:
                note = f"toplam {total} kayıt, ilk {max_rows} gösteriliyor"
                lists[k] = {"_note": note}
                counts = _category_counts(v)
                if counts:
                    lists[k]["_dagilim_tum_kayitlar"] = counts
                lists[k]["rows"] = shown
                if notes is not None:
                    notes.append(f"{k}: {note}")
            else:
                lists[k] = shown
        elif isinstance(v, dict):
            scalars[k] = _slim_row(v)
        else:
            scalars[k] = _slim_scalar(v)
    # dönüş kodu açıklaması uydurulmasın: not verinin hemen yanında (tek sefer)
    if _has_nonzero_return_code(result):
        from app.services.automic.error_codes import RETURN_CODE_NOTE
        scalars.setdefault("return_code_note", RETURN_CODE_NOTE)
    # durum kodu ≠ neden; model kaynak meşguliyeti vb. uydurmasın
    if isinstance(result, dict) and (
            result.get("status_code_note")
            or any(isinstance(it, dict) and it.get("status_code") is not None
                   for it in (result.get("items") or []))
            or (isinstance(result.get("execution"), dict) and result["execution"].get("status_code") is not None)):
        from app.services.automic.error_codes import STATUS_CODE_NOTE
        scalars.setdefault("status_code_note", result.get("status_code_note") or STATUS_CODE_NOTE)
    # özet önce, listeler sonra
    out = dict(scalars)
    out.update(lists)
    return out


class ToolResultCompactor:
    """Bir istek boyunca durum tutan LLM-yönlü araç sonucu dönüştürücü."""

    def __init__(self, *, mask_fn: Optional[Callable[[Any], Any]] = None, tz_name: Optional[str] = None) -> None:
        self.mask_fn = mask_fn
        self.tz = None
        if tz_name:
            try:
                from zoneinfo import ZoneInfo
                self.tz = ZoneInfo(tz_name)
            except Exception:
                self.tz = None
        self.max_rows = _setting_int("llm_tool_result_max_rows", 20)
        self.max_tokens_each = _setting_int("llm_tool_result_max_tokens", 3000)
        self.max_tokens_total = _setting_int("llm_tool_results_total_max_tokens", 7000)
        self.total_tokens = 0
        self.log: List[Dict[str, Any]] = []
        self.texts: List[str] = []   # modele giden araç sonucu metinleri (sırayla) — kalite kontrolü izi

    def _dump(self, obj: Any) -> str:
        return json.dumps(obj, ensure_ascii=False, default=str, separators=(",", ":"))

    def __call__(self, name: str, result: Any) -> str:
        tok = _TZ_CV.set(self.tz)
        try:
            return self._call(name, result)
        finally:
            _TZ_CV.reset(tok)

    def _call(self, name: str, result: Any) -> str:
        raw_text = self._dump(result) if not isinstance(result, str) else result
        raw_tokens = _est_tokens(raw_text)
        obj = result
        if self.mask_fn is not None and not isinstance(result, str):
            try:
                obj = self.mask_fn(result)
            except Exception as exc:  # maskeleme hatası sessiz veri sızdırmasın
                logger.warning("LLM sonuç maskeleme hatası (%s): %s", name, exc)
                obj = {"ok": False, "error": "Araç sonucu maskelenemedi"}
        remaining = max(400, self.max_tokens_total - self.total_tokens)
        budget = min(self.max_tokens_each, remaining)
        rows = self.max_rows
        notes: List[str] = []
        text = ""
        while True:
            notes.clear()
            slim = compact_result(obj, max_rows=rows, notes=notes) if not isinstance(obj, str) else obj
            text = slim if isinstance(slim, str) else self._dump(slim)
            if _est_tokens(text) <= budget or rows <= 3:
                break
            rows = max(3, rows // 2)
        if _est_tokens(text) > budget:
            from app.services.llm_context_budget import truncate_text_to_token_budget
            text, _ = truncate_text_to_token_budget(
                text, budget, suffix="\n…(araç sonucu token sınırında kısaltıldı)")
        tok = _est_tokens(text)
        self.total_tokens += tok
        self.texts.append(text)
        self.log.append({
            "tool": name, "raw_tokens": raw_tokens, "llm_tokens": tok, "rows_cap": rows,
            "notes": list(notes),
        })
        logger.info(
            "[LLMContext] araç sonucu küçültüldü tool=%s ham~%d → llm~%d token (satır sınırı %d, toplam~%d)",
            name, raw_tokens, tok, rows, self.total_tokens,
        )
        try:
            from app.services import chat_request_metrics as crm
            crm.record_tool_llm_payload(name, raw_tokens=raw_tokens, llm_tokens=tok, rows_cap=rows)
        except Exception:
            pass
        return text
