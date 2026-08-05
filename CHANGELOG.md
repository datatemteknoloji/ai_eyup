# Changelog

Bu dosya, GitHub Release notlarının kalıcı ve air-gapped (internetsiz) müşteri
ortamlarında da erişilebilir bir kopyasıdır — internet erişimi olmayan
kurulumlarda `github.com/.../releases` sayfasına bakılamadığı için, paketle
birlikte gelen bu dosya sürüm geçmişini görmenin tek yoludur.

Format [Keep a Changelog](https://keepachangelog.com/) yaklaşımına yakındır.
Yeni bir release oluştururken bu dosyaya da bir madde eklemek için
`scripts/release.sh` kullanın (bkz. o script'in başlığı).

## [Unreleased]

### Eklendi — GPT-OSS 20B air-gapped chat modeli kurulum paketi
- Yeni, uygulama sürümünden bağımsız GitHub release:
  [`ollama-gpt-oss-20b-v1`](https://github.com/datatemteknoloji/ai_eyup/releases/tag/ollama-gpt-oss-20b-v1) —
  `gpt-oss:20b` chat modeli (~13GB, 7 parçaya bölünmüş) + `nomic-embed-text`
  embedding modeli birlikte paketlendi.
- Yeni `deploy/install-ollama-model.sh`: mevcut bir kuruluma TEK bir ek Ollama
  modelini (chat veya embedding) idempotent şekilde ekler — diskte zaten
  başka modeller olması bu betiği atlamaz (önceki `--ollama-files` /
  `install-ollama-runtime.sh` akışının aksine). `--set-default` ile
  `.env`'deki `AGENT_MODEL`'i de güncelleyebilir.
- `install-rhel.sh` (`--ollama-files`) ve `install-ollama-runtime.sh` artık
  bir klasördeki TÜM `ollama-models-*.tar.gz[.part*]` paketlerini (yalnızca
  embedding modeliyle sınırlı değil) açıyor — parçalanmış büyük model
  paketleri için birleştirme/doğrulama desteği eklendi.
- `scripts/export-ollama-embed-model.sh`: artık `isim:tag` biçimini (ör.
  `gpt-oss:20b`) doğru işliyor — önceden aynı ada sahip birden fazla tag'i
  olan modellerde (ör. `gpt-oss` → 20b/120b) yanlış tag paketlenme riski vardı.

### Düzeltildi — Sanallaştırma asistanı: VM ↔ ESX host eşlemesi eksikti
- `Server.vm_esx_host` alanı eklendi: her VM'in HANGİ fiziksel ESX host'ta
  çalıştığı artık senkron sırasında kalıcı olarak kaydediliyor (öncesinde bu
  bilgi vCenter'dan çekilse de hiçbir yere yazılmıyordu — "en fazla CPU
  kullanan VM'lerin ESX host kırılımı" gibi bileşik sorular bu yüzden
  cevaplanamıyordu).
- `vCenterClient`: host adı çözümlemesi artık `hypervisor_host_metrics`
  tablosunu besleyen AYNI SOAP kaynağından yapılıyor (REST API'nin bu alanı
  hiç döndürmediği/host adını farklı formatta (IP/FQDN) döndürebildiği
  ortamlarda tutarsızlığı önlemek için).
- Canlı VM performans sorgularına (`fetch_live_vm_stats`) ve "en çok CPU
  tüketen VM" / "%90 üzeri CPU" tablolarına ESX Host kolonu eklendi.
- Yeni deterministik soru tipi: "X host'unda hangi VM'ler var" — senkronize
  veriden anında cevaplanıyor, canlı sorgu gerekmiyor.
- En yoğun host sorgusuna, istenirse o host'un VM kırılımını da ekleme
  yeteneği eklendi.
- Agentic araç setine `vcenter_vms_by_host` (host bazlı VM listesi) ve
  `knowledge_base_search` (Bilgi Bankası/RAG sorgusu — tüm platformlarda
  kullanılabilir) araçları eklendi.
- DB'den (senkronize) gelen host metrik yanıtlarında yanlışlıkla "canlı
  sorguda dönmedi" diyen yanıltıcı mesajlar düzeltildi.

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
