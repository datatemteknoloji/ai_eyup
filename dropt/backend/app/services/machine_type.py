"""Effective machine type for inventory + ASM disk mode.

Physical override hosts stay physical until removed from this list
(facts refresh must not clear the override).
"""

from __future__ import annotations

from app.models.server import TargetServer

# Siz kaldırana kadar fiziksel (multipath) gibi davranır
PHYSICAL_OVERRIDE_HOSTS: tuple[str, ...] = (
    "enesapp",
    "rhelcluster01",
    "rhelcluster02",
)


def _short_hostname(hostname: str) -> str:
    return (hostname or "").strip().lower().split(".")[0]


def hostname_has_physical_override(hostname: str) -> bool:
    short = _short_hostname(hostname)
    if not short:
        return False
    return short in {h.lower() for h in PHYSICAL_OVERRIDE_HOSTS}


def effective_machine_type(server: TargetServer | None, *, hostname: str | None = None) -> str:
    """
    Returns 'physical' or 'virtual'.
    Override hosts → always physical.
    Empty/unknown inventory → virtual (çoğu envanter VM).
    """
    host = hostname if hostname is not None else (server.hostname if server else "")
    if hostname_has_physical_override(host or ""):
        return "physical"
    mt = ((server.machine_type if server else "") or "").strip().lower()
    if mt == "physical":
        return "physical"
    return "virtual"


def apply_physical_override(server: TargetServer) -> None:
    """Facts sonrası: override hostlarda machine_type=physical kilitle."""
    if hostname_has_physical_override(server.hostname or ""):
        server.machine_type = "physical"


def asm_disk_mode(server: TargetServer) -> str:
    """multipath | sd"""
    return "multipath" if effective_machine_type(server) == "physical" else "sd"
