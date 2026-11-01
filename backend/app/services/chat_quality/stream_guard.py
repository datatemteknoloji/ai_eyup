"""Geri tutma tamponlu akış doğrulayıcı (ENGELLE).

Token'lar ~1 cümlelik pencerede bekletilir; cümle tamamlanınca kontrol edilir ve gönderilir:
  - "yapıldı" iddiası (güçlü iddia her zaman; zayıf iddia yalnız kullanıcı eylem istediyse),
    eylem aracı çağrılmamışken → akış kesilir, cevap şablonla değiştirilir,
  - sistem prompt'u sızıntısı → akış kesilir, şablon,
  - kod bloğu içindeki iddialar yok sayılır (komut çıktısı/log olabilir); sızıntı kontrolü her yerde.
Akış sonunda: değişiklik yapan komut öneren cevaplara risk uyarısı eklenir (zorunlu).

Gecikme ölçümü: her serbest bırakmada en eski bekleyen karakterin tutulma süresi (ms).
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from app.services.chat_quality import claims

# Cümle sonu: nokta/ünlem/soru + (kapanış karakteri) + boşluk, ya da satır sonu
_BOUNDARY = re.compile(r"(?:[.!?…][\"')\]*_]*(?=\s)|\n)")

MAX_HOLD_CHARS = 240   # sınır yoksa bu kadar karakterden fazla bekletme
TAIL_KEEP = 48         # zorla bırakmada son yarım cümleden saklanan karakter
MAX_HOLD_S = 1.5       # bekleyen metin bu süreyi aşarsa (bir sonraki token'da) bırak

CLAIM_TEMPLATE = (
    "\n\n---\n**Cevap engellendi:** Bu sohbet **salt-okunur** çalışır; hiçbir komut çalıştırmaz ve ortamda "
    "değişiklik yapmaz. Üretilen cevap bir işlemin yapıldığını söylüyordu, ancak böyle bir işlem "
    "gerçekleşmedi, bu yüzden gösterilmedi. Durumu salt-okunur olarak sorgulayabilirim; değişiklik için "
    "insan onaylı Agent akışını kullanın."
)
CLAIM_DB_TEXT = CLAIM_TEMPLATE.lstrip("\n-").strip()
LEAK_TEMPLATE = (
    "\n\n---\n**Cevap engellendi:** Sistem talimatlarımı veya iç yapılandırmamı paylaşamam. Ortamınızla "
    "ilgili (VM, host, cluster, node, pod, sunucu) sorular sorabilirsiniz."
)
LEAK_DB_TEXT = LEAK_TEMPLATE.lstrip("\n-").strip()


@dataclass
class Violation:
    kind: str            # "claim" | "leak"
    sentence: str
    level: str = ""      # claim: strong|weak
    template: str = ""   # akışa eklenen metin
    db_text: str = ""    # DB'ye yazılacak metin


@dataclass
class GuardStats:
    releases: int = 0
    delays_ms: List[float] = field(default_factory=list)
    chars_held_max: int = 0
    blocked: Optional[str] = None
    risk_cmds: int = 0
    ttft_added_ms: Optional[float] = None   # ilk token girişi ile ilk serbest bırakma arası

    def summary(self) -> dict:
        d = sorted(self.delays_ms)

        def pct(p: float) -> float:
            return round(d[min(len(d) - 1, int(len(d) * p))], 1) if d else 0.0

        return {
            "releases": self.releases,
            "hold_ms_p50": pct(0.50), "hold_ms_p95": pct(0.95),
            "hold_ms_max": round(d[-1], 1) if d else 0.0,
            "hold_ms_mean": round(sum(d) / len(d), 1) if d else 0.0,
            "chars_held_max": self.chars_held_max,
            "blocked": self.blocked, "risk_cmds": self.risk_cmds,
            "ttft_added_ms": self.ttft_added_ms,
        }


class StreamGuard:
    def __init__(
        self,
        *,
        user_action_intent: bool = False,
        has_mutating_tool: Callable[[], bool] = lambda: False,
        shingles: Optional[set] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.user_action_intent = user_action_intent
        self._mut_tool = has_mutating_tool
        self._shingles = shingles
        self._clock = clock
        self._buf = ""
        self._stamps: List[tuple] = []   # (buffer içindeki bitiş indeksi, zaman)
        self._sent: List[str] = []
        self._fence = False
        self.violation: Optional[Violation] = None
        self.stats = GuardStats()
        self._t_first_feed: Optional[float] = None

    # ── genel API ──────────────────────────────────────────────────────────
    @property
    def sent_text(self) -> str:
        return "".join(self._sent)

    def feed(self, token: str) -> str:
        """Token ekler; güvenle gönderilebilecek metni döner ('' = beklet)."""
        if self.violation or not token:
            return ""
        self._buf += token
        if self._t_first_feed is None:
            self._t_first_feed = self._clock()
        self._stamps.append((len(self._buf), self._clock()))
        self.stats.chars_held_max = max(self.stats.chars_held_max, len(self._buf))
        cut = self._cut_index()
        return self._release(cut) if cut > 0 else ""

    def flush(self) -> str:
        """Sıra korumak için (başka olay yayınlanmadan önce) kalan tamponu denetleyip bırakır."""
        if self.violation or not self._buf:
            return ""
        return self._release(len(self._buf))

    def finish(self) -> str:
        """Akış sonu: kalan tampon + (varsa) risk uyarısı. İhlal varsa ''."""
        out = self.flush()
        if self.violation:
            return ""
        full = self.sent_text
        cmds = claims.extract_mutating_commands(full)
        self.stats.risk_cmds = len(cmds)
        if cmds and claims.RISK_MARKER not in full:
            block = claims.risk_warning_block(cmds)
            self._sent.append(block)
            out += block
        return out

    # ── iç ─────────────────────────────────────────────────────────────────
    def _cut_index(self) -> int:
        buf = self._buf
        last = -1
        for m in _BOUNDARY.finditer(buf):
            last = m.end()
        if last > 0:
            return last
        age = self._clock() - self._stamps[0][1] if self._stamps else 0.0
        if len(buf) > MAX_HOLD_CHARS or age > MAX_HOLD_S:
            cut = max(0, len(buf) - TAIL_KEEP)
            sp = buf.rfind(" ", 0, cut + 1)
            return sp + 1 if sp > 0 else cut
        return 0

    def _release(self, cut: int) -> str:
        cand, rest = self._buf[:cut], self._buf[cut:]
        if not cand:
            return ""
        v = self._inspect(cand)
        now = self._clock()
        if v is not None:
            self.violation = v
            self.stats.blocked = v.kind
            self._buf = ""
            self._stamps = []
            return ""
        # gecikme: aday içindeki ilk token'ın tutulma süresi
        t0 = self._stamps[0][1] if self._stamps else now
        self.stats.delays_ms.append(max(0.0, (now - t0) * 1000.0))
        self.stats.releases += 1
        if self.stats.ttft_added_ms is None and self._t_first_feed is not None:
            self.stats.ttft_added_ms = round(max(0.0, (now - self._t_first_feed) * 1000.0), 1)
        self._stamps = [(i - cut, t) for (i, t) in self._stamps if i > cut]
        self._buf = rest
        self._sent.append(cand)
        return cand

    def _inspect(self, text: str) -> Optional[Violation]:
        # sızıntı: her yerde (kod bloğu içinde de)
        leak = claims.find_leak(text, self._shingles)
        if leak:
            return Violation("leak", leak, template=LEAK_TEMPLATE, db_text=LEAK_DB_TEXT)
        if self._mut_tool():
            return None
        # iddia: kod bloğu dışı cümleler
        parts = text.split("```")
        fence = self._fence
        for i, seg in enumerate(parts):
            if i > 0:
                fence = not fence
            if fence:
                continue
            for sent in re.split(r"(?<=[.!?…])\s+|\n+", seg):
                if not sent.strip():
                    continue
                lvl = claims.claim_level(sent, user_action_intent=self.user_action_intent)
                if lvl:
                    return Violation("claim", sent.strip()[:200], level=lvl,
                                     template=CLAIM_TEMPLATE, db_text=CLAIM_DB_TEXT)
        # fence durumunu kalıcı güncelle (``` sayısının paritesi)
        if (len(parts) - 1) % 2 == 1:
            self._fence = not self._fence
        return None
