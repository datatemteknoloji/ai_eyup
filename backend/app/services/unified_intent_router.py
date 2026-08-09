"""Unified Chat — deterministik intent router (Dalga 2).

Tek structured karar: knowledge | planning_clarify | planning_agentic | live.
Ekstra LLM round-trip yok (TTFT korunur). Keyword + planning_intent + path_policy.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import FrozenSet, Optional

logger = logging.getLogger(__name__)

_LINUX_TRIGGER = (
    "linux", "rhel", "centos", "ubuntu", "debian", "selinux", "systemctl", "journalctl",
    "kernel", "ssh", "vmstat", "iostat", "firewalld", "iptables",
)
_WINDOWS_TRIGGER = (
    "windows", "winrm", "powershell", "defender", "event log", "olay günlüğü", "wsus",
    "active directory", "iis", "kb", "domain",
)
_OPENSHIFT_TRIGGER = (
    "openshift", "ocp", "kubernetes", "k8s", "kube", "pod", "pods", "namespace",
    "crashloop", "crashloopbackoff", "imagepull", "deployment", "statefulset",
    "route", "scc", "operator", "etcd", "oc get", "kubectl", "kubevirt",
    "proje", "project", "clusterversion", "machineconfig",
)
_GENERAL_TRIGGER = (
    "cpu", "ram", "memory", "bellek", "disk", "performans", "performance", "kullanım",
    "usage", "yük", "load", "durum", "status", "genel", "özet", "rapor", "servis", "service",
    "kaynak", "tüket", "tuket", "tüketim", "tuketim",
    "log", "hata", "error", "güncelleme", "update", "yama", "patch", "güvenlik", "security",
    "os", "işletim", "sürüm", "version", "network", "ağ", "uptime",
)


@dataclass(frozen=True)
class UnifiedRoute:
    mode: str  # knowledge | live | planning_clarify | planning_agentic
    domains: FrozenSet[str]
    need_rag: bool
    need_live: bool
    complexity: str  # simple | normal | deep
    confidence: float
    reason: str
    wants_linux: bool = False
    wants_windows: bool = False
    wants_openshift: bool = False
    linux_specific: bool = False
    windows_specific: bool = False


def _platform_flags(message: str, *, skip_ctx: bool) -> tuple:
    ml = (message or "").lower()
    try:
        from app.services.linux_info_collector import has_recognized_topic
        topic = has_recognized_topic(message)
    except Exception:
        topic = False

    wants_openshift = any(k in ml for k in _OPENSHIFT_TRIGGER) and not skip_ctx
    linux_kw = any(k in ml for k in _LINUX_TRIGGER)
    # OCP odaklı soruda yalnız topic eşleşmesi Linux SSH açmasın (eski karışıklık)
    linux_specific = linux_kw or (bool(topic) and not wants_openshift)
    windows_specific = any(k in ml for k in _WINDOWS_TRIGGER)
    wants_linux = (linux_specific or any(k in ml for k in _GENERAL_TRIGGER)) and not skip_ctx
    wants_windows = (windows_specific or any(k in ml for k in _GENERAL_TRIGGER)) and not skip_ctx
    if wants_openshift and not linux_specific:
        wants_linux = False
    if wants_openshift and not windows_specific:
        wants_windows = False
    # OCP + genel kelime (durum/cpu): Linux/Windows genel tetik kapat
    if wants_openshift and not linux_kw:
        wants_linux = False
    if wants_openshift and not windows_specific:
        wants_windows = False
    return wants_linux, wants_windows, wants_openshift, linux_specific, windows_specific


def _domains_for(
    message: str,
    *,
    wants_linux: bool,
    wants_windows: bool,
    wants_openshift: bool,
    linux_specific: bool,
    windows_specific: bool,
) -> FrozenSet[str]:
    from app.services.chat_planning_intent import planning_tool_domains

    planned = planning_tool_domains(
        message,
        wants_openshift=wants_openshift,
        linux_specific=linux_specific,
        windows_specific=windows_specific,
    )
    if planned is not None:
        return planned
    dom: set = set()
    if wants_openshift:
        dom |= {"openshift", "infra"}
    if wants_linux:
        dom |= {"linux", "infra"}
    if wants_windows:
        dom |= {"windows", "infra"}
    try:
        from app.services.chat_planning_intent import message_has_vcenter_intent
        if message_has_vcenter_intent(message):
            dom |= {"vcenter", "infra"}
    except Exception:
        pass
    return frozenset(dom) if dom else frozenset({"infra"})


def _complexity(message: str, *, mode: str) -> str:
    if mode == "knowledge":
        return "simple"
    try:
        from app.services.chat_path_policy import is_deep_live_query
        from app.services.chat_planning_intent import is_depth_followup, resolve_planning_scope
        if is_deep_live_query(message) or is_depth_followup(message):
            return "deep"
        if resolve_planning_scope(message) == "mtv":
            return "deep"
    except Exception:
        pass
    if mode == "planning_agentic":
        return "normal"
    return "normal"


def route_unified(
    message: str,
    *,
    is_followup: bool = False,
    has_episode: bool = False,
    clarification_pending: bool = False,
    skip_ctx: bool = False,
) -> UnifiedRoute:
    """Unified soru için tek structured rota kararı."""
    msg = message or ""

    from app.services.chat_planning_intent import (
        planning_needs_clarification,
        is_cross_platform_planning,
        resolve_planning_scope,
        is_depth_followup,
        message_has_vcenter_intent,
    )
    from app.services.chat_path_policy import is_knowledge_only

    # 1) Planlama netleştirme
    if planning_needs_clarification(
        msg,
        is_followup=is_followup,
        has_episode=has_episode,
        clarification_pending=clarification_pending,
    ):
        return UnifiedRoute(
            mode="planning_clarify",
            domains=frozenset({"vcenter", "openshift", "infra"}),
            need_rag=False,
            need_live=False,
            complexity="simple",
            confidence=0.9,
            reason="planning_needs_clarification",
        )

    # 2) Planlama agentic (scope / depth / cross-platform)
    scope = resolve_planning_scope(msg)
    if scope or is_depth_followup(msg) or is_cross_platform_planning(msg):
        _, _, _, ls, ws = _platform_flags(msg, skip_ctx=skip_ctx)
        reason = (
            f"planning_scope:{scope}" if scope
            else ("planning_depth" if is_depth_followup(msg) else "planning_cross")
        )
        return UnifiedRoute(
            mode="planning_agentic",
            domains=frozenset({"vcenter", "openshift", "infra"}),
            need_rag=True,
            need_live=True,
            complexity=_complexity(msg, mode="planning_agentic"),
            confidence=0.85,
            reason=reason,
            wants_linux=False,
            wants_windows=False,
            wants_openshift=True,
            linux_specific=ls,
            windows_specific=ws,
        )

    # 3) Saf bilgi
    if is_knowledge_only(msg):
        return UnifiedRoute(
            mode="knowledge",
            domains=frozenset({"infra"}),
            need_rag=True,
            need_live=False,
            complexity="simple",
            confidence=0.8,
            reason="knowledge_only",
        )

    # 4) Canlı / genel
    wl, ww, wo, ls, ws = _platform_flags(msg, skip_ctx=skip_ctx)
    domains = _domains_for(
        msg,
        wants_linux=wl,
        wants_windows=ww,
        wants_openshift=wo,
        linux_specific=ls,
        windows_specific=ws,
    )
    conf = 0.7
    reason = "live"
    if wo and not ls and not ws:
        reason = "live_openshift"
        conf = 0.75
    elif message_has_vcenter_intent(msg) and not ls and not ws:
        reason = "live_vcenter"
        conf = 0.75
    elif wl or ww:
        reason = "live_os"
        conf = 0.72

    return UnifiedRoute(
        mode="live",
        domains=domains,
        need_rag=True,
        need_live=True,
        complexity=_complexity(msg, mode="live"),
        confidence=conf,
        reason=reason,
        wants_linux=wl,
        wants_windows=ww,
        wants_openshift=wo,
        linux_specific=ls,
        windows_specific=ws,
    )
