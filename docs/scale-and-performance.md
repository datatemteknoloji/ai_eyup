# Ölçek ve Performans (10.000+ Sunucu)

> **Diataxis:** Reference + How-to

Bu doküman, platformun **10.000+ sunucu** ölçeğinde çalışacak müşteri ortamları
için yapılan ayarları ve bunların **neden** gerekli olduğunu belgeler. Buradaki
her madde gerçek bir "hang" (donma) veya performans sorununun kök nedenidir —
sadece teorik tavsiye değildir.

## Altın kural: FastAPI'de bloklayan çağrı = tüm platform donar

Uygulama **tek Uvicorn worker** ve tek `asyncio` event loop üzerinde çalışır.
Bir `async def` endpoint içinde `await` olmadan senkron/bloklayan bir çağrı
(SSH, WinRM, vCenter SOAP, LLM HTTP isteği, Ansible subprocess) yapılırsa, o
çağrı bitene kadar **event loop'taki başka hiçbir istek işlenmez** — `/health`
dahil. Bu, müşteri ortamında yaşanan "tüm sayfa spinner'da donuyor" hatasının
kök nedeniydi.

**İki geçerli çözüm:**

1. **Endpoint'i `async def`'ten `def`'e çevir.** FastAPI, `def` endpoint'leri
   otomatik olarak bir thread pool'da (AnyIO) çalıştırır — event loop
   bloklanmaz. Bloklayan işin **tamamı** o endpoint içindeyse (SSH/WinRM
   bağlantı testi, Ansible playbook çalıştırma, LLM'e senkron istek) bu en
   basit çözümdür.
2. **`await loop.run_in_executor(None, blocking_fn, ...)` kullan.** Endpoint
   `async def` kalmalı ama içinde bir noktada bloklayan bir çağrı yapılıyorsa
   (ör. bir arka plan görevi içinden vCenter'a bağlanmak) bu çağrıyı thread
   pool'a devret.

Bu düzeltme şu dosyalarda uygulandı (referans için): `metric_sync.py`
(vCenter fallback), `agent.py`, `rca.py`, `windows_chat.py`, `hypervisors.py`
(bağlantı testleri + VM sync), `openshift.py`, `ansible.py`, `terminal.py`,
`servers.py` (health check + SSH durumu içeren liste).

**Kural:** Yeni bir endpoint yazarken SSH/WinRM/vCenter/LLM/subprocess
çağrısı içeriyorsa, ya `def` yapın ya da `run_in_executor` ile sarın. `async
def` + senkron `requests`/`paramiko`/`winrm` çağrısı = potansiyel platform
donması.

## Veritabanı bağlantı havuzu

| Ayar | Değer | Dosya |
|---|---|---|
| SQLAlchemy `pool_size` | 50 | `backend/app/core/database.py` |
| SQLAlchemy `max_overflow` | 100 (toplam 150) | `backend/app/core/database.py` |
| Postgres `max_connections` | 500 | `docker-compose.yml`, `deploy/docker-compose.prod.yml` |

**Neden:** Ana pool (150) + arka plan `NullPool` thread'leri (toplu SSH/TCP/log
/WinRM işleri her biri kendi bağlantısını açar, 10k ölçekte onlarca worker'a
çıkabilir) toplamda Postgres'in **varsayılan** `max_connections=100` değerini
kolayca aşar → "too many clients" hatası veya `pool_timeout=30s` boyunca
donma. `max_connections` compose dosyasında **explicit** ayarlanmazsa
Postgres varsayılana (100) düşer — bu iki değer (pool + Postgres) birlikte
değiştirilmelidir.

## Worker sayıları (Ayarlar → Worker sayıları)

Tüm toplu (bulk) SSH/WinRM/TCP işlemleri sabit kodlanmış worker sayısı yerine
`bulk_concurrency.py`'daki fonksiyonlardan okur — çalışma zamanında Ayarlar
sayfasından değiştirilebilir:

| Ayar | Varsayılan | Aralık | Kullanıldığı yer |
|---|---|---|---|
| `bulk_ssh_workers` | 25 | 1-128 | Auto-onboarding, app discovery, bulk NE kurulum, live metrics |
| `log_ssh_workers` | 32 | 1-64 | Linux log tarama |
| `windows_log_workers` | 20 | 1-64 | Windows Event Log toplama |
| `bulk_tcp_workers` | 100 | 1-256 | Toplu TCP health check |
| `windows_log_batch_size` | 500 | 50-5000 | Windows log tarama batch boyutu |

10.000+ sunucu ortamında bu değerleri **DB pool'un kaldırabileceği payla**
dengeli artırın (worker sayısı × ortalama sorgu süresi, pool_timeout'u
aşmamalı).

## Metrik senkronizasyonu: batch PromQL sorguları

Eskiden her fiziksel sunucu için ayrı ayrı ~38 PromQL sorgusu sıralı
çalıştırılıyordu (N sunucu × 38 sorgu = doğrusal olmayan bir maliyet). Şimdi
`MetricSyncService.sync_physical_servers_metrics_batch`
(`backend/app/services/metric_sync.py:343`) her **metrik** için tek bir
`instance=~"ip1|ip2|..."` regex sorgusu atıyor — sunucular 300'lük gruplar
halinde chunk'lanıyor (URL uzunluk sınırı için).

**PromQL regex escape tuzağı:** IP adreslerindeki `.` karakteri Python'un
`re.escape()` ile `\.` olarak kaçırılırsa, bu PromQL sorgusu bir Go string
literal'ına gömüldüğünde ("`instance=~\"...\"`") "unknown escape sequence"
parse hatası veriyor. Çözüm: `_promql_regex_escape` özel karakterleri
backslash yerine tek elemanlı karakter sınıfına alıyor (`.` → `[.]`).

VM'ler bu batch'e hiç girmiyor — ayrı bir yoldan (`sync_vmware_fallback_batch`,
thread pool'da) vCenter'dan toplanıyor. Detay:
[Metrik Mimarisi](explanation-metrics-architecture.md).

## Windows canlı metrik cache'i

`GET /api/v1/windows/live-metrics` (frontend 30sn'de bir polluyor) 20 saniyelik
TTL'li bir **cache + single-flight lock** ile korunuyor
(`backend/app/api/windows.py:34-36`). Cache olmadan her poll, Windows sunucu
sayısı kadar paralel WinRM bağlantısı açardı — binlerce sunuculu ortamda bu
tek başına platformu tıkayabilir. Ölçülen etki: soğuk çağrı ~5.9s → sıcak
çağrı ~0.8s (7x).

## `system_events` tablosu: index + retention

`system_events` (anomali, log, vCenter olayı gibi periyodik kayıtların
biriktiği tablo) hiçbir index veya otomatik temizlik olmadan sürekli
büyüyordu — 288K satırda bile zaman bazlı sorgular 1.4M seq scan
yapıyordu.

**Eklenen index'ler** (`backend/app/models/event.py`,
`backend/app/main.py` startup migration):
- `created_at` (tekil)
- `last_seen` (tekil)
- `(server_id, last_seen)` (kompozit)

**Otomatik temizlik** (`backend/app/services/event_retention.py`,
`_periodic_event_cleanup` arka plan görevi):

| Ayar | Varsayılan | Aralık |
|---|---|---|
| `event_retention_days` | 180 gün | 30-3650 |
| `event_cleanup_interval_sec` | 6 saat (21600) | 1-24 saat |

Silme işlemi 5000'lik batch'ler halinde yapılır — tek büyük transaction'da
kilit tutmaz.

## uCMDB senkronizasyonu: O(N²) → O(1) arama

`ucmdb_sync_service.py`'deki `_find_by_ucmdb_id` eskiden **tüm sunucuları**
(binlerce satır) Python'a çekip döngüyle arıyordu — her uCMDB kaydı için bu
tekrarlanıyordu (O(N×M)). Artık filtreleme SQLAlchemy JSON operatörleriyle
veritabanı seviyesinde yapılıyor (O(1) indeksli arama).

## Kontrol listesi: Yeni bir müşteri ortamı 10k+ sunucu ile geliyorsa

1. Postgres `max_connections` ≥ 500, SQLAlchemy pool + overflow ile uyumlu mu?
2. `bulk_ssh_workers` / `log_ssh_workers` / `windows_log_workers` ortamın
   SSH/WinRM kapasitesine göre ayarlandı mı? (Çok yüksek değer hedef
   sunucuları veya jump host'u zorlayabilir.)
3. Yeni eklenen tüm bloklayan I/O içeren endpoint'ler `def` mi, yoksa
   `run_in_executor` ile mi sarılı? (Bkz. "Altın kural" yukarıda.)
4. Prometheus tarafında `scrape_interval`/`scrape_timeout` sunucu sayısına
   göre makul mü? (Binlerce hedef varsa çok kısa interval Prometheus'u
   zorlar.)
5. `system_events` retention ayarı (varsayılan 180 gün) ortamın disk/performans
   kısıtlarına uygun mu?

## İlgili
- [Metrik Mimarisi (VM vs Fiziksel)](explanation-metrics-architecture.md)
- [Sanallaştırma / Hypervisor Yönetimi](features/virtualization.md)
- [Windows Platform](features/windows-platform.md)
- [Deployment](deployment.md)

---
Back to [Documentation Index](index.md)
