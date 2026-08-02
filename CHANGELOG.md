# Changelog

Bu dosya, GitHub Release notlarının kalıcı ve air-gapped (internetsiz) müşteri
ortamlarında da erişilebilir bir kopyasıdır — internet erişimi olmayan
kurulumlarda `github.com/.../releases` sayfasına bakılamadığı için, paketle
birlikte gelen bu dosya sürüm geçmişini görmenin tek yoludur.

Format [Keep a Changelog](https://keepachangelog.com/) yaklaşımına yakındır.
Yeni bir release oluştururken bu dosyaya da bir madde eklemek için
`scripts/release.sh` kullanın (bkz. o script'in başlığı).

## [Unreleased]

### Düzeltildi
- Validasyon hataları (Pydantic) artık diğer API hataları gibi Türkçe, tutarlı
  `{"detail": ...}` formatında dönüyor.
- Kimlik doğrulaması olmadan var olmayan bir API path'ine istek atıldığında
  artık yanıltıcı 401 yerine doğal 404 dönüyor.
- `power_state` (VM açık/kapalı) normalizasyonu tek bir paylaşılan fonksiyona
  taşındı (`frontend/src/utils/powerState.ts`) ve birim testleri eklendi —
  Servers.tsx ve Hypervisors.tsx'teki 6+ tekrarlı/tutarsız kontrol kaldırıldı.
- Dashboard: kritik durum başlığı artık severity rengini (kırmızı/yeşil) doğru
  yansıtıyor; emoji ikonlar (📊, ⚠) `lucide-react` ikonlarıyla değiştirildi.

### Eklendi
- `scripts/dev-setup.sh`: yerel geliştirme için `.env` dosyasını otomatik
  `SECRET_KEY`/`POSTGRES_PASSWORD` ile hazırlayan script.

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
