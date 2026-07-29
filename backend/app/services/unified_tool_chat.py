"""
Unified Chat — READ_ONLY agentic tool-calling katmanı.

Sabit context toplamanın (linux/windows SSH-WinRM taraması, RAG, learned facts)
YANINDA/ÖNCESİNDE çalışır: model önce kısa bir sistem promptu + READ_ONLY araç
listesiyle "bu soruyu yanıtlamak için ek bir araç çağırmam gerekir mi?" kararını
kendi verir. Araç çağırırsa (SSH tanı komutu, canlı vCenter/OpenShift sorgusu vb.)
sonuç tekrar modele beslenir; çağırmazsa (ya da sağlayıcı/model tool-calling
desteklemiyorsa) sessizce hiçbir şey üretmeden mevcut sabit-context akışına düşülür
— bu modülün ürettiği metin, `_build_prompt`'a EK bir bağlam bloğu olarak eklenir,
var olan davranışı asla bozmaz.
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
    "- vCenter/ESXi/VM soruları → vcenter_* araçları.\n"
    "- Belirsiz 'servis/durum' ifadesinde: kullanıcı OpenShift/pod demediyse Linux; "
    "pod/namespace/cluster dediysa OpenShift. İkisini aynı yanıtta karıştırma.\n\n"
    "KURAL — GENEL TEKNİK SORU vs BU ORTAMA ÖZGÜ SORU:\n"
    "- Soru GENEL bir teknik/kavramsal konuysa (ör. 'RAID5 nedir', 'TCP handshake nasıl "
    "işler', 'PostgreSQL VACUUM ne işe yarar', 'systemd unit dosyası nasıl yazılır') "
    "kendi mühendislik bilgini SERBESTÇE kullan — araç çağırmana gerek YOK.\n"
    "- Soru BU ORTAMA özgüyse (belirli bir sunucu/VM/cluster/hypervisor'ın güncel "
    "durumu, metrik, log, alarm, olay, konfigürasyon) SADECE araç sonucuna güven; "
    "araç çağırmadan veri uydurma, 'muhtemelen', 'genelde şöyledir' gibi tahminî "
    "ifade kullanma.\n\n"
    "ARAÇ KULLANIMI:\n"
    "- Kullanıcı 'şu an', 'canlı', 'güncel', 'gerçek zamanlı', 'aktif' gibi ifadelerle AÇIKÇA "
    "anlık durum istiyorsa, cevap vermeden ÖNCE mutlaka ilgili aracı çağır (ör. vcenter_live_alarms, "
    "vcenter_live_tasks, list_ocp_events) — 'toplanmamış/bilinmiyor' deyip geçme, önce dene.\n"
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
        "kullanıcıya OpenShift AIOps / Unified Chat'e yönlendir."
    ),
    "openshift": (
        "\n\nBU SOHBET KAPSAMI: YALNIZCA OpenShift Container Platform (pod, namespace, "
        "node, event, KubeVirt). Linux sunucu SSH/systemd cevabı ÜRETME; o konular "
        "için Linux AIOps sohbetini öner."
    ),
    "windows": (
        "\n\nBU SOHBET KAPSAMI: YALNIZCA Windows sunucular (WinRM). "
        "Linux SSH veya OpenShift karıştırma."
    ),
    "virt": (
        "\n\nBU SOHBET KAPSAMI: YALNIZCA sanallaştırma (vCenter/ESXi/KubeVirt VM). "
        "Linux OS yönetimi veya OCP pod envanterini karıştırma."
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
) -> Iterator[Dict[str, Any]]:
    """READ_ONLY tool-calling döngüsü — generator.

    Her adımda şu tiplerden birini yield eder:
      - {"type": "tool_call", "tool": str, "args": dict, "label": str}
      - {"type": "tool_result", "tool": str}
      - {"type": "skipped", "reason": str}           (tool desteklenmiyor/hata — ilk turda)
      - {"type": "error", "detail": str}              (araç kullanıldıktan SONRA hata)
      - {"type": "final", "used_tools": bool, "tool_text": str, "max_steps_reached": bool}

    Çağıran taraf yalnızca "final" ile dönen tool_text'i mevcut prompt'a ek bir
    bağlam bloğu olarak ekler; bu fonksiyon HİÇBİR ŞEKİLDE kullanıcıya doğrudan
    cevap üretmez/streaming yapmaz (bu iş her zaman mevcut akışta kalır).
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

    sys_content = SYSTEM_PROMPT
    plat = (platform or "").strip().lower()
    if plat in _PLATFORM_HINTS:
        sys_content += _PLATFORM_HINTS[plat]
    if server_summary:
        sys_content += "\n\nKULLANILABİLİR SUNUCULAR/KÜMELER:\n" + server_summary[:4000]
    if context_str:
        sys_content += "\n\nBAĞLAM (bu turda zaten toplanmış canlı veri — varsa önce buna bak):\n" + context_str[:_MAX_CONTEXT_CHARS]

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": sys_content},
        {"role": "user", "content": user_message},
    ]

    tool_texts: List[str] = []
    used_tools = False
    exec_ctx: Dict[str, Any] = {}

    for _step in range(max(1, max_steps)):
        llm = chat_with_tools(model, messages, specs, timeout=90)
        if llm.get("error"):
            if used_tools:
                yield {"type": "error", "detail": llm["error"]}
            else:
                yield {"type": "skipped", "reason": llm["error"]}
            return

        tool_calls = llm.get("tool_calls") or []
        if not tool_calls:
            yield {"type": "final", "used_tools": used_tools, "tool_text": "\n\n".join(tool_texts)}
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
                result_text = _tool_result_to_text(result)
                messages.append({"role": "tool", "name": name, "content": result_text})
                tool_texts.append(f"[{label}]\n{result_text[:_MAX_TOOL_TEXT_CHARS]}")
                yield {"type": "tool_result", "tool": name}

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

    yield {"type": "final", "used_tools": used_tools, "tool_text": "\n\n".join(tool_texts),
           "max_steps_reached": True}
