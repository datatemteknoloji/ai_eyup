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
    "PLATFORM / MODÜL AYIRIMI (KRİTİK — asla karıştırma):\n"
    "- Bu sohbetin platform kapsamı sistem eklerinde yazılıdır. Yalnız o modülün "
    "araçlarıyla cevap ver; diğer modül konularında yönlendir, veri uydurma.\n"
    "- Linux sunucu soruları (systemd, journalctl, SELinux, df, SSH, RHEL/Ubuntu, "
    "'failed service') → get_* / run_diagnostic gibi Linux SSH araçları. "
    "OpenShift pod/namespace araçlarını KULLANMA.\n"
    "- OpenShift/OCP/Kubernetes soruları (pod, namespace, proje, CrashLoopBackOff, "
    "Deployment, Route, node NotReady, oc/kubectl) → openshift_ask / list_ocp_pods / "
    "list_ocp_events. Linux SSH/systemd araçlarını KULLANMA.\n"
    "- OpenShift CLUSTER SAĞLIK/OPERATÖR/SÜRÜM soruları (cluster operator, degraded, "
    "ClusterVersion, API server adresi, genel sağlık) → ocp_cluster_status.\n"
    "- OpenShift STORAGE soruları (PV, PVC, StorageClass, kota/kapasite) → "
    "ocp_storage_overview; namespace CPU/bellek/VM-pod SAYISI KOTASI → ocp_resource_quota "
    "(namespace ZORUNLU).\n"
    "- OpenShift NETWORK soruları (NetworkAttachmentDefinition, Multus, SR-IOV, bridge, "
    "ek ağ/VLAN) → ocp_network_overview.\n"
    "- KubeVirt VM DataVolume/import/clone durumu → list_datavolumes; CANLI LIVE MIGRATION "
    "(hangi node'a taşınıyor, transfer hızı/ilerleme) → list_ocp_migrations.\n"
    "- KubeVirt VM detayı → kubevirt_vm_detail: fields=[...] veya question ile "
    "YALNIZ istenen alanları iste (örn. fields=[run_strategy,firmware]). "
    "Kullanıcı sormadıysa 50 özelliği DÖKME — varsayılan kısa özet yeter. "
    "list_kubevirt_vms sadece liste özeti.\n"
    "- BİLGİ KİRLİLİĞİ YASAĞI (tüm platformlar): Kullanıcı ne sordıysa yalnız onu "
    "göster. Tool ekstra alan döndürse bile cevabında istenmeyen kolonları yazma; "
    "'tam detay / hepsini ver' demedikçe kısa tut.\n"
    "- KubeVirt VM Snapshot/Restore listesi (ready, failure_reason, volume snapshots, "
    "restore durumu) → kubevirt_snapshots.\n"
    "- vCenter/ESXi/VM soruları → ÖNCE db_list_vms / db_vm_detail / db_list_datastores / "
    "db_list_esx_hosts / db_virt_alarms / db_virt_cross_match (DATABASE). stale=true "
    "veya veri yoksa vcenter_live_alarms / vcenter_live_tasks / vcenter_perf_query.\n"
    "- SNAPSHOT sorularında (adet, boyut/büyüklük, en eski/en yeni, ağaç, GB) db_list_vms'i "
    "BEKLEME — db_list_vms'te snapshot boyutu/detayı YOKTUR (staleness gözetmeksizin her "
    "zaman eksiktir). Bu yüzden snapshot geçen HER soruda DOĞRUDAN vcenter_snapshot_summary "
    "(fleet özeti) veya vcenter_list_vm_snapshots (vm_name verilmişse — GERÇEK per-snapshot "
    "byte boyutu döner) çağır; 'veri toplanmadı' deyip geçme, önce bu aracı dene.\n"
    "- TERİM: hypervisor/vcenter alanı = vCenter kaydı adı (örn. Office) veya bağlantı "
    "IP/FQDN; host/esxi_host = ESXi compute host (örn. 192.168.1.101). Karıştırma.\n"
    "- DİNAMİK ALAN SEÇİMİ: Kullanıcı hangi özellikleri istediyse "
    "(örn. ESXi name+IP+version, VM name+host+datastore) sorudan fields listesini "
    "çıkar ve ilgili db_* aracına fields olarak geç.\n"
    "- ÇAPRAZ EŞLEŞTİRME: Farklı SoT'lar (host + VM + datastore + alarm) tek tabloda "
    "isteniyorsa db_virt_cross_match(join_on=host|datastore|entity) kullan. "
    "Tool ortak anahtarla JOIN eder — ayrı çağırıp isimleri tahminle birleştirme. "
    "Yalnız istenen kolonları yanıtta göster; missing_fields doluysa "
    "'envanterde yok / sync gerekir' de, uydurma.\n"
    "- CANLI PERF (Monitor): Disk Rate, Disk Requests, anlık CPU/mem/net → "
    "vcenter_perf_query. metrics paket/key listesi ver (disk_rate, disk_requests, "
    "cpu, overview…). Kullanıcının istemediği metrikleri çekme. "
    "list_catalog=true ile menüyü görebilirsin. Mutate yok.\n"
    "- OpenShift Virtualization / KubeVirt VM soruları → list_kubevirt_vms / openshift_ask "
    "(OV bir sanallaştırma ortamıdır; yalnız VMware listesine bakıp 'OV yok' deme) — "
    "ancak yalnız virt veya openshift kapsamında bu araçlar açıksa.\n"
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
    "- TARİF DEĞİL, SONUÇ VER: Kullanıcı 'X'i API/SOAP ile alabilir misin', 'bu veriyi "
    "sorgulayabilir misin', 'boyutu/büyüklüğü nedir' gibi bir şey sorduğunda, sana "
    "'şu şu adımlarla / şu API çağrısıyla elde edilebilir' tarzı bir REÇETE yazman "
    "YASAKTIR — elinde o veriyi getirecek bir araç varsa onu GERÇEKTEN ÇAĞIR ve "
    "sonucu göster. Sadece hiçbir araç o veriyi hiçbir şekilde sağlamıyorsa (gerçekten "
    "denedikten sonra) bunu açıkça söyle; 'şöyle yapabilirsiniz' diye anlatıp aracı "
    "çağırmadan bırakma.\n"
    "- Bu arayüzde değişiklik yapan (mutating) HİÇBİR araç yoktur — yalnızca "
    "salt-okunur bilgi toplarsın. vCenter/ESXi üzerinde power/destroy/reconfig "
    "yapamazsın; yalnız read.\n"
    "- Performans/sağlık/kök-neden sorularında (ör. 'bu sunucunun performansını "
    "değerlendir') birden çok get_* aracını art arda çağırıp (sistem özeti, disk, "
    "süreçler, failed servisler vb.) TOPLADIĞIN GERÇEK VERİYE dayanarak derinlemesine, "
    "kanıta dayalı bir analiz üret — asla 'bu veri mevcut değil' deyip geçme, önce "
    "aracı çağırarak veriyi getirmeyi dene.\n"
    "- 'Kritik event/alarm/olay var mı', 'son N saatte hata var mı' tarzı sorularda "
    "ÖNCE db_list_critical_events (veya vCenter'a özgüyse db_virt_alarms) çağır — "
    "bu aracı çağırmadan 'yok/tespit edilemedi' ya da örnek olay/tarih UYDURMA; "
    "tool count=0 dönerse gerçekten yok demektir, dönmezse tool sonucundaki gerçek "
    "kayıtları kullan.\n"
    "- BÜYÜME/TREND/TAHMİN sorularında (ör. 'workload büyümesini değerlendir', "
    "'gelecek ayki kullanım ne olur'): yalnızca GERÇEK geçmiş zaman serisi (tekrarlanan "
    "ölçüm geçmişi) elindeyse sayısal tahmin üret. Elindeki veri yalnızca ANLIK/tek "
    "noktalıysa (ör. şu anki node/pod sayısı) ASLA geçmiş tarih, günlük artış oranı "
    "veya gelecek rakamı UYDURMA — açıkça 'geçmiş zaman serisi verisi toplanmadığı "
    "için büyüme oranı hesaplanamıyor, yalnızca mevcut anlık durum gösteriliyor' de. "
    "Keyfi bir varsayım (ör. '%20 yıllık artış') kullanman gerekiyorsa bunu HER ZAMAN "
    "'VARSAYIM' olarak açıkça etiketle ve dayanağının gerçek veri olmadığını belirt.\n"
    "- ÇAPRAZ DOĞRULAMA DÜRÜSTLÜĞÜ: 'X hem SSH hem vCenter'dan doğrulandı', 'iki "
    "kaynak da aynı sonucu veriyor' gibi bir iddiada bulunacaksan, iddia ettiğin HER "
    "kaynağın aracını BU TURDA gerçekten çağırmış olmalısın. Çağırmadığın bir "
    "kaynaktan (ör. SSH) veri geldiğini veya doğrulama yapıldığını ASLA söyleme — "
    "yalnızca gerçekten çağırdığın araçların sonucuna atıfta bulun.\n"
    "- KARŞILAŞTIRMA sorularında (ör. 'X ve Y sunucularını/VM'lerini karşılaştır'): "
    "yalnızca statik DB/vCenter envanter alanlarıyla (vCPU/RAM tahsisi) YETİNME; "
    "taraflar SSH erişimi olan Linux/Windows sunucularıysa ilgili get_system_summary/ "
    "get_disk_usage gibi canlı araçları da çağırıp gerçek kullanım verisiyle zenginleştir.\n"
    "- TAKİP SORUSU (ör. 'peki ... var mı?', 'ya X?') önceki turda incelenmemiş ek "
    "sunucu/VM/varlığı da kapsıyorsa, yalnızca önceki turun dar sonucuna güvenip "
    "'diğerleri için veri yok' deme — ilgili aracı bu sefer daha geniş kapsamda "
    "(tüm ilgili sunucular/VM'ler için) yeniden çağır.\n"
    "- Nihai cevabını TÜRKÇE, akıcı ve gramatik olarak doğru şekilde ver ('HEMEN "
    "VARMAYAN' gibi anlamsız/bozuk çekimlenmiş ifadeler ÜRETME — 'yok', 'tespit "
    "edilmedi' gibi net ve doğru Türkçe kullan); hangi sunucu/hypervisor/cluster'dan "
    "geldiğini belirt."
)

_PLATFORM_HINTS = {
    "linux": (
        "\n\nBU SOHBET KAPSAMI: YALNIZCA Linux sunucular (SSH/systemd). "
        "OpenShift pod/cluster veya vCenter/ESXi/VM cevapları ÜRETME; elinde o araçlar "
        "yoksa kullanıcıya OpenShift AIOps / Sanallaştırma / Unified Chat'e yönlendir.\n"
        "infra_overview bu sohbette YALNIZCA Linux özeti döner — Windows/HV/OCP sayma; "
        "tabloda yalnızca Linux metrikleri göster."
    ),
    "openshift": (
        "\n\nBU SOHBET KAPSAMI: YALNIZCA OpenShift Container Platform (pod, namespace, "
        "node, event, KubeVirt / OpenShift Virtualization). Linux sunucu SSH/systemd "
        "veya VMware vCenter/ESXi envanteri cevabı ÜRETME; o konular için ilgili "
        "modül sohbetini öner.\n"
        "KubeVirt VirtualMachine'ler bu kapsamda SANALLAŞTIRMA workload'udur; "
        "'OV sanallaştırma sayılmaz' deme.\n"
        "Node/proje envanteri (rol, durum, kapasite, pod/deployment/route sayısı) için "
        "ÖNCE db_list_ocp_nodes / db_list_ocp_projects dene (ucuz, DB'den); "
        "stale=true, boş veya canlı pod/olay detayı gerekiyorsa openshift_ask / "
        "list_ocp_pods / list_ocp_events ile canlıya geç.\n"
        "Cluster sağlığı/operatör/sürüm/API server → ocp_cluster_status. "
        "Storage (PV/PVC/StorageClass) → ocp_storage_overview. Namespace ResourceQuota/"
        "LimitRange (CPU/bellek/obje kotası) → ocp_resource_quota (namespace ZORUNLU). "
        "Network (NetworkAttachmentDefinition/Multus/SR-IOV) → ocp_network_overview. "
        "VM detayı → kubevirt_vm_detail(fields=[...] veya question=...); kullanıcı "
        "sormadığı alanları DÖKME. Snapshot/Restore → kubevirt_snapshots. DataVolume → "
        "list_datavolumes. Live Migration → list_ocp_migrations. Hepsi READ_ONLY.\n"
        "infra_overview yalnızca OCP cluster özeti döner."
    ),
    "windows": (
        "\n\nBU SOHBET KAPSAMI: YALNIZCA Windows sunucular (WinRM). "
        "Linux SSH, OpenShift veya vCenter karıştırma.\n"
        "infra_overview yalnızca Windows özeti döner."
    ),
    "virt": (
        "\n\nBU SOHBET KAPSAMI: YALNIZCA sanallaştırma (vCenter/ESXi + OpenShift "
        "Virtualization/KubeVirt VM). Linux OS yönetimi (SSH/systemd) veya OCP "
        "pod/Deployment envanterini KARISTIRMA — o konular için Linux / OpenShift "
        "sohbetine yönlendir.\n"
        "OV, VMware yanında ikinci bir sanallaştırma yoludur; hypervisor kaydı yoksa "
        "bile OCP KubeVirt VM'leri sanallaştırma sayılır.\n"
        "VMware: önce db_*; çapraz tablo db_virt_cross_match; "
        "Monitor Disk Rate/Requests/CPU canlı → vcenter_perf_query "
        "(metrics=[disk_rate] / [disk_requests] / [cpu] — yalnız istenen). "
        "OV/KubeVirt VM'in TAM spec detayı (runStrategy, CPU pinning/NUMA/hugepages, "
        "firmware, disk/PVC/DataVolume zinciri, nodeSelector/affinity) → kubevirt_vm_detail; "
        "OV VM Snapshot/Restore → kubevirt_snapshots (list_kubevirt_vms sadece özet döner).\n"
        "Hepsi READ-ONLY (write/mutate yok). SSH get_* yok.\n"
        "infra_overview hypervisor/VM özeti döner; OV için OpenShift/KubeVirt araçlarını kullan."
    ),
    "exadata": (
        "\n\nBU SOHBET KAPSAMI: YALNIZCA Exadata. "
        "Genel Linux filo, Windows veya vCenter karıştırma.\n"
        "infra_overview yalnızca Exadata özeti döner."
    ),
}

_MAX_CONTEXT_CHARS = 12000
# Envanter tool çıktıları (örn. 300+ OCP pod TSV ~32K) için bütçe.
_MAX_TOOL_TEXT_CHARS = 48000


def _budgeted_context(text: str) -> str:
    try:
        from app.services.llm_context_budget import apply_context_char_budget
        return apply_context_char_budget(text or "")
    except Exception:
        return (text or "")[:_MAX_CONTEXT_CHARS]


import re as _re

_CONJUNCTION_RE = _re.compile(r"\bve\b|\bile\b|ayrıca|ayrica|hem de|ek olarak", _re.I)
_CROSS_DOMAIN_HINT_RE = _re.compile(
    r"\b(openshift|ocp|kubernetes|k8s)\b|cluster.?(?:ı|i|u|ün)n\b|\bpod\b|\bnode\b|"
    r"\bwindows\b|\blinux\b",
    _re.I,
)


def _has_unaddressed_cross_domain_clause(message: str, domains: Optional[frozenset]) -> bool:
    """Soru 've/ile' gibi bir bağlaçla ikinci bir alt-soru içeriyor mu ve o alt-soru

    (vCenter envanter deterministik tablosunun kapsamadığı) başka bir domain'e
    (OpenShift/Linux/Windows/node/pod) mi değiniyor? Öyleyse early_stop YAPILMAMALI —
    aksi halde soru bölünüp ikinci yarı sessizce cevapsız kalır.
    """
    m = message or ""
    if not (_CONJUNCTION_RE.search(m) and _CROSS_DOMAIN_HINT_RE.search(m)):
        return False
    # Unified'da domains=None (tam erişim) veya ilgili domain açıksa devam etmeye değer;
    # tek-platform vCenter sohbetinde zaten o araçlar yok, LLM nazikçe yönlendirir.
    return True


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
    system_addendum: Optional[str] = None,
    output_directive: Optional[str] = None,
) -> Iterator[Dict[str, Any]]:
    """READ_ONLY tool-calling döngüsü — generator.

    system_addendum: Unified module-first persona / join sözleşmesi (opsiyonel).
    output_directive: kullanıcının /table, /json, /brief komutu (chat_output_directives.
        OutputDirective değeri veya string). Hem LLM'e giden sistem talimatına hem de
        deterministik virt envanter render'ına (materialize_from_tool_results) uygulanır.
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

    from app.services.chat_output_directives import OutputDirective, directive_system_addendum

    _directive = output_directive if isinstance(output_directive, OutputDirective) else (
        OutputDirective(output_directive) if output_directive else OutputDirective.NONE
    )

    sys_content = SYSTEM_PROMPT
    plat = (platform or "").strip().lower()
    if plat in _PLATFORM_HINTS:
        sys_content += _PLATFORM_HINTS[plat]
    if system_addendum:
        sys_content += system_addendum
    sys_content += directive_system_addendum(_directive)

    # Unified + yalnız vcenter domain → virt uzmanı gibi davran
    if plat == "unified" and domains and "vcenter" in domains and "linux" not in domains and "windows" not in domains:
        sys_content += _PLATFORM_HINTS.get("virt", "")
    elif plat == "unified" and domains and "openshift" in domains and "linux" not in domains and "vcenter" not in domains:
        sys_content += _PLATFORM_HINTS.get("openshift", "")
    elif plat == "unified" and domains and "linux" in domains and "vcenter" not in domains and "openshift" not in domains:
        sys_content += _PLATFORM_HINTS.get("linux", "")

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
        sys_content += "\n\nBAĞLAM (bu turda zaten toplanmış canlı veri — varsa önce buna bak):\n" + _budgeted_context(context_str)

    # Virt envanter sınıfı (VM disk / datastore / ESX) — sözleşme + prefetch
    inv_kind = None
    inv_filters: Dict[str, str] = {}
    inv_fields: Optional[List[str]] = None
    materialize_from_tool_results = None
    prefetch_spec = None
    try:
        from app.services.virt_inventory_contract import (
            detect_virt_inventory_kind,
            detect_requested_vm_fields,
            inventory_system_addendum,
            prefetch_spec as _prefetch_spec,
            materialize_from_tool_results as _materialize,
            KIND_VM_DISK,
            KIND_VM_LIST,
        )
        prefetch_spec = _prefetch_spec
        materialize_from_tool_results = _materialize
        if domains is None or (domains and "vcenter" in domains):
            inv_kind = detect_virt_inventory_kind(user_message)
            if inv_kind:
                sys_content += inventory_system_addendum(inv_kind)
                # GENEL kural (datastore'a özel değil): mesajda geçen bilinen
                # VM/datastore/host/cluster adını gerçek DB kayıtlarıyla
                # eşleştirip filtre olarak uygula + yalnız istenen kolonları
                # göster ("bilgi kirliliği" önlemi).
                try:
                    from app.services.virt_entity_resolver import extract_entity_filters
                    inv_filters = extract_entity_filters(db, user_message)
                except Exception:
                    inv_filters = {}
                if inv_kind in (KIND_VM_DISK, KIND_VM_LIST):
                    inv_fields = detect_requested_vm_fields(user_message, filters=inv_filters)
    except Exception as e:
        logger.debug("virt inventory contract atlandı: %s", e)

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": sys_content},
        {"role": "user", "content": user_message},
    ]

    tool_texts: List[str] = []
    tools_used: List[str] = []
    structured_results: List[Dict[str, Any]] = []
    used_tools = False
    successful_tool_runs = 0
    exec_ctx: Dict[str, Any] = {
        "platform": plat or "unified",
        "user_message": user_message or "",
        "message": user_message or "",
    }
    _stop_n = int(stop_after_tools) if stop_after_tools and stop_after_tools > 0 else None
    # Aynı (tool, args) ikilisinin bu turda tekrar tekrar çağrılmasını önle —
    # gözlemlenen regresyon: canlı OCP 401 verince model aynı openshift_ask'i
    # 3-4 kez art arda çağırıp gereksiz yere 100+ sn kaybediyordu.
    _call_signatures: Dict[str, int] = {}
    _MAX_SAME_CALL = 2
    # Çok parçalı soru (P1-8): early_stop atlanıp LLM'e devam ettirildiyse, finalize
    # aşamasında deterministik tabloyu tekrar öne çıkarma — LLM'in gerçek sentezi
    # (tool_text bağlamıyla üretilecek nihai cevap) kullanılmalı, aksi halde ikinci
    # yarı (ör. OpenShift kısmı) yine sessizce kaybolur.
    _multi_part_deferred = False

    # SNAPSHOT boyutu/büyüklüğü sorusu — küçük/yerel modellerin bu tool-call'ı
    # güvenilir şekilde tetiklemediği gözlemlendi (bkz. hypervisors.py QA_RULES
    # ile aynı desen). db_list_vms'te snapshot boyutu YOKTUR — modelin karar
    # vermesini beklemeden DOĞRUDAN atomik SOAP aracını çağır (tarif değil,
    # gerçek sorgu). vcenter domain'i açık değilse atlanır.
    _snapshot_size_re = None
    try:
        import re as _re_snap
        _snapshot_size_re = _re_snap.compile(
            r"snapshot.*(boyut|büyüklük|buyukluk)|(boyut|büyüklük|buyukluk).*snapshot"
            r"|snapshot.*ne\s*kadar\s*yer|snapshot.*(kaç\s*gb|kac\s*gb)",
            _re_snap.I,
        )
    except Exception:
        pass
    if (
        _snapshot_size_re and _snapshot_size_re.search(user_message or "")
        and (domains is None or "vcenter" in domains)
    ):
        try:
            from app.services.virt_entity_resolver import extract_entity_filters
            _vm_hint = extract_entity_filters(db, user_message).get("vm_name")
        except Exception:
            _vm_hint = None
        _snap_tool_name = "vcenter_list_vm_snapshots" if _vm_hint else "vcenter_snapshot_summary"
        _snap_tool = tool_mod.get_tool(_snap_tool_name)
        if _snap_tool:
            _snap_args = {"vm_name": _vm_hint} if _vm_hint else {"limit": 200}
            yield {
                "type": "tool_call", "tool": _snap_tool_name, "args": _snap_args,
                "label": _snap_tool.direct_label or _snap_tool_name,
            }
            _snap_result = _snap_tool.execute(db, _snap_args, exec_ctx)
            used_tools = True
            successful_tool_runs += 1
            tools_used.append(_snap_tool_name)
            _snap_text = _tool_result_to_text(_snap_result)
            tool_texts.append(f"[{_snap_tool.direct_label or _snap_tool_name}]\n{_snap_text[:_MAX_TOOL_TEXT_CHARS]}")
            structured_results.append({"tool": _snap_tool_name, "args": _snap_args, "result": _snap_result})
            messages.append({
                "role": "assistant", "content": "",
                "tool_calls": [{
                    "id": f"call_prefetch_{_snap_tool_name}", "type": "function",
                    "function": {"name": _snap_tool_name, "arguments": json.dumps(_snap_args, ensure_ascii=False)},
                }],
            })
            messages.append({
                "role": "tool", "tool_call_id": f"call_prefetch_{_snap_tool_name}",
                "name": _snap_tool_name, "content": _snap_text[:12000],
            })
            yield {"type": "tool_result", "tool": _snap_tool_name}
            logger.info(
                "[UnifiedToolChat] snapshot boyutu prefetch tool=%s vm=%s ok=%s",
                _snap_tool_name, _vm_hint,
                (_snap_result or {}).get("ok") if isinstance(_snap_result, dict) else None,
            )
            # LLM'e devam ettir — gerçek veriyi (tool sonucu) BAĞLAM olarak görsün ve
            # Türkçe akıcı bir cevaba dönüştürsün (tekil VM için tablo zaten net;
            # LLM'in tekrar araç çağırmasına gerek yok, mesaj bunu zaten belirtiyor).

    # Zorunlu prefetch: model çağırmadan SoT çek → deterministik tablo
    if inv_kind and prefetch_spec:
        try:
            spec = prefetch_spec(inv_kind, filters=inv_filters, fields=inv_fields)
            if spec:
                pref_name, pref_args = spec
                pref_tool = tool_mod.get_tool(pref_name)
                if pref_tool and (
                    domains is None or (pref_tool.domains & domains)
                ):
                    yield {
                        "type": "tool_call",
                        "tool": pref_name,
                        "args": pref_args,
                        "label": pref_tool.direct_label or pref_name,
                    }
                    pref_result = pref_tool.execute(db, pref_args, exec_ctx)
                    used_tools = True
                    successful_tool_runs += 1
                    if pref_name not in tools_used:
                        tools_used.append(pref_name)
                    pref_text = _tool_result_to_text(pref_result)
                    tool_texts.append(f"[{pref_tool.direct_label or pref_name}]\n{pref_text[:_MAX_TOOL_TEXT_CHARS]}")
                    structured_results.append({"tool": pref_name, "args": pref_args, "result": pref_result})
                    messages.append({
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{
                            "id": f"call_prefetch_{pref_name}",
                            "type": "function",
                            "function": {
                                "name": pref_name,
                                "arguments": json.dumps(pref_args, ensure_ascii=False),
                            },
                        }],
                    })
                    messages.append({
                        "role": "tool",
                        "tool_call_id": f"call_prefetch_{pref_name}",
                        "name": pref_name,
                        "content": pref_text[:12000],
                    })
                    yield {"type": "tool_result", "tool": pref_name}
                    logger.info(
                        "[UnifiedToolChat] virt inventory prefetch kind=%s tool=%s ok=%s",
                        inv_kind, pref_name,
                        (pref_result or {}).get("ok") if isinstance(pref_result, dict) else None,
                    )
                    # Prefetch yeterliyse LLM tool döngüsünü atla — tabloyu SoT'tan üret.
                    # İSTİSNA: soru çok parçalıysa (ör. "...ve bu VM'lerden biri
                    # OpenShift'in parçası mı?") ve ikinci kısım başka bir domain'e
                    # değiniyorsa, early_stop YAPMA — deterministik tabloyu context'e
                    # ekleyip LLM'in ilgili aracı çağırarak sorunun TAMAMINI
                    # yanıtlamasına izin ver (aksi halde ikinci yarı sessizce atlanır).
                    if materialize_from_tool_results and isinstance(pref_result, dict) and pref_result.get("ok"):
                        det = materialize_from_tool_results(
                            inv_kind, structured_results,
                            filters=inv_filters, fields=inv_fields, directive=_directive,
                        )
                        if det and not _has_unaddressed_cross_domain_clause(user_message, domains):
                            out = {
                                "type": "final",
                                "used_tools": True,
                                "tool_text": "\n\n".join(tool_texts),
                                "tools_used": list(tools_used),
                                "db_first": db_first,
                                "live_escalated": False,
                                "deterministic_answer": det,
                                "inventory_kind": inv_kind,
                                "early_stop": True,
                                "structured_results": list(structured_results),
                            }
                            try:
                                from app.services.assistant_playbooks import record_playbook
                                record_playbook(
                                    db,
                                    platform=plat or "unified",
                                    question=user_message,
                                    tools=tools_used,
                                    server_scope=(server_summary or "")[:80] or None,
                                )
                            except Exception:
                                pass
                            yield out
                            return
                        if det:
                            _multi_part_deferred = True
                            logger.info(
                                "[UnifiedToolChat] cok parcali soru: early_stop atlandi, "
                                "LLM devam ediyor kind=%s", inv_kind,
                            )
                            tool_texts.append(f"[Deterministik envanter — {inv_kind}]\n{det}")
                            messages.append({
                                "role": "system",
                                "content": (
                                    "Yukarıdaki deterministik envanter tablosu sorunun İLK "
                                    "kısmını zaten karşılıyor — bunu tekrar sorgulama. "
                                    "Sorunun geri kalan kısmı (ör. başka bir platform/"
                                    "domain'e referans) için uygun aracı çağırıp TAM "
                                    "cevabı tamamla; hiçbir kısmı sessizce atlama."
                                ),
                            })
        except Exception as e:
            logger.warning("[UnifiedToolChat] inventory prefetch hata: %s", e)

    def _active_specs(step: int) -> List[Dict[str, Any]]:
        """DB-first: ilk adımlarda canlı vCenter şemasını gizle.

        vcenter_perf_query her zaman kalır (Monitor disk/cpu DB'de yok; READ-ONLY).
        """
        if not db_first or escalate_live:
            return specs
        if step >= tool_policy.DB_FIRST_MAX_STEPS:
            return specs
        filtered = []
        for s in specs:
            if not isinstance(s, dict):
                continue
            name = ((s.get("function") or {}).get("name") or "")
            if name in tool_policy.LIVE_VCENTER_TOOLS and name != "vcenter_perf_query":
                continue
            filtered.append(s)
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
        det = None
        if inv_kind and materialize_from_tool_results and structured_results and not _multi_part_deferred:
            try:
                det = materialize_from_tool_results(
                    inv_kind, structured_results,
                    filters=inv_filters, fields=inv_fields, directive=_directive,
                )
            except Exception:
                det = None
        out: Dict[str, Any] = {
            "type": "final",
            "used_tools": used_tools,
            "tool_text": "\n\n".join(tool_texts),
            "tools_used": list(tools_used),
            "db_first": db_first,
            "live_escalated": escalate_live if db_first else False,
            # Özel Rapor motoru (custom_report_engine) için: bu turda çağrılan her
            # tool'un tam (isim, args, ham sonuç) üçlüsü. Geriye dönük uyumlu ek alan.
            "structured_results": list(structured_results),
        }
        if det:
            out["deterministic_answer"] = det
            out["inventory_kind"] = inv_kind
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

        # OpenAI/Ollama OpenAI-compat: arguments STRING + tool_call_id zorunlu
        messages.append({
            "role": "assistant",
            "content": llm.get("content") or "",
            "tool_calls": [
                {
                    "id": tc.get("id") or f"call_{i}_{tc.get('name') or 'tool'}",
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": tc["arguments"] if isinstance(tc.get("arguments"), str)
                        else json.dumps(tc.get("arguments") or {}, ensure_ascii=False),
                    },
                }
                for i, tc in enumerate(tool_calls)
            ],
        })

        for tc in tool_calls:
            name = tc.get("name") or ""
            args = tc.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args) if args.strip() else {}
                except Exception:
                    args = {}
            tc_id = tc.get("id") or f"call_{name}"

            # Aynı (tool, args) tekrarını engelle (bkz. yukarıdaki _call_signatures notu).
            try:
                _sig = f"{name}:{json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)}"
            except Exception:
                _sig = f"{name}:{args!r}"
            _prior_calls = _call_signatures.get(_sig, 0)
            if _prior_calls >= _MAX_SAME_CALL:
                messages.append({"role": "tool", "tool_call_id": tc_id, "name": name, "content": json.dumps({
                    "ok": False,
                    "error": (
                        f"'{name}' bu argümanlarla bu turda zaten {_prior_calls} kez "
                        "çağrıldı — tekrar ÇALIŞTIRILMADI. Yukarıdaki önceki sonucu "
                        "kullan; aynı çağrıyı tekrarlama, doğrudan yanıtla."
                    ),
                }, ensure_ascii=False)})
                continue
            _call_signatures[_sig] = _prior_calls + 1

            if name == "ask_user":
                messages.append({"role": "tool", "tool_call_id": tc_id, "name": name, "content": json.dumps({
                    "error": "ask_user bu sohbette desteklenmiyor (insan onay akışı yok); "
                             "mevcut bilgiyle veya diğer READ_ONLY araçlarla devam et"
                }, ensure_ascii=False)})
                continue

            # DB-first: canlı vCenter çağrısını faz-1'de reddet (şema sızıntısına karşı)
            # vcenter_perf_query istisna (Monitor perf; READ-ONLY)
            if db_first and not escalate_live:
                block_msg = tool_policy.tool_blocked_in_db_first_phase(name, domains=domains)
                if block_msg and name in tool_policy.LIVE_VCENTER_TOOLS and name != "vcenter_perf_query":
                    messages.append({"role": "tool", "tool_call_id": tc_id, "name": name, "content": json.dumps({
                        "error": block_msg,
                        "ok": False,
                    }, ensure_ascii=False)})
                    continue

            try:
                if name.startswith("win_"):
                    if domains is not None and "windows" not in domains:
                        messages.append({"role": "tool", "tool_call_id": tc_id, "name": name, "content": json.dumps({
                            "error": "Windows araçları bu sohbet kapsamında değil"
                        }, ensure_ascii=False)})
                        continue
                    from app.services.agent.tools_windows import execute_windows_tool, MUTATING_WIN_TOOLS
                    if name in MUTATING_WIN_TOOLS:
                        messages.append({"role": "tool", "tool_call_id": tc_id, "name": name, "content": json.dumps({
                            "error": "Bu araç değişiklik yaptığı (mutating) için bu sohbette çalıştırılamaz"
                        }, ensure_ascii=False)})
                        continue
                    yield {"type": "tool_call", "tool": name, "args": args, "label": name}
                    result_str = execute_windows_tool(name, args, db, exec_ctx)
                    used_tools = True
                    successful_tool_runs += 1
                    if name and name not in tools_used:
                        tools_used.append(name)
                    messages.append({"role": "tool", "tool_call_id": tc_id, "name": name, "content": (result_str or "")[:6000]})
                    tool_texts.append(f"[{name}] {(result_str or '')[:_MAX_TOOL_TEXT_CHARS]}")
                    try:
                        _win_result = json.loads(result_str) if result_str else {}
                    except Exception:
                        _win_result = {"raw": result_str}
                    structured_results.append({"tool": name, "args": args, "result": _win_result})
                    yield {"type": "tool_result", "tool": name}
                    continue

                tool = tool_mod.get_tool(name)
                if not tool or tool.risk_level != RiskLevel.READ_ONLY:
                    messages.append({"role": "tool", "tool_call_id": tc_id, "name": name, "content": json.dumps({
                        "error": f"Bilinmeyen veya bu sohbette izinli olmayan araç: {name}"
                    }, ensure_ascii=False)})
                    continue
                if domains is not None and not (tool.domains & domains):
                    messages.append({"role": "tool", "tool_call_id": tc_id, "name": name, "content": json.dumps({
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
                messages.append({"role": "tool", "tool_call_id": tc_id, "name": name, "content": result_text})
                tool_texts.append(f"[{label}]\n{result_text[:_MAX_TOOL_TEXT_CHARS]}")
                structured_results.append({"tool": name, "args": args, "result": result})
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
                messages.append({"role": "tool", "tool_call_id": tc_id, "name": name,
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
