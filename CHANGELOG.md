# Changelog

Bu dosya, GitHub Release notlarının kalıcı ve air-gapped (internetsiz) müşteri
ortamlarında da erişilebilir bir kopyasıdır — internet erişimi olmayan
kurulumlarda `github.com/.../releases` sayfasına bakılamadığı için, paketle
birlikte gelen bu dosya sürüm geçmişini görmenin tek yoludur.

Format [Keep a Changelog](https://keepachangelog.com/) yaklaşımına yakındır.
Yeni bir release oluştururken bu dosyaya da bir madde eklemek için
`scripts/release.sh` kullanın (bkz. o script'in başlığı).

## [Unreleased]

## [1.0.9.25] - 2026-08-14

### Düzeltildi — kurulum / Dropt Postgres şifresi
- Eski `data/dropt/postgres` (veya ainew Timescale) + yeni `.env` şifresi: `install-rhel.sh` / `update-rhel.sh` önce yalnızca DB/Redis açar, unix/local trust ile `ALTER USER`, sonra `dropt-api` (ağ scram). `set -e` yüzünden ALTER’a hiç gelmeme tuzağı kalktı.
- Timescale/PG data paket imajıyla açılmazsa silinmez; `*.bak-incompatible-*` olarak kenara alınıp boş küme init edilir.

### Level 1 / Operasyon merkezi
- Tek-host sihirbazlar (hostname, reboot, terminal, servis, path, log, sysctl, limits, network, VLAN): Ops Center / konsol `serverId` ile açılınca sunucu listesi yok; `hostname · IP` özeti.
- Yerel kullanıcılar: tüm işlemler çoklu sunucuda; ayrı `bulk_lock` menü öğesi kalktı. Kullanıcı tablosu yalnızca tek sunucu seçiliyken görünür.
- ASM ve Mail Config çoklu seçici olarak kaldı.

### OpenShift MTV / Explorer
- MTV sağlayıcı silme; aranabilir proje seçici; daraltılabilir explorer nav; VM snapshot drawer.

### UI dili (TR / EN)
- Kullanıcı menüsünde tema gibi TR|EN seçimi; tercih `users.locale` + `PATCH /auth/preferences` (kullanıcı bazlı).
- Level 1 / Dropt ayrı dil seçici kullanmaz; ana locale’i izler.
- Teknik terimler (Cluster, Pod, interface, Host, AIOps…) her iki dilde İngilizce kalır.

### DATA_DIR kanonik yol
- Kalıcı veri her zaman `$INSTALL_DIR/data` (örn. `/dttadvance/app/data`). Compose `${DATA_DIR:-./data}`; hardcoded `/data/data` kaldırıldı.
- `install-rhel.sh` / `update-rhel.sh` DATA_DIR’i kanonik yola zorlar.
- Doküman (`deployment.md`, `INSTALL_RHEL.md`) aynı kurala güncellendi.
- Dev `docker-compose.yml`: tüm ana servislere `restart: unless-stopped` (reboot sonrası Dropt ile aynı otomatik kalkış; prod zaten vardı).

### Remote LLM / Bifrost kimlik
- Çift yol netleştirildi: **Virtual Key → `x-bf-vk`** (Bifrost `sk-bf-…`, API Key boş = curl ile aynı); **API Key → `Authorization`** (eski yol). İkisi birlikte de gönderilebilir.
- Ayarlar UI sırası/hint’leri ve bağlantı testi 401 mesajı buna göre.

### Level 1 / Dropt envanter filtresi
- Sync adayları: **AI Ready + IP + (RHEL | Oracle Linux)**; `exadata_nodes.server_id` bağlı sunucular hariç.
- Linux modülü görünürlüğü bu filtreden bağımsız (ileride Exadata Linux listesinde de görünebilir; Dropt’a gitmez).
- Create sonrası best-effort Dropt projeksiyonu aynı eligibility kuralını kullanır.

### Performans / altyapı (Dalga 0–3)
- **Disk/Docker hijyen:** kullanılmayan imaj/cache temizliği; Prometheus file-SD yazma izni (`appuser` + entrypoint chown, atomic target save).
- **Level 1 oturum UX:** Dropt token TTL cache + in-flight dedupe; soft open (sayfa spinner’sız açılır); asistan sync fire-and-forget. Dropt upstream 401/403 artık ainew JWT 401’i gibi oturum düşürmez (502).
- **Arka plan → Celery:** onboarding, NLQ inventory, inventory/metric/ESX sync, log/anomaly, exporter bayrak sync, windows live metrics, health — `server_management_worker` kuyruğunda. API process yalnızca scheduler tick + enqueue; Redis `fleet_lock` ile çift çalışma engeli; worker yoksa local fallback.
- **Process worker ayarları (Gelişmiş):** `celery_concurrency`, `uvicorn_workers` — kayıt `/app/uploads/ainew_process_workers.env`; uygulamak için ilgili container recreate. Multi-uvicorn’da BG scheduler fcntl ile tek process.

## [1.0.9.24] - 2026-08-13

### Eklendi / iyileştirildi — Linux sunucu kimliği
- Linux Yönetimi listesi: birincil etiket OS **hostname** (yoksa guest FQDN / name); ikincil satırda IP + VM adı.
- Arama: hostname, VM adı (`vm_name`), guest hostname ve IP; varsayılan sıralama hostname.
- Admin / linux modülü: VM adı ≠ hostname için **İsim uyumsuz** badge + filtre + summary sayısı.
- Level 1 Dropt sync: AI Ready + RHEL + `skip_connection_test`; description’a ainew adı; Ops Center araması description’ı da tarar.

### Eklendi / iyileştirildi — Chat, Remote LLM, platform
- Model erişilemez banner (Linux / Windows / Unified / Hypervisor chat).
- Remote LLM isteğe bağlı Virtual Key (`REMOTE_LLM_VIRTUAL_KEY` / `x-bf-vk`).
- Platform Durumu log paneli kendi içinde kayar.
- Live Metrics select: dark `colorScheme` (okunabilir dropdown).

### Düzeltildi — DB taşıma / restore
- `pg_dump` `\restrict` / stderr satırları sanitize; Timescale DROP CASCADE hazırlığı; restore öncesi app pool dispose.

## [1.0.9.23] - 2026-08-11

### Eklendi / iyileştirildi — Linux Yönetimi
- OS sütunu: kısa etiket + ikon; hover’da tam PRETTY_NAME.
- SSH `/etc/os-release` `VERSION_ID` ile minor sürüm (ör. RHEL 9.7 / 9.8); vCenter yalnızca major (`RHEL_9_64`) verir.
- Çoklu seçim, çift tık detay, gelişmiş sağ tık menü; çevrimdışıları üste sıralama.
- AI Ready / OS yenileme: SSH kimlik bilgisi yoksa engellenir; TCP sağlık kontrolü kimlik olmadan çalışır.
- Level1 Dropt: otomasyon şifresi zorunluluğu; erişilemeyen host senkron/konsol davranışı.

### Düzeltildi — Dark tema ana menü okunabilirliği
- Dark `--text-secondary` / `--text-muted` token'ları `#c5d0e8` / `#9aabcb` (sidebar yüzeyinde yüksek kontrast).
- Ana menü (Layout) inactive öğeler `--text-secondary`; `aside.app-sidebar` için zorunlu nav renk kuralları eklendi.
- Prod frontend imajı yeniden build edilmeden görünmez (kaynak mount yok).

### Düzeltildi — Fiziksel host ekleme UI donması
- `POST /servers/` artık DB kaydını hemen döner; SSH OS probe + Dropt projeksiyonu
  `BackgroundTasks` ile arka planda (kısa SSH timeout). Önceden istek 20–60s+
  bloke olunca modal "Ekleniyor..."da kalıyordu; kayıt yine de oluşuyordu.
- `virt_datastores` tablosu: datastore başına capacity/free/accessible (ESX metric sync ile upsert).
- `servers` VM alanları: `vm_host_name/ref`, `vm_guest_os_full`, `vm_disks`, QuickStats özeti (`vm_cpu_usage_mhz`, `vm_mem_active_mb`, `vm_stats_as_of`).
- VM enrich: disk listesi, NIC portgroup, SOAP placement (host/cluster).
- Hypervisor intelligence datastore yolu: taze DB önce, değilse canlı API.
- Chat tools: `db_list_vms`, `db_vm_detail`, `db_list_datastores`, `db_list_esx_hosts`, `db_virt_alarms` (DB-first; stale → canlı tool).
- Chat tool politikası (`chat_tool_policy` + `unified_tool_chat`): virt / vCenter domain’de
  ilk 2 adımda `vcenter_ask` / `vcenter_live_*` şemadan gizlenir; DB `stale`/boş/hata veya
  faz dolunca canlı araçlar açılır (HypervisorChat + Unified aynı döngü).
- Virt chat: ince LangGraph `chat_source` (`decide_source → execute_tools → finalize`) +
  `WorkflowRun` izi; başarısızsa eski `run_read_only_tool_loop` fallback.
- VMware metric sync: QuickStats (`vm_stats_as_of` / cpu_mhz / mem) metric_data olmasa
  bile Server satırına commit edilir.
- Deterministik virt QA: VM envanter özetine host kırılımı; tek-VM QuickStats (DB);
  datastore boş özetinde kaynak etiketi DB/canlı; `db_list_vms` power_state filtresi
  `POWERED_ON` ile doğru eşleşir.
- Virt chat VM liste limiti: Gelişmiş Ayarlar `virt_chat_vm_list_limit` /
  `virt_chat_vm_list_hard_max`. “Tüm VM’ler” → uyarı → onay; onay **yalnızca o soruya**
  hard_max uygular, cevap bitince varsayılan limite döner.
- Tüm chat’ler (Linux/Windows/Unified/Virt/OCP): ortak `chat_full_scan_policy` —
  “tüm filo / tüm liste / bütün sunucular / all servers …” keyword’leri; onaylı tek-soru
  `chat_fleet_hard_max`; varsayılan `chat_ssh_fleet_cap`.
- Chat chitchat hızlı yolu (`chat_chitchat_policy`): selam / hâl hatır / kimlik /
  teşekkür / vedâ / kısa onay / yardım / nezaket (TR+EN+kısaltma+bileşik kalıplar);
  SSH/tool/RAG yok; ops kelimesi varsa chitchat değil. Full-scan onayı chitchat’ten önce
  (ok/tamam çakışmaz).

## [1.0.9.22] - 2026-08-10


## [1.0.9.21] - 2026-08-04

### Eklendi — `install-rhel.sh` / `update-rhel.sh`: `--ollama-files <dizin>`
- Air-gapped sunucularda artık ayrı bir script çalıştırmaya gerek kalmadan,
  ana kurulum/güncelleme script'inin kendisine elle indirilmiş Ollama runtime
  dosyalarının (ollama.tar.gz[.part*] + ollama-models-*.tar.gz) bulunduğu
  klasör tek argümanla verilebiliyor:
  `sudo ./install-rhel.sh --ollama-files /path/to/dosyalar` veya
  `sudo ./update-rhel.sh --install-dir /data --ollama-files /path/to/dosyalar`.
  İmaj/model zaten yüklü değilse ve otomatik internet indirmesi mümkün
  değilse önce bu klasöre bakılır — internete hiç çıkılmadan kurulumun/
  güncellemenin geri kalanıyla aynı tek script akışında tamamlanır.
  `install-ollama-runtime.sh` (v1.0.9.19'da eklenen ayrı script) hâlâ mevcut
  ve zaten kurulu bir sistemi sonradan tamamlamak için kullanılabilir.

## [1.0.9.20] - 2026-08-04

### Eklendi — Tam gömülü ("bundle") with-ollama paketi
- `ainew-<sürüm>-linux-amd64-with-ollama.tar.gz` paketi artık Ollama imajını
  ve `nomic-embed-text` embedding modelini doğrudan pakete gömülü olarak
  içeriyor (`--bundle-ollama` derleme modu). Bu paketle kurulum yapılan
  sunucu **hiçbir zaman internete çıkmaz** — hedef sunucunun interneti
  olmayıp yalnızca GitHub Release'ine erişimi olan (dosyaları scp/USB ile
  taşıyan) müşteriler için, v1.0.9.16+'daki "kurulum sırasında bir kereye
  mahsus indir" davranışının tamamen offline alternatifi.

## [1.0.9.19] - 2026-08-04

### Düzeltildi — Ollama runtime indirme hatası tüm servisleri düşürüyordu
- `with-ollama` paketinde Ollama imajı/embedding modeli internetten
  indirilemediğinde (ağ erişimi yok, disk dolu vb.) `install-rhel.sh` ve
  `update-rhel.sh` bunu sessizce geçip yine de `--profile ollama` ile
  `docker compose up` çalıştırıyordu; bu da TÜM çalıştırmanın
  `no such image: docker.io/ollama/ollama:latest` hatasıyla düşmesine yol
  açıyordu (müşteri ortamı bulgusu: podman tabanlı/internet erişimi kısıtlı
  RHEL 9 sunucusu). Artık Ollama profili yalnızca imaj fiilen yüklüyse
  eklenir; yüklenemediyse net bir uyarı basılıp o adım atlanır, diğer tüm
  servisler normal başlar.

### Eklendi — `install-ollama-runtime.sh`: Ollama runtime'ı tek komutla kurma
- Air-gapped sunucularda, `ollama-runtime-v1` GitHub release'inden internetli
  bir makinede indirilen dosyaları (imaj parçaları + embedding modeli) TEK
  KOMUTLA kuran yeni bir betik eklendi: parçaları birleştirir, varsa
  `.sha256` ile bütünlük doğrular, imajı docker/podman'a yükler, modeli açar,
  `.env`'i günceller, servisleri Ollama profiliyle başlatır ve sağlık
  kontrolü yapar. İdempotenttir. Bkz. `docs/INSTALL_RHEL.md` §5.3.

## [1.0.9.18] - 2026-08-02

### Düzeltildi — AI Asistan: gereksiz SSH beklemesi
- "Sunucularımızın kernel versiyonları" gibi sorular, kernel_version/os_version/
  hostname zaten veritabanında (periyodik taramadan) kayıtlı olmasına rağmen tüm
  AI Ready filoya paralel canlı SSH bağlantısı açıp 20-90 saniye beklemeye
  neden oluyordu. AI Asistan artık bu tür statik/yapısal alanları doğrudan
  veritabanından okuyor; SSH'a yalnızca DB'de olmayan veriler (servis durumu,
  güvenlik/SELinux, açık portlar, loglar vb.) veya kullanıcı açıkça "canlı
  doğrula" dediğinde gidiliyor.

### Düzeltildi — Raporlar ve sunucu karşılaştırma
- Linux/Windows/Exadata operasyon raporları artık frontend'in beklediği
  `event_breakdown` (severity'li) ve `daily_trend` (critical sayılı) şemasını
  döndürüyor; bu üç platformun kapasite/risk raporları için sanallaştırmaya
  özel görünüm yerine kendi verilerini (top_servers/nodes, risky_servers/
  unhealthy_racks) doğru gösteren ayrı görsel bileşenler eklendi.
- Sanallaştırma kapasite raporunda kullanım zaten %80 üzerindeyken negatif/
  anlamsız "-1724 gün içinde %80'e ulaşacak" uyarısı üretiliyordu; artık
  "zaten %80'in üzerinde" olarak raporlanıyor. Kapasite tahmin raporunda
  düşen trendlerde negatif kullanım yüzdesi üretilmesi önlendi.
- Sunucu karşılaştırma: AI yorumu `generate_async`'e eksik `httpx` client
  argümanı nedeniyle her zaman hata veriyordu, düzeltildi. Candidate
  filtreleme artık `platform_scope.server_ids_for_platform` kullanıyor
  (Exadata node'larının Linux/Windows karşılaştırma listesine sızmasını
  önler).
- Yukarıdaki "gereksiz SSH beklemesi" düzeltmesi yalnızca `/chat/` (non-
  streaming) uç noktasına uygulanmıştı; frontend'in gerçekte kullandığı
  `/chat/stream` (SSE) uç noktası hâlâ eski/yavaş davranıştaydı ("kernel
  versiyonları" hâlâ tüm filoya SSH atıyordu). İki uç noktanın anahtar
  kelime/karar mantığı artık modül seviyesinde paylaşılan tek bir yerden
  (`DB_STATIC_SYSINFO_KEYWORDS`, `_classify_db_only_sysinfo`) yönetiliyor,
  böylece ileride yalnızca birinin güncellenmesi riski ortadan kalktı.
- Risk Dashboard'daki yanıltıcı "Güvenlik Skoru" etiketi "Sağlık Skoru"
  olarak düzeltildi.
- Exadata executive summary artık gerçek bir sağlık skoru hesaplıyor
  (önceden hep "Normal" dönüyordu).

## [1.0.9.17] - 2026-08-02

### Düzeltildi — Kritik: 10.000+ sunucu ölçeğinde donma (hang) riskleri
- Event loop'u bloke eden **tüm** kalan senkron çağrılar thread pool'a taşındı:
  AI Agent chat/onay/red uçları, RCA (AWR/quick-analyze) LLM çağrıları, Windows
  AI Chat WinRM toplama, hypervisor/OpenShift bağlantı testleri ve VM senkronu,
  Ansible/AWX uçları, SSH terminal bağlantısı, sunucu sağlık kontrolü. Bunların
  hiçbiri artık tek worker'lı event loop'u kilitleyemiyor.
- `MetricSyncService`: fiziksel sunucu metrik senkronu artık sunucu başına tek
  tek değil, metrik başına **toplu (batch) PromQL** sorgusu ile çalışıyor
  (`instance=~"regex"`), sorgu sayısını sunucu sayısından bağımsız hale getirdi.
  PromQL regex escape hatası (Go string literal `\.` parse hatası) düzeltildi.
- `system_events` tablosuna `created_at`, `last_seen` ve `(server_id, last_seen)`
  bileşik indeksleri eklendi (288K satırda 1.4M seq scan'e neden oluyordu);
  ayarlanabilir otomatik retention (varsayılan 180 gün) eklendi.
- Postgres `max_connections` 100 → 500, uygulama havuzu `pool_size`/`max_overflow`
  50/100'e yükseltildi; SSH/WinRM/log toplama worker sayıları artık sabit kod
  yerine ayarlanabilir (`bulk_ssh_workers()`), Windows log toplama ve uygulama
  keşfi paralelleştirildi.
- WinRM canlı metrik uçlarına single-flight cache (TTL'li) eklendi — 30 sn'lik
  frontend polling'i artık sunucu sayısı kadar eşzamanlı WinRM çağrısı üretmiyor.
- uCMDB senkronu: O(N²) Python taraması yerine O(1) doğrudan SQL sorgusu.

### Düzeltildi — Metrik kaynağı ayrımı ve vCenter
- VM'ler artık her zaman vCenter'dan (QuickStats/PerfManager), fiziksel
  sunucular her zaman Prometheus/node_exporter'dan metrik alıyor.
- Hypervisor kaydında `hostname` alanı görünen ad olsa bile `ip_address`'e
  düşülüyor (vCenter bağlantı hatası düzeltmesi).
- `/monitoring/metrics/servers` artık yalnızca gerçek fiziksel host'ları
  listeliyor; eski node_exporter'ı çalışan VM'ler bu listeye sızmıyor.
- Sunucu performans sekmesinde `power_state` (VM açık/kapalı) normalizasyonu
  tek bir paylaşılan fonksiyona taşındı (`frontend/src/utils/powerState.ts`,
  birim testleriyle) — vCenter'ın camelCase (`poweredOn`) döndürdüğü durumlarda
  açık bir VM'in yanlışlıkla "Kapalı" görünmesi düzeltildi.

### Düzeltildi — API hataları ve DevEx
- Validasyon hataları (Pydantic) artık diğer API hataları gibi Türkçe, tutarlı
  `{"detail": ...}` formatında dönüyor.
- Kimlik doğrulaması olmadan var olmayan bir API path'ine istek atıldığında
  artık yanıltıcı 401 yerine doğal 404 dönüyor.

### Değişti — Tasarım tutarlılığı
- Dashboard: kritik durum başlığı artık severity rengini (kırmızı/yeşil) doğru
  yansıtıyor.
- Tüm arayüzdeki fonksiyonel emoji ikonlar (`DESIGN.md` ihlali) `lucide-react`
  ikonlarıyla değiştirildi (~30 dosya).

### Eklendi
- `scripts/dev-setup.sh`: yerel geliştirme için `.env` dosyasını otomatik
  `SECRET_KEY`/`POSTGRES_PASSWORD` ile hazırlayan script.
- Kök `CHANGELOG.md` ve `scripts/release.sh`: air-gapped müşteriler için
  sürüm geçmişini GitHub Release'lerle senkron tutan otomasyon.
- Yeni dokümanlar: sanallaştırma yönetimi, Windows platformu, metrik mimarisi
  açıklaması, 10k+ sunucu ölçek/performans rehberi (`docs/`).
- Ollama runtime kurulum dokümantasyonu (otomatik ve air-gapped manuel kurulum).

### Değişti — Depo düzeni
- İç kullanım belgeleri (`MERGE_CONFLICT_COZUMU.md`, `sunum/`) `docs/internal/`
  altına taşındı.

## [1.0.9.16] - 2026-08-01

### Düzeltildi
- **Kritik: uygulama donması (hang)** — VM'lerin vCenter'dan metrik çekmesi
  (periyodik arka plan senkronu) senkron/bloklayan `requests` çağrıları
  yapıyordu ve tek worker'lı event loop'u kilitliyordu. Bu sırada `/auth/me`
  dahil TÜM API istekleri yanıt veremiyor, arayüz sürekli dönen bir yükleme
  ekranında takılı kalıyordu. Artık bu çağrılar thread pool'da çalıştırılıyor.

## [1.0.9.15] - 2026-08-01

### Eklendi
- **Metrik kaynağı ayrımı**: VM'ler artık her zaman vCenter'dan
  (QuickStats/PerfManager), fiziksel sunucular her zaman Prometheus/node_exporter'dan
  metrik alır.

### Düzeltildi
- **vCenter bağlantı düzeltmesi**: Hypervisor kaydında `hostname` alanına
  yanlışlıkla görünen bir ad girilmişse bile artık `ip_address` alanına
  düşülüyor.
- **Fiziksel sunucu özet ekranı düzeltmesi**: `/monitoring/metrics/servers`
  artık yalnızca gerçek fiziksel host'ları listeliyor; eski node_exporter'ı
  çalışan VM'ler bu listeye sızmıyor.

## [1.0.9.14] - 2026-08-01

### Eklendi
- Admin/yönetici sorularını güvenilir cevaplamak için merkezi intent router
  (`admin_intent_router`).
- "Hangi datastore'da hangi VM var" sorusu artık isimli VM haritası döndürüyor.

## [1.0.9.13] - 2026-07-31

### Değiştirildi
- Virt Q&A kuralları ve Linux admin SSH konu eşlemesi sertleştirildi.
- Learned Facts: Linux whitelist genişletme, hypervisor inventory → virt facts.
- "bilinmiyor" cevap temizliği (`answer_sanitize`).
- Bilgi Bankası: fact düzeltme / onay API + UI.
- Fleet SSH cap 64, vCenter event timeout 60s.

---

Daha eski sürümler (1.0 – 1.0.9.12) için [GitHub Releases](https://github.com/datatemteknoloji/ai_eyup/releases) sayfasına bakın.
