"""RAG getirim ölçümü (Adım 8R): R2 modül sızıntısı / doğru belge ilk-5 / gecikme ve R3 alaka eşiği dağılımı.

Konteyner içinde çalışır (backend modüllerini kullanır):
  docker cp scripts/chat_bench/rag_eval.py server_management_backend:/tmp/rag_eval.py
  docker exec -w /app -e PYTHONPATH=/app server_management_backend python /tmp/rag_eval.py r2|r3|all [--json out.json]

Salt-okunur: yalnız arama yapar (embed çağrısı = sorgu başına bir vektör). Veri yazmaz.
"""
from __future__ import annotations

import asyncio
import json
import statistics as st
import sys
import time
from typing import Any, Dict, List, Optional, Sequence

# (id, kapsam(platform), soru, beklenen başlık önekleri) — beklenen boş = bu modülde belge yok; yalnız sızıntı denetlenir
R2: List[Dict[str, Any]] = [
    # openshift
    {"id": "r01", "scope": "openshift", "q": "OpenShift cluster nasıl güncellenir, update channel nedir?", "exp": ["OCP-4.18-Updating"]},
    {"id": "r02", "scope": "openshift", "q": "Operator Lifecycle Manager ile operatör kurulumu nasıl yapılır?", "exp": ["OCP-4.18-Operators"]},
    {"id": "r03", "scope": "openshift", "q": "Node NotReady olursa ne kontrol edilir?", "exp": ["OCP-node-notready", "OCP-4.18"]},
    {"id": "r04", "scope": "openshift", "q": "Pod CrashLoopBackOff veya Pending ise nasıl teşhis edilir?", "exp": ["OCP-pending-crashloop"]},
    {"id": "r05", "scope": "openshift", "q": "Huawei CSI sürücüsü ile PV nasıl oluşturulur?", "exp": ["Huawei-eSDK-CSI"]},
    {"id": "r06", "scope": "openshift", "q": "Persistent volume ve storage class yapılandırması nasıl yapılır?", "exp": ["OCP-4.18-Storage", "Huawei-eSDK-CSI"]},
    # linux
    {"id": "r07", "scope": "linux", "q": "Pacemaker cluster kaynak (resource) nasıl eklenir?", "exp": ["RHEL9-HA"]},
    {"id": "r08", "scope": "linux", "q": "Disk dolu olduğunda hangi dizinler temizlenir?", "exp": ["LINUX-disk-dolu"]},
    {"id": "r09", "scope": "linux", "q": "systemd servisi failed durumda, nasıl bakılır?", "exp": ["LINUX-failed-systemd"]},
    {"id": "r10", "scope": "linux", "q": "SSH ile sunucuya erişilemiyor, ne yapılır?", "exp": ["LINUX-ssh-erisim"]},
    {"id": "r11", "scope": "linux", "q": "Centrify zone yönetimi nasıl yapılır?", "exp": ["CENTRIFY-zone-mgmt"]},
    # virtualization
    {"id": "r12", "scope": "virtualization", "q": "vCenter HA ve DRS alarmı ne anlama gelir?", "exp": ["VIRT-ha-drs-alarm"]},
    {"id": "r13", "scope": "virtualization", "q": "VM datastore doluluğu için ne yapılmalı?", "exp": ["VIRT-vm-datastore"]},
    {"id": "r14", "scope": "virtualization", "q": "Sanallaştırma operasyon kabiliyetleri nelerdir?", "exp": ["VIRT-ops-capability"]},
    # windows (runbook'ta belge yok → yalnız sızıntı)
    {"id": "r15", "scope": "windows", "q": "Windows sunucuda RDP bağlantı sorunu nasıl çözülür?", "exp": []},
    {"id": "r16", "scope": "windows", "q": "Event Viewer'da kritik hata nasıl incelenir?", "exp": []},
    {"id": "r17", "scope": "windows", "q": "Windows servisi nasıl yeniden başlatılır?", "exp": []},
    # exadata (runbook'ta belge yok; linux belgeleri kapsamda olabilir)
    {"id": "r18", "scope": "exadata", "q": "Exadata cell disk durumu nasıl kontrol edilir?", "exp": []},
    {"id": "r19", "scope": "exadata", "q": "Exadata flash cache nedir?", "exp": []},
    {"id": "r20", "scope": "exadata", "q": "ASM disk group doluluğu nasıl izlenir?", "exp": []},
    # unified-admin tek modül (automic yok; OCP/Linux sızıntısı olmamalı)
    {"id": "r21", "scope": "windows", "q": "OpenShift Operators nasıl kurulur?", "exp": []},       # windows sohbetinde OCP belgesi GELMEZ
    {"id": "r22", "scope": "linux", "q": "OpenShift cluster güncelleme kanalı nedir?", "exp": []},   # linux sohbetinde OCP belgesi GELMEZ
    {"id": "r23", "scope": "virtualization", "q": "Pacemaker resource ekleme nasıl yapılır?", "exp": []},  # virt sohbetinde RHEL-HA GELMEZ
    {"id": "r24", "scope": "openshift", "q": "Pacemaker cluster stonith nasıl yapılandırılır?", "exp": []},  # OCP sohbetinde RHEL-HA GELMEZ
    {"id": "r25", "scope": "linux", "q": "Huawei CSI storage backend nasıl tanımlanır?", "exp": []},    # linux sohbetinde Huawei CSI GELMEZ
    # automic (runbook'ta Automic belgesi yok → OCP/Linux/Virt belgesi GELMEZ)
    {"id": "r26", "scope": "automic", "q": "Automic job nasıl restart edilir?", "exp": []},
    {"id": "r27", "scope": "automic", "q": "OpenShift node NotReady olursa ne yapılır?", "exp": []},
    {"id": "r28", "scope": "automic", "q": "RHEL pacemaker cluster kaynağı nasıl eklenir?", "exp": []},
    # general (kısıtsız kapsam; ainew kılavuzu)
    {"id": "r29", "scope": "general", "q": "ainew sohbetinde RAG nasıl çalışır?", "exp": ["AINEW-chat-rag"]},
    {"id": "r30", "scope": "general", "q": "Hangi sohbette ne sorulur, Linux Chat Windows Chat ayrımı nedir?", "exp": ["AINEW-chat-rag"]},
    {"id": "r31", "scope": "general", "q": "docs/rag_seed dosyaları açılışta nasıl chunk'lanır?", "exp": ["AINEW-chat-rag"]},
]

# R3: (soru, ilgili başlık önekleri; boş = bilgi bankasında karşılığı yok → gelen her şey alakasız), kapsam
R3: List[Dict[str, Any]] = (
    [dict(q=d["q"], rel=d["exp"], scope=d["scope"]) for d in R2 if d["exp"]]
    + [
        dict(q="OpenShift'te etcd yedeği nasıl alınır?", rel=["OCP-4.18"], scope="openshift"),
        dict(q="Cluster autoscaler nasıl yapılandırılır?", rel=["OCP-4.18-Machine-management"], scope="openshift"),
        dict(q="MachineSet nasıl ölçeklenir?", rel=["OCP-4.18-Machine-management"], scope="openshift"),
        dict(q="OAuth identity provider nasıl eklenir?", rel=["OCP-4.18-Authentication"], scope="openshift"),
        dict(q="Network policy ile pod trafiği nasıl kısıtlanır?", rel=["OCP-4.21-Advanced-networking"], scope="openshift"),
        dict(q="Cluster performans ayarı (tuning) nasıl yapılır?", rel=["OCP-4.18-Scalability"], scope="openshift"),
        dict(q="STONITH fencing nedir?", rel=["RHEL9-HA"], scope="linux"),
        dict(q="Linux sunucuda disk alanı nasıl açılır?", rel=["LINUX-disk-dolu"], scope="linux"),
        dict(q="Failed durumundaki systemd unit nasıl incelenir?", rel=["LINUX-failed-systemd"], scope="linux"),
        dict(q="ainew sohbetinde RAG nasıl çalışır?", rel=["AINEW-chat-rag"], scope=None),
        dict(q="Hangi sohbette ne sorulur?", rel=["AINEW-chat-rag"], scope=None),
    ]
    + [dict(q=q, rel=[], scope=None) for q in [
        "Bugün hava nasıl olacak?",
        "İstanbul'da en iyi kebapçı hangisi?",
        "Python'da liste nasıl sıralanır?",
        "Dünya Kupası'nı kim kazandı?",
        "Bana bir şiir yaz",
        "Kek tarifi verir misin?",
        "Bitcoin fiyatı ne kadar?",
        "Fransa'nın başkenti neresidir?",
        "Kaç saat uyumalıyım?",
        "En iyi film önerisi nedir?",
        "Muz mu elma mı daha sağlıklı?",
        "Marsta yaşam var mı?",
        "Excel'de dikey arama formülü nedir?",
        "Futbol maçı kaçta başlıyor?",
        "Doğum günü hediyesi önerir misin?",
        "Mutfak dolabı nasıl monte edilir?",
        "Lisans maliyeti ne kadar?",
        "Şirketin yıllık cirosu nedir?",
        "Müşteri sözleşmesi ne zaman bitiyor?",
        "Çalışan maaş listesi nerede?",
        "Oracle veritabanı lisans fiyatı nedir?",
        "Kuantum bilgisayar nasıl çalışır?",
        "JavaScript'te promise nedir?",
        "Vergi beyannamesi nasıl verilir?",
        "Araba lastiği ne zaman değişir?",
        "Telefonum şarj olmuyor, ne yapmalıyım?",
    ]]
)


def _ms(x: float) -> float:
    return round(x * 1000.0, 1)


def _pct(vals: Sequence[float], p: float) -> float:
    if not vals:
        return 0.0
    v = sorted(vals)
    return v[min(len(v) - 1, int(round((p / 100.0) * (len(v) - 1))))]


async def retrieve(q: str, modules: Optional[Sequence[str]], top_k: int = 5, *, emb=None) -> Dict[str, Any]:
    """Sohbetin kullandığı yolun aynısı: embed → hibrit arama → rerank(top_k). Hit'ler metadata + skor ile döner."""
    from app.services.embedding import embed_text
    from app.services.rag_service import _candidate_k, _rerank_hits, _store_model_dim
    from app.services.rag_store import COLLECTION_RUNBOOK, hybrid_search_collection
    t0 = time.perf_counter()
    if emb is None:
        res = await embed_text(q)
        emb = res.vector if (res.usable_for_vector_search and res.vector) else None
    t_emb = time.perf_counter() - t0
    model, dim = _store_model_dim()
    t1 = time.perf_counter()
    hits = hybrid_search_collection(COLLECTION_RUNBOOK, q, query_embedding=emb, embedding_model=model,
                                    embedding_dim=dim, n_results=_candidate_k(top_k), modules=modules)
    t_search = time.perf_counter() - t1
    t2 = time.perf_counter()
    hits = await _rerank_hits(q, hits, top_k)
    t_rerank = time.perf_counter() - t2
    return {"hits": hits, "emb": emb, "t_search": t_search, "t_rerank": t_rerank, "t_emb": t_emb,
            "t_total": time.perf_counter() - t0}


def _meta(h: dict, key: str) -> str:
    return str((h.get("metadata") or {}).get(key) or "")


def _scope_ok(h: dict, scope_mods: Optional[set]) -> bool:
    mod = _meta(h, "module")
    return (scope_mods is None) or (not mod) or (mod == "general") or (mod in scope_mods)


async def run_r2() -> Dict[str, Any]:
    from app.services.rag_scope import modules_for_platform
    rows = []
    lat_f, lat_u = [], []
    s_f, s_u = [], []
    for item in R2:
        mods = modules_for_platform(item["scope"])
        # sorgu vektörünü bir kez al (iki koşuda aynı)
        first = await retrieve(item["q"], mods)
        emb = first["emb"]
        filt_runs = [first["t_search"]] + [(await retrieve(item["q"], mods, emb=emb))["t_search"] for _ in range(2)]
        unf = await retrieve(item["q"], None, emb=emb)
        unf_runs = [unf["t_search"]] + [(await retrieve(item["q"], None, emb=emb))["t_search"] for _ in range(2)]
        lat_f += filt_runs
        lat_u += unf_runs
        s_f += filt_runs
        s_u += unf_runs
        leak_f = [h for h in first["hits"] if not _scope_ok(h, mods)]
        leak_u = [h for h in unf["hits"] if not _scope_ok(h, mods)]
        exp = item["exp"]
        titles = [_meta(h, "title") for h in first["hits"]]
        ok = (not exp) or any(any(t.startswith(e) for e in exp) for t in titles[:5])
        rows.append({"id": item["id"], "scope": item["scope"], "q": item["q"], "exp": exp,
                     "titles_filtered": titles, "leak_filtered": len(leak_f), "leak_unfiltered": len(leak_u),
                     "correct_in_top5": ok, "has_exp": bool(exp)})
    with_exp = [r for r in rows if r["has_exp"]]
    return {
        "questions": len(rows),
        "leak_filtered_total": sum(r["leak_filtered"] for r in rows),
        "leak_unfiltered_total": sum(r["leak_unfiltered"] for r in rows),
        "questions_with_leak_filtered": sum(1 for r in rows if r["leak_filtered"]),
        "questions_with_leak_unfiltered": sum(1 for r in rows if r["leak_unfiltered"]),
        "correct_top5": f'{sum(1 for r in with_exp if r["correct_in_top5"])}/{len(with_exp)}',
        "correct_top5_ratio": round(sum(1 for r in with_exp if r["correct_in_top5"]) / max(1, len(with_exp)), 3),
        "search_ms_p50_filtered": _ms(_pct(s_f, 50)), "search_ms_p95_filtered": _ms(_pct(s_f, 95)),
        "search_ms_p50_unfiltered": _ms(_pct(s_u, 50)), "search_ms_p95_unfiltered": _ms(_pct(s_u, 95)),
        "rows": rows,
    }


async def run_r3() -> Dict[str, Any]:
    from app.services.rag_scope import modules_for_platform
    from app.services import reranker
    from app.services import runtime_settings
    try:
        reranker._load_model(runtime_settings.get_str("rag_reranker_model"), allow_download=True)
    except Exception:
        pass
    points = []  # (score, relevant_bool, qid)
    per_q = []
    for i, item in enumerate(R3):
        mods = modules_for_platform(item["scope"]) if item["scope"] else None
        r = await retrieve(item["q"], mods)
        rel = item["rel"]
        for h in r["hits"]:
            sc = h.get("rerank_score")
            relevant = bool(rel) and any(_meta(h, "title").startswith(p) for p in rel)
            points.append({"q": i, "score": sc, "relevant": relevant})
        per_q.append({"i": i, "q": item["q"], "n_rel_labeled": len(rel), "hits": len(r["hits"]),
                      "top_score": max([h.get("rerank_score") for h in r["hits"] if h.get("rerank_score") is not None] or [None])
                      if any(h.get("rerank_score") is not None for h in r["hits"]) else None})
    scored = [p for p in points if p["score"] is not None]
    rel_s = [p["score"] for p in scored if p["relevant"]]
    irr_s = [p["score"] for p in scored if not p["relevant"]]
    sweep = []
    for thr in sorted({round(p["score"], 1) for p in scored}):
        lost = sum(1 for s in rel_s if s < thr)
        removed = sum(1 for s in irr_s if s < thr)
        sweep.append({"thr": thr, "relevant_lost_pct": round(100 * lost / max(1, len(rel_s)), 1),
                      "irrelevant_removed_pct": round(100 * removed / max(1, len(irr_s)), 1)})
    return {"questions": len(R3), "hits_scored": len(scored), "relevant_hits": len(rel_s), "irrelevant_hits": len(irr_s),
            "rel_score_p5_p50_p95": [round(_pct(rel_s, 5), 2), round(_pct(rel_s, 50), 2), round(_pct(rel_s, 95), 2)] if rel_s else None,
            "irr_score_p5_p50_p95": [round(_pct(irr_s, 5), 2), round(_pct(irr_s, 50), 2), round(_pct(irr_s, 95), 2)] if irr_s else None,
            "sweep": sweep, "per_q": per_q}


async def main(argv: List[str]) -> None:
    which = (argv[1] if len(argv) > 1 else "all").lower()
    out: Dict[str, Any] = {}
    if which in ("r2", "all"):
        out["r2"] = await run_r2()
    if which in ("r3", "all"):
        out["r3"] = await run_r3()
    if "--json" in argv:
        path = argv[argv.index("--json") + 1]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=1, default=str)
    brief = json.loads(json.dumps(out, default=str))
    if "r2" in brief:
        brief["r2"].pop("rows", None)
    if "r3" in brief:
        brief["r3"].pop("per_q", None)
        brief["r3"]["sweep"] = brief["r3"]["sweep"][::max(1, len(brief["r3"]["sweep"]) // 25)]
    print(json.dumps(brief, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    asyncio.run(main(sys.argv))
