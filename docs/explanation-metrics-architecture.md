# Neden metrikler kaynağa göre ayrılır: VM → vCenter, Fiziksel → Prometheus

> **Diataxis:** Explanation

## Problem

ainew hem fiziksel sunucuları hem de hypervisor'lardaki VM'leri aynı envanterde
(`servers` tablosu) tutar. İlk tasarımda tüm sunucular için tek bir metrik
kaynağı vardı: Prometheus (node_exporter/windows_exporter). Bu, iki gerçek
sorun doğurdu:

1. **VM'ler için Prometheus güvenilir değil.** Bir VM'e node_exporter kurulması
   müşterinin elinde değildir (VM'ler genelde üçüncü taraf ekipler tarafından
   yönetilir); node_exporter kurulu olmayan VM'ler "Scrape yok" gösterir —
   oysa hypervisor zaten bu veriyi (CPU/RAM/disk QuickStats) API üzerinden
   sağlıyor.
2. **Fiziksel sunucular için vCenter yok.** Fiziksel donanımın bir hypervisor
   API'si yoktur — tek doğru kaynak Prometheus/node_exporter'dır.

Bunun üstüne, ikinci bir gerçek dünya sorunu: bir VM'e daha önce (yanlışlıkla
veya test amaçlı) node_exporter kurulmuşsa, bu VM hem vCenter'da hem
Prometheus'ta görünüyordu — fiziksel sunucu özet ekranına VM'ler "sızıyordu."

## Yaklaşım

`MetricSyncService.sync_all_servers_metrics`
(`backend/app/services/metric_sync.py:580`) her senkronizasyon turunda
sunucuları **tipe göre kesin olarak ikiye ayırır** ve bu ayrım asla karışmaz:

```
                    ┌─────────────────────┐
                    │  Server.status =     │
                    │  ONLINE (adaylar)    │
                    └──────────┬───────────┘
                               │
                    is_vm(s)? ─┼─ Evet ──► vm_servers[]
                               │            (hypervisor_id dolu olmalı)
                               │
                               └─ Hayır ──► physical_servers[]
                                            (ai_ready veya
                                             node_exporter_running)
                                            │
                     ┌──────────────────────┴───────────────────┐
                     ▼                                          ▼
        sync_physical_servers_metrics_batch()         sync_vmware_fallback_batch()
        (Prometheus, batch PromQL sorguları)           (vCenter QuickStats/PerfManager,
                                                         thread pool'da — event loop
                                                         kilitlenmesin diye)
```

**Bir VM'de node_exporter çalışıyor olsa bile** Prometheus'a hiç sorgu atılmaz
— `is_vm(s)` true olduğu an o sunucu `vm_servers` listesine gider ve sadece
vCenter'dan metrik alır. Bu, "iki kaynaktan çelişen veri" sınıfının tamamını
ortadan kaldırır.

## `monitoring.py`'daki ikinci savunma katmanı

Yukarıdaki ayrım arka plan senkronizasyonunu (TimescaleDB'ye yazılan geçmiş
veri) kapsar. Ama `/monitoring/metrics/servers` (canlı Prometheus `up` özeti,
Live Metrics dashboard'unun kullandığı) **ayrı bir kod yolu** — kendi ikinci
savunma katmanı var: `matched_instances` seti, `ONLINE` durumdaki VM'lere ait
Prometheus instance'larını **önceden** dolduruyor, böylece "eşleşmeyen"
hedefleri fiziksel sunucu olarak sentezleyen döngü VM'leri asla dahil etmiyor
(`backend/app/api/monitoring.py`, `list_metric_servers`).

## Neden vCenter çağrıları thread pool'da çalışır

`sync_vmware_fallback_batch` senkron `requests` kütüphanesiyle SOAP/REST
çağrıları yapar. `sync_all_servers_metrics` bir `async def` fonksiyon ve
FastAPI/Uvicorn **tek event loop** üzerinde çalışıyor — bu fonksiyon
`await` olmadan doğrudan çağrılsaydı, vCenter yanıt vermediği her an (timeout'a
kadar onlarca saniye) **tüm platformun** event loop'u kilitlenirdi. Bu tam
olarak müşteri ortamında yaşanan "tüm sayfa spinner'da donuyor" hatasının kök
nedeniydi (bkz. Trade-off'lar). Çözüm:

```python
loop = asyncio.get_event_loop()
vm_stats = await loop.run_in_executor(
    None, MetricSyncService.sync_vmware_fallback_batch, db, vm_servers
)
```

`run_in_executor(None, ...)` çağrıyı varsayılan `ThreadPoolExecutor`'a
devrediyor — event loop bu süre boyunca başka isteklere (health check, diğer
kullanıcıların sayfa yüklemeleri) yanıt vermeye devam ediyor.

## `hostname` vs `ip_address` tuzağı

`Hypervisor.hostname` alanı genelde bir **görünen ad**dır ("Vcenter datatem"),
`ip_address` ise gerçek bağlantı adresidir. `VCenterClient`'ı `hyp.hostname`
ile başlatan eski kod, görünen ad çözümlenemediği için (DNS'te yok) bağlantı
kurulamıyordu ama fiziksel sunucu tarafı etkilenmediği için sorun uzun süre
fark edilmedi (yalnızca VM metrikleri "Scrape yok" gösteriyordu). Düzeltme
her iki çağrı noktasında da (`metric_sync.py`, `servers.py`) aynı:

```python
host = hyp.ip_address or hyp.hostname
```

## Trade-off'lar

- **Basitlik vs. esneklik:** Bir VM'i "hibrit" modda (hem vCenter hem
  Prometheus'tan veri birleştirerek) izlemek mümkün değil — kasıtlı bir
  kısıtlama. Tutarlılık, teorik esneklikten daha değerli görüldü.
- **vCenter kullanılamazsa VM metriği yok:** Fallback olarak Prometheus'a
  dönülmüyor. Alternatif tasarımda "vCenter başarısız olursa Prometheus'u dene"
  eklenebilirdi, ama bu iki kaynağın aynı VM için farklı zaman damgalarında
  farklı değerler üretmesi riskini geri getirirdi.

## İlgili
- [Sanallaştırma / Hypervisor Yönetimi](features/virtualization.md) — How-to + Reference
- [Ölçek ve Performans](scale-and-performance.md) — 10k+ sunucu ölçeğinde batch sorgu stratejisi
- [Windows Platform](features/windows-platform.md) — Windows Exporter vs WinRM canlı metrik ayrımı

---
Back to [Documentation Index](index.md)
