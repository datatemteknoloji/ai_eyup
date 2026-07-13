"""
AWR Parser — Oracle AWR raporunu yapılandırılmış JSON'a dönüştürür.

Desteklenen formatlar:
  - HTML (Oracle AWR varsayılan çıktı)
  - Text (awrrpt.sql text modu)

Çıktı (AWRReport dataclass):
  db_info, snapshot_info, top_wait_events, top_sql_cpu, top_sql_elapsed,
  instance_stats, buffer_cache, log_file_sync, load_profile, rac_interconnect

Tasarım:
  - LLM token bütçesi için özet versiyon üretir (~2000 token hedefi)
  - Ham HTML parse: BeautifulSoup gerektirir; yoksa regex fallback
  - Text format: regex tabanlı, dependency yok
"""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Veri modelleri ────────────────────────────────────────────────────────────

@dataclass
class WaitEvent:
    event: str
    waits: str
    time_s: float
    avg_wait_ms: float
    pct_db_time: float
    wait_class: str = ""


@dataclass
class TopSQL:
    sql_id: str
    cpu_s: float
    elapsed_s: float
    executions: int
    pct_total: float
    sql_text: str = ""


@dataclass
class LoadProfile:
    db_time_per_sec: float = 0.0
    db_cpu_per_sec: float = 0.0
    logical_reads_per_sec: float = 0.0
    physical_reads_per_sec: float = 0.0
    parses_per_sec: float = 0.0
    user_calls_per_sec: float = 0.0
    redo_size_per_sec: float = 0.0


@dataclass
class AWRReport:
    db_name: str = ""
    db_id: str = ""
    instance_name: str = ""
    host_name: str = ""
    db_version: str = ""
    snap_begin: str = ""
    snap_end: str = ""
    elapsed_minutes: float = 0.0
    db_time_minutes: float = 0.0

    load_profile: LoadProfile = field(default_factory=LoadProfile)
    buffer_cache_hit_pct: float = 0.0
    library_cache_hit_pct: float = 0.0
    redo_log_space_wait_pct: float = 0.0

    top_wait_events: List[WaitEvent] = field(default_factory=list)
    top_sql_cpu: List[TopSQL] = field(default_factory=list)
    top_sql_elapsed: List[TopSQL] = field(default_factory=list)

    rac_avg_gc_cr_ms: float = 0.0
    rac_avg_gc_current_ms: float = 0.0

    parse_errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_llm_summary(self, max_sql: int = 5, max_events: int = 10) -> str:
        """LLM token bütçesine uygun özet metin (~1500-2000 token)."""
        lines = [
            f"=== AWR RAPORU ===",
            f"DB: {self.db_name} ({self.db_id}) | Instance: {self.instance_name} | Host: {self.host_name}",
            f"Versiyon: {self.db_version}",
            f"Snapshot: {self.snap_begin} → {self.snap_end} ({self.elapsed_minutes:.1f} dk)",
            f"DB Time: {self.db_time_minutes:.1f} dk",
            "",
            "--- YÜK PROFİLİ (saniye başı) ---",
            f"DB CPU: {self.load_profile.db_cpu_per_sec:.2f}s/s | DB Time: {self.load_profile.db_time_per_sec:.2f}s/s",
            f"Logical Reads: {self.load_profile.logical_reads_per_sec:.0f}/s | Physical Reads: {self.load_profile.physical_reads_per_sec:.0f}/s",
            f"Parses: {self.load_profile.parses_per_sec:.0f}/s | User Calls: {self.load_profile.user_calls_per_sec:.0f}/s",
            "",
            "--- KESİM İSTATİSTİKLERİ ---",
            f"Buffer Cache Hit: {self.buffer_cache_hit_pct:.1f}%",
            f"Library Cache Hit: {self.library_cache_hit_pct:.1f}%",
        ]

        if self.rac_avg_gc_cr_ms > 0:
            lines += [
                "",
                "--- RAC INTERCONNECT ---",
                f"Avg GC CR Block Receive: {self.rac_avg_gc_cr_ms:.2f}ms",
                f"Avg GC Current Block Receive: {self.rac_avg_gc_current_ms:.2f}ms",
            ]

        if self.top_wait_events:
            lines += ["", f"--- TOP {min(max_events, len(self.top_wait_events))} WAIT EVENTS ---"]
            for e in self.top_wait_events[:max_events]:
                lines.append(
                    f"  {e.event}: {e.time_s:.1f}s ({e.pct_db_time:.1f}% DB time) "
                    f"avg={e.avg_wait_ms:.2f}ms [{e.wait_class}]"
                )

        if self.top_sql_cpu:
            lines += ["", f"--- TOP {min(max_sql, len(self.top_sql_cpu))} SQL (CPU) ---"]
            for s in self.top_sql_cpu[:max_sql]:
                lines.append(
                    f"  SQL_ID={s.sql_id}: CPU={s.cpu_s:.1f}s Elapsed={s.elapsed_s:.1f}s "
                    f"Exec={s.executions} ({s.pct_total:.1f}%)"
                )
                if s.sql_text:
                    lines.append(f"    {s.sql_text[:120]}")

        if self.top_sql_elapsed:
            lines += ["", f"--- TOP {min(max_sql, len(self.top_sql_elapsed))} SQL (ELAPSED) ---"]
            for s in self.top_sql_elapsed[:max_sql]:
                lines.append(
                    f"  SQL_ID={s.sql_id}: Elapsed={s.elapsed_s:.1f}s CPU={s.cpu_s:.1f}s "
                    f"Exec={s.executions} ({s.pct_total:.1f}%)"
                )
                if s.sql_text:
                    lines.append(f"    {s.sql_text[:120]}")

        if self.parse_errors:
            lines += ["", "--- PARSE UYARILARI ---"]
            for e in self.parse_errors:
                lines.append(f"  ! {e}")

        return "\n".join(lines)


# ── HTML Parser ───────────────────────────────────────────────────────────────

def _safe_float(s: str) -> float:
    try:
        return float(s.replace(",", "").strip())
    except (ValueError, AttributeError):
        return 0.0


def _parse_html(content: str) -> AWRReport:
    """BeautifulSoup varsa kullan, yoksa regex fallback."""
    try:
        from bs4 import BeautifulSoup
        return _parse_html_bs4(content)
    except ImportError:
        logger.info("[AWRParser] BeautifulSoup yok, regex fallback kullanılıyor")
        return _parse_text(content)


def _parse_html_bs4(content: str) -> AWRReport:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(content, "html.parser")
    report = AWRReport()

    # ── DB bilgisi ──
    for td in soup.find_all("td"):
        txt = td.get_text(strip=True)
        if "DB Name" in txt and td.find_next_sibling("td"):
            report.db_name = td.find_next_sibling("td").get_text(strip=True)
        elif "DB Id" in txt and td.find_next_sibling("td"):
            report.db_id = td.find_next_sibling("td").get_text(strip=True)
        elif "Instance" in txt and not report.instance_name and td.find_next_sibling("td"):
            report.instance_name = td.find_next_sibling("td").get_text(strip=True)
        elif "Host Name" in txt and td.find_next_sibling("td"):
            report.host_name = td.find_next_sibling("td").get_text(strip=True)
        elif "Release" in txt and td.find_next_sibling("td"):
            report.db_version = td.find_next_sibling("td").get_text(strip=True)

    # ── Snapshot bilgisi ──
    snap_pattern = re.compile(r"(\d{2}-\w{3}-\d{2}\s+\d{2}:\d{2}:\d{2})")
    snaps = snap_pattern.findall(content)
    if len(snaps) >= 2:
        report.snap_begin = snaps[0]
        report.snap_end = snaps[1]

    elapsed_m = re.search(r"Elapsed[:\s]+(\d+[\d.,]*)\s+\(mins\)", content)
    if elapsed_m:
        report.elapsed_minutes = _safe_float(elapsed_m.group(1))

    dbtime_m = re.search(r"DB Time[:\s]+(\d+[\d.,]*)\s+\(mins\)", content)
    if dbtime_m:
        report.db_time_minutes = _safe_float(dbtime_m.group(1))

    # ── Wait events — tablo arama ──
    for table in soup.find_all("table"):
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        if "event" in headers and "% db time" in " ".join(headers):
            _extract_wait_events_html(table, report, headers)
        elif "sql id" in " ".join(headers) and "cpu time" in " ".join(headers):
            _extract_sql_html(table, report, headers, kind="cpu")
        elif "sql id" in " ".join(headers) and "elapsed time" in " ".join(headers):
            _extract_sql_html(table, report, headers, kind="elapsed")

    # ── Buffer cache ──
    bc = re.search(r"Buffer\s+Cache\s+Hit\s+%[:\s]+([\d.]+)", content, re.IGNORECASE)
    if bc:
        report.buffer_cache_hit_pct = _safe_float(bc.group(1))
    lc = re.search(r"Library\s+Cache\s+Hit\s+%[:\s]+([\d.]+)", content, re.IGNORECASE)
    if lc:
        report.library_cache_hit_pct = _safe_float(lc.group(1))

    return report


def _extract_wait_events_html(table, report: AWRReport, headers: list):
    from bs4 import BeautifulSoup
    rows = table.find_all("tr")[1:]
    for row in rows[:15]:
        cols = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cols) < 4:
            continue
        try:
            evt = WaitEvent(
                event=cols[0],
                waits=cols[1] if len(cols) > 1 else "",
                time_s=_safe_float(cols[2]) if len(cols) > 2 else 0.0,
                avg_wait_ms=_safe_float(cols[3]) if len(cols) > 3 else 0.0,
                pct_db_time=_safe_float(cols[4]) if len(cols) > 4 else 0.0,
                wait_class=cols[5] if len(cols) > 5 else "",
            )
            report.top_wait_events.append(evt)
        except Exception:
            pass


def _extract_sql_html(table, report: AWRReport, headers: list, kind: str):
    rows = table.find_all("tr")[1:]
    for row in rows[:10]:
        cols = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cols) < 3:
            continue
        try:
            sql = TopSQL(
                sql_id=cols[0],
                cpu_s=_safe_float(cols[1]),
                elapsed_s=_safe_float(cols[2]),
                executions=int(_safe_float(cols[3])) if len(cols) > 3 else 0,
                pct_total=_safe_float(cols[4]) if len(cols) > 4 else 0.0,
                sql_text=cols[-1][:200] if len(cols) > 5 else "",
            )
            if kind == "cpu":
                report.top_sql_cpu.append(sql)
            else:
                report.top_sql_elapsed.append(sql)
        except Exception:
            pass


# ── Text Parser (fallback + txt modu) ────────────────────────────────────────

def _parse_text(content: str) -> AWRReport:
    """AWR text raporu için regex tabanlı parser."""
    report = AWRReport()

    # DB bilgisi
    m = re.search(r"DB Name\s+DB Id\s+Instance\s+.*?\n\s*(\S+)\s+(\d+)\s+(\S+)", content)
    if m:
        report.db_name = m.group(1)
        report.db_id = m.group(2)
        report.instance_name = m.group(3)

    m = re.search(r"Host Name\s*[:\s]+(\S+)", content)
    if m:
        report.host_name = m.group(1)

    m = re.search(r"Release\s*[:\s]+([\d.]+)", content)
    if m:
        report.db_version = m.group(1)

    # Snapshot zamanları
    m = re.search(r"Begin Snap.*?(\d{2}-\w{3}-\d{4}\s+\d{2}:\d{2}:\d{2})", content, re.DOTALL)
    if m:
        report.snap_begin = m.group(1)
    m = re.search(r"End Snap.*?(\d{2}-\w{3}-\d{4}\s+\d{2}:\d{2}:\d{2})", content, re.DOTALL)
    if m:
        report.snap_end = m.group(1)

    m = re.search(r"Elapsed[^:]*:\s*([\d.]+)\s+\(mins\)", content)
    if m:
        report.elapsed_minutes = _safe_float(m.group(1))

    m = re.search(r"DB Time[^:]*:\s*([\d.]+)\s+\(mins\)", content)
    if m:
        report.db_time_minutes = _safe_float(m.group(1))

    # Load Profile
    lp = report.load_profile
    def _lp(pattern: str) -> float:
        mm = re.search(pattern, content, re.IGNORECASE)
        return _safe_float(mm.group(1)) if mm else 0.0

    lp.db_time_per_sec = _lp(r"DB Time\(s\):\s*([\d.,]+)")
    lp.db_cpu_per_sec = _lp(r"DB CPU\(s\):\s*([\d.,]+)")
    lp.logical_reads_per_sec = _lp(r"Logical reads:\s*([\d.,]+)")
    lp.physical_reads_per_sec = _lp(r"Physical reads:\s*([\d.,]+)")
    lp.parses_per_sec = _lp(r"Parses \(SQL\):\s*([\d.,]+)")
    lp.user_calls_per_sec = _lp(r"User calls:\s*([\d.,]+)")
    lp.redo_size_per_sec = _lp(r"Redo size:\s*([\d.,]+)")

    # Buffer cache
    m = re.search(r"Buffer\s+Nowait\s+%:\s*([\d.]+)", content, re.IGNORECASE)
    if m:
        report.buffer_cache_hit_pct = _safe_float(m.group(1))
    else:
        m = re.search(r"Buffer\s+Cache\s+Hit\s+Ratio:\s*([\d.]+)", content, re.IGNORECASE)
        if m:
            report.buffer_cache_hit_pct = _safe_float(m.group(1))

    # Top wait events
    wait_section = re.search(
        r"Top \d+ (?:Timed )?(?:Foreground )?Events(.*?)(?:Wait Class|Foreground|Background|SQL ordered)",
        content, re.DOTALL | re.IGNORECASE
    )
    if wait_section:
        lines = wait_section.group(1).strip().split("\n")
        for line in lines[2:17]:
            # Format: Event  Waits  Time(s)  Avg wait (ms)  % DB time  Wait Class
            parts = re.split(r"\s{2,}", line.strip())
            if len(parts) >= 4:
                try:
                    evt = WaitEvent(
                        event=parts[0],
                        waits=parts[1] if len(parts) > 1 else "",
                        time_s=_safe_float(parts[2]) if len(parts) > 2 else 0.0,
                        avg_wait_ms=_safe_float(parts[3]) if len(parts) > 3 else 0.0,
                        pct_db_time=_safe_float(parts[4]) if len(parts) > 4 else 0.0,
                        wait_class=parts[5] if len(parts) > 5 else "",
                    )
                    if evt.event and evt.time_s >= 0:
                        report.top_wait_events.append(evt)
                except Exception:
                    pass

    # Top SQL CPU
    sql_cpu_section = re.search(
        r"SQL ordered by CPU Time(.*?)SQL ordered by",
        content, re.DOTALL | re.IGNORECASE
    )
    if sql_cpu_section:
        _extract_sql_text(sql_cpu_section.group(1), report, kind="cpu")

    # Top SQL Elapsed
    sql_ela_section = re.search(
        r"SQL ordered by Elapsed Time(.*?)SQL ordered by",
        content, re.DOTALL | re.IGNORECASE
    )
    if sql_ela_section:
        _extract_sql_text(sql_ela_section.group(1), report, kind="elapsed")

    # RAC
    m = re.search(r"Avg GC CR Block Receive Time.*?([\d.]+)\s*ms", content, re.IGNORECASE)
    if m:
        report.rac_avg_gc_cr_ms = _safe_float(m.group(1))
    m = re.search(r"Avg GC Current Block Receive Time.*?([\d.]+)\s*ms", content, re.IGNORECASE)
    if m:
        report.rac_avg_gc_current_ms = _safe_float(m.group(1))

    return report


def _extract_sql_text(section: str, report: AWRReport, kind: str):
    lines = section.strip().split("\n")
    for line in lines[2:12]:
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) < 3:
            continue
        # SQL ID genellikle 13 karakter alfanumerik
        sql_id_match = re.search(r"\b([0-9a-z]{13})\b", line)
        if not sql_id_match:
            continue
        try:
            vals = re.findall(r"[\d.,]+", line.replace(",", ""))
            nums = [_safe_float(v) for v in vals if v]
            sql = TopSQL(
                sql_id=sql_id_match.group(1),
                cpu_s=nums[0] if nums else 0.0,
                elapsed_s=nums[1] if len(nums) > 1 else 0.0,
                executions=int(nums[2]) if len(nums) > 2 else 0,
                pct_total=nums[3] if len(nums) > 3 else 0.0,
                sql_text=parts[-1][:200] if len(parts) > 3 else "",
            )
            if kind == "cpu":
                report.top_sql_cpu.append(sql)
            else:
                report.top_sql_elapsed.append(sql)
        except Exception:
            pass


# ── Ana fonksiyon ─────────────────────────────────────────────────────────────

def parse_awr(content: str, filename: str = "") -> AWRReport:
    """
    AWR içeriğini parse et. HTML veya text otomatik algılanır.

    Args:
        content: AWR raporu içeriği (string)
        filename: Opsiyonel dosya adı (format algılama için)

    Returns:
        AWRReport objesi
    """
    is_html = (
        content.strip().lower().startswith("<!doctype") or
        "<html" in content[:200].lower() or
        filename.lower().endswith(".html") or
        filename.lower().endswith(".htm")
    )

    try:
        if is_html:
            return _parse_html(content)
        else:
            return _parse_text(content)
    except Exception as e:
        logger.error(f"[AWRParser] Parse hatası: {e}")
        report = AWRReport()
        report.parse_errors.append(f"Parse hatası: {str(e)[:200]}")
        return report
