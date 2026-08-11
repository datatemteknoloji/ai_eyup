"""
Unified Chat — READ_ONLY agentic tool-calling katmanı.

Dalga 2 (TTFT): varsayılan yol agentic-first XOR sabit collect — chat stream'ler
`chat_path_policy.resolve_live_path` ile karar verir. Bu modül yalnızca agentic
açıldığında çağrılır; sabit SSH/WinRM taraması aynı turda genelde çalışmaz
(derin analiz / chat_force_collect_and_agentic hariç).

Model kısa sistem promptu + READ_ONLY araç listesiyle karar verir. Araç çağırırsa
sonuç tekrar modele beslenir; çağırmazsa / destek yoksa sessizce mevcut context
akışına düşülür — üretilen metin `_build_prompt`'a EK bağlam bloğu olarak eklenir.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Iterator, List, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = (
    "Sen kıdemli bir Altyapı Mimarısın. Elindeki READ_ONLY araçlarla sunuculara "
    "SSH/WinRM ile tanı komutu çalıştırabilir, vCenter/OpenShift/KubeVirt'e canlı "
    "sorgu atabilirsin.\n\n"
    "PLATFORM AYIRIMI (KRİTİK — karıştırma):\n"
    "- Linux sunucu soruları (systemd, journalctl, SELinux, df, SSH, RHEL/Ubuntu, "
    "'failed service') → get_* / run_diagnostic gibi Linux SSH araçları. "
    "OpenShift pod/namespace araçlarını KULLANMA.\n"
    "- OpenShift/OCP/Kubernetes soruları (pod, namespace, proje, CrashLoopBackOff, "
    "Deployment, Route, node NotReady, oc/kubectl) → openshift_ask / list_ocp_pods / "
    "list_ocp_events. Linux SSH/systemd araçlarını KULLANMA.\n"
    "- vCenter/ESXi/VM soruları → ÖNCE db_list_vms / db_vm_detail / db_list_datastores / "
    "db_list_esx_hosts / db_virt_alarms (DATABASE). stale=true veya veri yoksa "
    "vcenter_ask / vcenter_live_alarms / vcenter_live_tasks.\n"
    "- OpenShift Virtualization / KubeVirt VM soruları → list_kubevirt_vms / openshift_ask "
    "(OV bir sanallaştırma ortamıdır; yalnız VMware listesine bakıp 'OV yok' deme).\n"
    "- Belirsiz 'servis/durum' ifadesinde: kullanıcı OpenShift/pod demediyse Linux; "
    "pod/namespace/cluster dediysa OpenShift. İkisini aynı yanıtta karıştırma.\n\n"
    "SANALLASTIRMA KAPSAMI:\n"
    "- VMware/vCenter hypervisor kaydı VE OpenShift Virtualization (KubeVirt VM'ler) "
    "ikisi de sanallaştırmadır. Hypervisors tablosunda yalnızca vmware olsa bile "
    "OCP kümesinde KubeVirt VM varsa OV ortamı vardır — 'sayılmaz' deme; "
    "'hypervisor satırı yok, OpenShift VM yüzeyinden yönetiliyor' de.\n\n"
    "KURAL — GENEL TEKNİK SORU vs BU ORTAMA ÖZGÜ SORU:\n"
    "- Soru GENEL bir teknik/kavramsal konuysa (ör. 'RAID5 nedir', 'TCP handshake nasıl "
    "işler', 'PostgreSQL VACUUM ne işe yarar', 'systemd unit dosyası nasıl yazılır') "
    "kendi mühendislik bilgini SERBESTÇE kullan — araç çağırmana gerek YOK.\n"
    "- Soru BU ORTAMA özgüyse (belirli bir sunucu/VM/cluster/hypervisor'ın güncel "
    "durumu, metrik, log, alarm, olay, konfigürasyon) SADECE araç sonucuna güven; "
    "araç çağırmadan veri uydurma, 'muhtemelen', 'genelde şöyledir' gibi tahminî "
    "ifade kullanma.\n\n"
    "ARAÇ KULLANIMI:\n"
    "- Bu ortamda bağlantılar tanımlıdır. Ortama özgü sorularda ASLA 'bilinmiyor', "
    "'erişimim yok', 'toplanmamış', 'senkronize edilmiyor' deme — önce ilgili READ_ONLY "
    "aracı çağırıp veriyi çek; sonuç boşsa 'canlı sorguda kayıt dönmedi' veya bağlantı "
    "hatasını yaz.\n"
    "- Kullanıcı anlık durum istiyorsa cevap vermeden ÖNCE ilgili aracı çağır "
    "(vcenter_live_alarms, vcenter_live_tasks, list_ocp_events, SSH/WinRM get_*).\n"
    "- BAĞLAM bölümünde zaten toplanmış canlı veri varsa öncelikle onu kullan; "
    "eksik/yetersiz kaldığı noktada ek bir araç çağırarak tamamla.\n"
    "- Aynı bilgiyi tekrar tekrar çağırma; birkaç adımda gerekli veriyi topla, sonra "
    "daha fazla araç çağırmadan (tool_call üretmeden) doğrudan yanıtla.\n"
    "- Bu arayüzde değişiklik yapan (mutating) HİÇBİR araç yoktur — yalnızca "
    "salt-okunur bilgi toplarsın, hiçbir aracın bir servisi/veriyi değiştirmediğinden "
    "emin olabilirsin.\n"
    "- Performans/sağlık/kök-neden sorularında (ör. 'bu sunucunun performansını "
    "değerlendir') birden çok get_* aracını art arda çağırıp (sistem özeti, disk, "
    "süreçler, failed servisler vb.) TOPLADIĞIN GERÇEK VERİYE dayanarak derinlemesine, "
    "kanıta dayalı bir analiz üret — asla 'bu veri mevcut değil' deyip geçme, önce "
    "aracı çağırarak veriyi getirmeyi dene.\n"
    "- Nihai cevabını TÜRKÇE ver; hangi sunucu/hypervisor/cluster'dan geldiğini belirt."
)

_PLATFORM_HINTS = {
    "linux": (
        "\n\nBU SOHBET KAPSAMI: YALNIZCA Linux sunucular (SSH/systemd). "
        "OpenShift pod/cluster veya vCenter cevapları ÜRETME; elinde o araçlar yoksa "
        "kullanıcıya OpenShift AIOps / Unified Chat'e yönlendir.\n"
        "infra_overview bu sohbette YALNIZCA Linux özeti döner — Windows/HV/OCP sayma; "
        "tabloda yalnızca Linux metrikleri göster."
    ),
    "openshift": (
        "\n\nBU SOHBET KAPSAMI: YALNIZCA OpenShift Container Platform (pod, namespace, "
        "node, event, KubeVirt / OpenShift Virtualization). Linux sunucu SSH/systemd "
        "cevabı ÜRETME; o konular için Linux AIOps sohbetini öner.\n"
        "KubeVirt VirtualMachine'ler bu kapsamda SANALLAŞTIRMA workload'udur; "
        "'OV sanallaştırma sayılmaz' deme.\n"
        "infra_overview yalnızca OCP cluster özeti döner."
    ),
    "windows": (
        "\n\nBU SOHBET KAPSAMI: YALNIZCA Windows sunucular (WinRM). "
        "Linux SSH veya OpenShift karıştırma.\n"
        "infra_overview yalnızca Windows özeti döner."
    ),
    "virt": (
        "\n\nBU SOHBET KAPSAMI: YALNIZCA sanallaştırma (vCenter/ESXi + OpenShift "
        "Virtualization/KubeVirt VM). Linux OS yönetimi veya OCP pod envanterini karıştırma.\n"
        "OV, VMware yanında ikinci bir sanallaştırma yoludur; hypervisor kaydı yoksa "
        "bile OCP KubeVirt VM'leri sanallaştırma sayılır.\n"
        "VMware sorularında önce db_* (DATABASE); canlı vcenter_* yalnızca stale/boş "
        "sonrası. SSH get_* yok.\n"
        "infra_overview hypervisor/VM özeti döner; OV için OpenShift/KubeVirt araçlarını kullan."
    ),
    "exadata": (
        "\n\nBU SOHBET KAPSAMI: YALNIZCA Exadata. "
        "Genel Linux filo veya Windows karıştırma.\n"
        "infra_overview yalnızca Exadata özeti döner."
    ),
}

_MAX_CONTEXT_CHARS = 12000
# Envanter tool çıktıları (örn. 300+ OCP pod TSV ~32K) için bütçe.
_MAX_TOOL_TEXT_CHARS = 48000


def _tool_result_to_text(result: Any) -> str:
    try:
        return json.dumps(result, ensure_ascii=False, default=str)[:48000]
    except Exception:
        return str(result)[:48000]


def run_read_only_tool_loop(
    db: Session,
    model: str,
    user_message: str,
    context_str: str,
    server_summary: str,
    max_steps: int = 6,
    domains: Optional[frozenset] = None,
    platform: Optional[str] = None,
    *,
    stop_after_tools: Optional[int] = None,
    planning_mode: bool = False,
    planning_depth: bool = False,
) -> Iterator[Dict[str, Any]]:
    """READ_ONLY tool-calling döngüsü — generator.

    Her adımda şu tiplerden birini yield eder:
      - {"type": "tool_call", "tool": str, "args": dict, "label": str}
      - {"type": "tool_result", "tool": str}
      - {"type": "skipped", "reason": str}           (tool desteklenmiyor/hata — ilk turda)
      - {"type": "error", "detail": str}              (araç kullanıldıktan SONRA hata)
      - {"type": "final", "used_tools": bool, "tool_text": str, "max_steps_reached": bool}

    stop_after_tools: Bu kadar başarılı tool sonrası ek LLM turu yok (erken final) —
    migrasyon/planlama TTFT için.
    planning_mode: Kapasite/migrasyon sistem ekleri + agresif erken kesme.
    planning_depth: Kullanıcı 'daha kapsamlı' istediğinde derin addendum.
    """
    try:
        from app.services.agent import tools as tool_mod
        from app.services.agent.llm import chat_with_tools
        from app.services.agent.policy import RiskLevel
    except Exception as e:
        yield {"type": "skipped", "reason": f"agent modülü yüklenemedi: {e}"}
        return

    try:
        specs = tool_mod.tool_specs_read_only(domains=domains)
    except Exception as e:
        yield {"type": "skipped", "reason": f"tool şemaları alınamadı: {e}"}
        return
    if not specs:
        yield {"type": "skipped", "reason": "kullanılabilir araç yok"}
        return

    from app.services import chat_tool_policy as tool_policy

    sys_content = SYSTEM_PROMPT
    plat = (platform or "").strip().lower()
    if plat in _PLATFORM_HINTS:
        sys_content += _PLATFORM_HINTS[plat]

    db_first = tool_policy.should_use_db_first(platform=plat, domains=domains)
    escalate_live = False
    if db_first:
        # Şemada hiç db_* yoksa politikayı uygulama
        _spec_names = {
            ((s.get("function") or {}).get("name") or "")
            for s in specs
            if isinstance(s, dict)
        }
        if not (_spec_names & set(tool_policy.DB_FIRST_TOOLS)):
            db_first = False
        else:
            sys_content += tool_policy.DB_FIRST_SYSTEM_ADDENDUM
            logger.info(
                "[UnifiedToolChat] db-first aktif platform=%s domains=%s",
                plat or "unified",
                sorted(domains) if domains else None,
            )

    if planning_mode:
        try:
            from app.services.chat_planning_intent import (
                PLANNING_SYSTEM_ADDENDUM,
                PLANNING_DEPTH_ADDENDUM,
            )
            sys_content += PLANNING_DEPTH_ADDENDUM if planning_depth else PLANNING_SYSTEM_ADDENDUM
        except Exception:
            pass
    if server_summary:
        sys_content += "\n\nKULLANILABİLİR SUNUCULAR/KÜMELER:\n" + server_summary[:4000]
    if context_str:
        sys_content += "\n\nBAĞLAM (bu turda zaten toplanmış canlı veri — varsa önce buna bak):\n" + context_str[:_MAX_CONTEXT_CHARS]

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": sys_content},
        {"role": "user", "content": user_message},
    ]

    tool_texts: List[str] = []
    tools_used: List[str] = []
    used_tools = False
    successful_tool_runs = 0
    exec_ctx: Dict[str, Any] = {"platform": plat or "unified"}
    _stop_n = int(stop_after_tools) if stop_after_tools and stop_after_tools > 0 else None

    def _active_specs(step: int) -> List[Dict[str, Any]]:
        """DB-first: ilk adımlarda canlı vCenter şemasını gizle."""
        if not db_first or escalate_live:
            return specs
        if step >= tool_policy.DB_FIRST_MAX_STEPS:
            return specs
        filtered = [
            s for s in specs
            if isinstance(s, dict)
            and ((s.get("function") or {}).get("name") or "")
            not in tool_policy.LIVE_VCENTER_TOOLS
        ]
        return filtered or specs

    def _unlock_live(reason: str) -> None:
        nonlocal escalate_live
        if escalate_live or not db_first:
            return
        escalate_live = True
        logger.info("[UnifiedToolChat] db-first → canlı araçlar açıldı: %s", reason)
        messages.append({
            "role": "system",
            "content": (
                "Canlı vCenter araçları artık AÇIK (vcenter_ask, vcenter_live_alarms, "
                f"vcenter_live_tasks). Gerekçe: {reason}. "
                "DB yetersizse bunları kullan; yeterliyse ek çağrı yapma."
            ),
        })

    def _finalize(max_steps_reached: bool = False, early_stop: bool = False) -> Dict[str, Any]:
        if used_tools and tools_used:
            try:
                from app.services.assistant_playbooks import record_playbook
                record_playbook(
                    db,
                    platform=plat or "unified",
                    question=user_message,
                    tools=tools_used,
                    server_scope=(server_summary or "")[:80] or None,
                )
            except Exception as e:
                logger.debug("Playbook kayıt atlandı: %s", e)
        out: Dict[str, Any] = {
            "type": "final",
            "used_tools": used_tools,
            "tool_text": "\n\n".join(tool_texts),
            "tools_used": list(tools_used),
            "db_first": db_first,
            "live_escalated": escalate_live if db_first else False,
        }
        if max_steps_reached:
            out["max_steps_reached"] = True
        if early_stop:
            out["early_stop"] = True
        return out

    for _step in range(max(1, max_steps)):
        if db_first and not escalate_live and _step >= tool_policy.DB_FIRST_MAX_STEPS:
            _unlock_live(f"faz adımı doldu ({tool_policy.DB_FIRST_MAX_STEPS})")

        step_specs = _active_specs(_step)
        llm = chat_with_tools(model, messages, step_specs, timeout=90)
        if llm.get("error"):
            if used_tools:
                yield {"type": "error", "detail": llm["error"]}
            else:
                yield {"type": "skipped", "reason": llm["error"]}
            return

        tool_calls = llm.get("tool_calls") or []
        if not tool_calls:
            yield _finalize()
            return

        messages.append({
            "role": "assistant",
            "content": llm.get("content") or "",
            "tool_calls": [
                {"function": {"name": tc["name"], "arguments": tc["arguments"]}} for tc in tool_calls
            ],
        })

        for tc in tool_calls:
            name = tc.get("name") or ""
            args = tc.get("arguments") or {}

            if name == "ask_user":
                messages.append({"role": "tool", "name": name, "content": json.dumps({
                    "error": "ask_user bu sohbette desteklenmiyor (insan onay akışı yok); "
                             "mevcut bilgiyle veya diğer READ_ONLY araçlarla devam et"
                }, ensure_ascii=False)})
                continue

            # DB-first: canlı vCenter çağrısını faz-1'de reddet (şema sızıntısına karşı)
            if db_first and not escalate_live:
                block_msg = tool_policy.tool_blocked_in_db_first_phase(name)
                if block_msg and name in tool_policy.LIVE_VCENTER_TOOLS:
                    messages.append({"role": "tool", "name": name, "content": json.dumps({
                        "error": block_msg,
                        "ok": False,
                    }, ensure_ascii=False)})
                    continue

            try:
                if name.startswith("win_"):
                    if domains is not None and "windows" not in domains:
                        messages.append({"role": "tool", "name": name, "content": json.dumps({
                            "error": "Windows araçları bu sohbet kapsamında değil"
                        }, ensure_ascii=False)})
                        continue
                    from app.services.agent.tools_windows import execute_windows_tool, MUTATING_WIN_TOOLS
                    if name in MUTATING_WIN_TOOLS:
                        messages.append({"role": "tool", "name": name, "content": json.dumps({
                            "error": "Bu araç değişiklik yaptığı (mutating) için bu sohbette çalıştırılamaz"
                        }, ensure_ascii=False)})
                        continue
                    yield {"type": "tool_call", "tool": name, "args": args, "label": name}
                    result_str = execute_windows_tool(name, args, db, exec_ctx)
                    used_tools = True
                    successful_tool_runs += 1
                    if name and name not in tools_used:
                        tools_used.append(name)
                    messages.append({"role": "tool", "name": name, "content": (result_str or "")[:6000]})
                    tool_texts.append(f"[{name}] {(result_str or '')[:_MAX_TOOL_TEXT_CHARS]}")
                    yield {"type": "tool_result", "tool": name}
                    continue

                tool = tool_mod.get_tool(name)
                if not tool or tool.risk_level != RiskLevel.READ_ONLY:
                    messages.append({"role": "tool", "name": name, "content": json.dumps({
                        "error": f"Bilinmeyen veya bu sohbette izinli olmayan araç: {name}"
                    }, ensure_ascii=False)})
                    continue
                if domains is not None and not (tool.domains & domains):
                    messages.append({"role": "tool", "name": name, "content": json.dumps({
                        "error": f"'{name}' bu sohbet platformunda kullanılamaz"
                    }, ensure_ascii=False)})
                    continue

                label = tool.preview(db, args, exec_ctx)
                yield {"type": "tool_call", "tool": name, "args": args, "label": label}
                result = tool.execute(db, args, exec_ctx)
                used_tools = True
                successful_tool_runs += 1
                if name and name not in tools_used:
                    tools_used.append(name)
                result_text = _tool_result_to_text(result)
                messages.append({"role": "tool", "name": name, "content": result_text})
                tool_texts.append(f"[{label}]\n{result_text[:_MAX_TOOL_TEXT_CHARS]}")
                yield {"type": "tool_result", "tool": name}

                if db_first and not escalate_live and tool_policy.result_needs_live_escalation(name, result):
                    _unlock_live(f"{name} sonucu yetersiz/stale/boş")

                try:
                    from app.services.fact_learning import extract_facts_from_tool_output
                    server = tool_mod.resolve_server(db, args, exec_ctx)
                    if server and isinstance(result, dict):
                        extract_facts_from_tool_output(db, server, name, result)
                except Exception:
                    pass
            except Exception as e:
                logger.warning(f"[UnifiedToolChat] '{name}' çalıştırma hatası: {e}")
                messages.append({"role": "tool", "name": name,
                                 "content": json.dumps({"error": str(e)}, ensure_ascii=False)})
                if db_first and not escalate_live and name in tool_policy.DB_FIRST_TOOLS:
                    _unlock_live(f"{name} çalıştırma hatası")

        # Migrasyon/planlama: yeterli tool sonrası ek LLM turlarını kes (TTFT)
        if _stop_n is not None and successful_tool_runs >= _stop_n:
            logger.info(
                "[UnifiedToolChat] early_stop planning tools=%s runs=%s",
                tools_used, successful_tool_runs,
            )
            yield _finalize(early_stop=True)
            return

    yield _finalize(max_steps_reached=True)
