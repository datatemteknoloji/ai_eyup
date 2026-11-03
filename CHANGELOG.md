# Changelog

Bu dosya, GitHub Release notlarının kalıcı ve air-gapped (internetsiz) müşteri
ortamlarında da erişilebilir bir kopyasıdır — internet erişimi olmayan
kurulumlarda `github.com/.../releases` sayfasına bakılamadığı için, paketle
birlikte gelen bu dosya sürüm geçmişini görmenin tek yoludur.

Format [Keep a Changelog](https://keepachangelog.com/) yaklaşımına yakındır.
Yeni bir release oluştururken bu dosyaya da bir madde eklemek için
`scripts/release.sh` kullanın (bkz. o script'in başlığı).

## [Unreleased]

## [1.0.9.45] - 2026-11-03

### OpenShift Access / RBAC: profesyonel okuma + yalnız-Admin OLUŞTURMA
- **Okuma** (`openshift` modülü yetkilileri): gruplu sekmeler (Genel / Kimlikler / Roller / Bağlamalar / Araçlar); sıralanabilir, aranabilir, sayfalı listeler (ortak `ColumnTable`); Role/ClusterRole **izin matrisi** (kaynak × fiil, wildcard ve `resourceNames` kısıtı işaretli); **etkin yetki** (doğrudan + grup üyeliği + örtük `system:authenticated`); **risk paneli** (cluster-admin sahipleri, özel wildcard roller, `system:authenticated` yetkisi, yetim binding/özne); ainew'in oluşturduğu nesneler rozetli ve süzülebilir.
- **Düzeltme:** liste uçları `continue` token'ını izlemiyordu (büyük cluster'da ilk sayfada kesilip sessizce eksik sayı/arama dönüyordu) — tüm sayfalar okunur; Özet/risk/etkin yetki 60 sn önbellekli ortak anlık görüntü kullanır.
- **Yazma — YALNIZ Admin, YALNIZ OLUŞTURMA:** RoleBinding, ClusterRoleBinding, Role, ClusterRole (form veya YAML; «mevcut rolden kopyala»). **Düzenleme, silme ve kullanıcı/grup yönetimi yoktur** (rota düzeyinde de yok). Güvenlik: girdi doğrulama; riskli içerik uyarıları (cluster-admin, wildcard, `escalate/bind/impersonate`, Secret okuma, `system:authenticated`) — kritikte nesne adını yazarak onay (sunucu da doğrular); `dryRun=All` ön izleme; audit kaydı (`openshift/access.create`, oluşturulan YAML ile; başarısız denemeler dahil); nesneye `app.kubernetes.io/managed-by: ainew` etiketi; 409 «aynı isimde zaten var»; Kubernetes yetki-yükseltme engeli Türkçe açıklanır; cluster token'ının `create` yetkisi türe göre sorgulanır (yetkisizse düğme gerekçeli pasif). Eşdeğer `oc delete …` komutu yalnız bilgi olarak gösterilir, ainew çalıştırmaz.
- **Admin'e özel okuma:** ham YAML görünümü ve OAuth IdP ayrıntıları (mapping/token). `access/get` artık ham nesne döndürmez. Sohbet aracı `ocp_access_query` **READ-ONLY** kalır.
- Yeni uçlar: `GET …/access/{capabilities,matrix,effective,risks,yaml}`, `POST …/access/create/preview`, `POST …/access/create`. Test: `test_ocp_access_write.py` (35), `openshiftAccess.test.tsx` (10).

### Değişiklikler (Virt + OpenShift): baseline görünürlüğü, canlı sapma, gözden geçirme
- **Baseline artık belli:** banner baseline'ı kim, ne zaman, kaç varlık için işaretlediğini gösterir; satırda baseline sahibi/tarihi; yeni **Baseline'lar** sekmesi her baseline'lı varlığı baseline↔son farkıyla listeler (canlı hesap).
- **«Sapma neden hep 0?» açıklandı:** sapma yalnız baseline'lı varlıklar için baseline↔son farktır; baseline son değişiklikten sonra alınmışsa veya değişen tür (ör. VM) baseline'lı değilse 0'dır. Ekranda bu iki durum açıkça yazılır; geçmiş (ardışık fark) ile sapma ayrıdır.
- **Silinemeyen değişiklikler:** «gözden geçirildi» (tekil/toplu, geri alınabilir) değişikliği silmeden varsayılan görünümden gizler; `POST /changes/prune` (admin, varsayılan dry-run; 365 gün + varlık başına son 20; latest/baseline korunur) eski anlık görüntüleri temizler. Yeni sütunlar `virt_config_snapshots.ack_by/ack_at` (otomatik, yalnız ekleme).
- **OpenShift parite:** `/ocp-insights` `/baseline`, `/baseline/compare`, `DELETE /baseline`, `/changes/ack`, `/changes/prune`. Toplu baseline mevcut baseline'ı ezecekse onay kutusu zorunlu.

### Olay / Incident sayıları: sorun düzelince düşer
- **Sorun:** çözülmüş sayılan olaylar akış toplayıcılarının 48 saatlik pencere tekrarı yüzünden `last_seen`/`occurrence_count` artırıp yeniden açılıyor; bazı türler hiç çözülmüyor, incident'ler bağlı olaylar düzelse de açık kalıyordu.
- **Yaşam döngüsü (`services/event_lifecycle.py`):** durum olayları (`vcenter_alarm`) 4 sa, nokta olayları önem derecesine göre (info 2 sa, warning 12 sa, error/critical 24 sa) sessiz kalınca otomatik çözülür; `metric_anomaly`/`hw_*` kendi yaşam döngüsünde, `manual` dokunulmaz; **hiçbir kayıt silinmez**. Atanmamış `auto_*`/fırtına incident'i bağlı tüm olaylar düzelince (≥15 dk) kapanır; sorun sürerken kapanmaz; kapanmış fırtına incident'i yeniden açılmaz; kritik anomaliler açık incident'e bağlanır.
- **Toplayıcı düzeltmesi:** vCenter, oVirt, OCP-Virt, virt_log ve OCP olay toplayıcılarında yeniden okunan (replay) olay artık tekrar sayılmaz/yeniden açmaz.

### OpenShift Dashboard ve açık tema
- **Açık tema:** rapor KPI sayıları (MTV Migrasyon dahil tüm raporlar) beyaz-üstü-mavi nedeniyle okunmuyordu; geniş `.text-white` kuralı yalnız düz mavi dolgulara daraltıldı (düğmeler beyaz metinli kalır), KPI değerleri tema renkli. Recharts eksen/ızgara/tooltip açık tema uyumlu. Kilit testi: `lightThemeContrast.test.ts`.
- **OpenShift Dashboard:** ortak sıralanabilir `ColumnTable` + `UsageBar`; node tablosu CPU/Memory çubukları (eşik renk, tooltip, açıklama), kaydırmalı ve sıralı «riskli pod» listesi (gerçek toplam: `/openshift/risks` artık `total` döner; önem filtresi; satıra tıklayınca ayrıntı çekmecesi), hazır olmayan node kutusu yalnız sorun varsa, VM namespace özeti kopyası kaldırıldı.
- `ColumnTable`: `pageSize` (sayfalama), `defaultSort`, `onRowClick`, `maxHeightClass`, `toolbar`, `countLabel` eklendi (geriye uyumlu).

### Donanım: portalsız (OME/OneView olmadan) log modu
- **Donanım sayfası artık portal şartı olmadan açılabilir:** portal bağlı değilken bile bir donanım log kaynağı açıksa (Host donanım logları, in-band ipmitool, BMC logları) veya log kaydı varsa menüde «Donanım» görünür; sayfa yalnız **Donanım Logları** ve **BMC** sekmeleriyle açılır (KPI/sunucu/şasi/alarm/garanti/firmware gizli, portal uçlarına istek atılmaz) ve «portal bağlı değil» notu gösterir. Portal eklenince tam sayfa gelir (değişiklik yok). `hardware` modülü RBAC'ı aynen geçerli.
- `GET /capabilities` yeni `has_hw_logs` alanı. Yeni port/firewall/hesap yok; yeni toplama başlatılmaz.

## [1.0.9.44] - 2026-11-01

### Level 1 (Dropt): oturum köprüsü düzeltmesi
- **Düzeltme:** Dropt bağımlılık yükseltmesinden (`sqlmodel` 0.0.48) sonra `/api/auth/bridge` 500 dönüyor, ainew Level 1 dashboard'u ve Dropt oturumu açılmıyordu (`Datetime values must have timezone information`). Dropt modellerindeki tarih alanları `NaiveDatetime` ile işaretlendi; veritabanı şeması değişmedi.
- **Dropt yığını:** Dropt imajı Python 3.14 ve güncel bağımlılıklarla (FastAPI, PyJWT, cryptography, celery vb.) yeniden derlendi.

## [1.0.9.43] - 2026-11-01

### Donanım: şasi/blade görünümü, firmware karşılaştırma, tablo sütunları ve giriş ekranı
- **Şasi / blade:** Kasalar sekmesi şasi kimliğiyle eşleşir (ad yalnız tekilse), blade'ler doğal yuva sırasında listelenir, sunucu kaydı olmayan yuvalar «Sunucu kaydı yok» diye gösterilir, aynı yuvadaki çok düğümlü sunucular gruplanır, şasisi belirlenemeyen blade'ler ayrı panelde listelenir (sessizce düşmez).
- **Firmware görünürlüğü:** Dell OME firmware envanteri imleçle döner (sınırdan fazla sunucuda hepsi sırayla okunur), `Installed`/`Available` durumu ve ComponentId saklanır, Dell BIOS sürümü envanterden türetilir. **HPE OneView appliance modu** için bileşen firmware'i (`/rest/server-hardware/{id}/firmware`) eklendi (yalnız okuma; OVGD'de uç yok; alan tipleri sahada doğrulanmadı). Sunucu satırında firmware listesi.
- **Referans karşılaştırma (Donanım › Firmware):** model veya şasi kapsamlı «referans sunucu» (şasi > model); yalnız kurulu bileşenler, sayısal sürüm karşılaştırması, ayrıştırılamayan sürüm «ölçülemedi» (asla «düşük» denmez). **«Kabul et»** yalnız kabul anındaki sürüm değişmedikçe geçerli. Yeni bulgu `hw.firmware.outdated` (metinde sürüm/BMC IP yok). Yazma uçları operatör+, yalnız ainew'e yazar. Yeni tablolar: `hw_firmware_references`, `hw_firmware_accepts`; `hw_firmware.location` sütunu.
- **Sunucular tablosu:** sunucu adından önce Dell/HP logosu; yeni sıralanabilir «BMC sürümü» ve «BIOS» sütunları (sayı duyarlı sıralama).
- **Giriş ekranı:** akış şeması yenilendi — Linux ve Windows ortak yapıyı paylaşır (HP/Dell → Fiziksel, Sanal); «Sanal» tek bağlantı çubuğuyla Sanallaştırma kümesine (vSphere, OpenShift, OLVM) bağlanır; açık temada çizgiler belirginleştirildi. Sol paneldeki **başlık ve açıklama Ayarlar › Marka'dan düzenlenebilir** (boş = varsayılan); «Sayılar ölçümden gelir; AI yalnızca yorumlar.» cümlesi varsayılan metinden kaldırıldı.

### OpenShift ve Yönetici (Tüm Ortamlar) Hazır Raporları + MTV geçmişi
- **OpenShift → Altyapı Raporları** (`/openshift/reports`): 14 rapor (Executive Summary, Kapasite, Tahmin, Kapasite Planı N+1, Risk, En Riskli, Proje kullanımı, PVC, Workload, KubeVirt VM, Uyum/Güncelleme, Operasyon, **MTV Migrasyon**, **MTV Hazırlık**). Veri yalnız ainew DB'sinden; tahmin ≥14 gün seri ister; veri yoksa «Ölçülemedi».
- **MTV geçmişi kalıcı:** yeni `mtv_plan_snapshots` tablosu (başlangıçta `create_all` ile oluşur; Alembic yok) — her 10 dk OpenShift senkronunda Plan/Migration anlık görüntüsü; silinen plan «Silindi» kalır, erişilemeyen küme hiçbir planı kapatmaz.
- **Yönetici → Tüm Ortamlar Raporları** (`/executive/infra-reports`): 11 rapor; her biri Sanallaştırma, OpenShift, Linux, Windows, Exadata'yı kapsar ama alan yalnız anlamlıysa girer (kapsam tablosu kodda; kapsam dışı satırı **neden** ile yazılır). Sentetik (ZZ-FAKE) hariç; yedek (Veeam) yok. Yeni API: `/api/v1/executive-reports/*` (yalnız `executive` modülü). Not: seçilen `/executive/reports` rotası zaten `/executive`'e yönlendirdiği için yeni sayfa `/executive/infra-reports`'ta.
- Ortak rapor şeması + tek görsel (`GenericReportView`); yöntem notları registry'den (4 yeni yöntem: `report.mtv.history`, `report.mtv.readiness`, `report.exec.health`, `report.exec.matrix`). Ekip raporlarının (virt/Linux/Windows/Exadata) çıktısı değişmedi.
- Test: yeni backend testleri (matris bütünlüğü, parse_plan, MTV kalıcılık, sentetik dışlama, modül politikası) + frontend Vitest.

### Sohbette «Rapor soruları» (OpenShift + Doğal Dil Asistanı) ve ilgili düzeltmeler
- **Rapor soruları:** Sanallaştırma sohbetindeki gibi OpenShift sohbetinde (12 chip, MTV dahil) ve Doğal Dil Asistanı'nda (11 chip, Tüm Ortamlar raporları) «Rapor soruları» bölümü; chip'e basınca sohbette doğrudan rapor özeti (KPI + tablolar + öneriler) döner. LLM yok: rakamlar rapor motorundan, cevap kısa özet (tam liste Hazır Raporlar sayfasında). Yönetici raporu `executive`, OpenShift raporu `openshift` yetkisi ister. Ayrıntı: `docs/guides/*/modules/ai-architecture.md`.
- **Yeniden adlandırma:** «Tüm Altyapı Analizi» → **Doğal Dil Asistanı** (EN: Natural Language Assistant).
- **Açık tema:** rapor ekranlarında beyaz zeminde okunmayan metinler (`text-yellow-400`, opaklıklı amber/mor/mavi/kırmızı) ve eksik hover/zemin renkleri için override eklendi.
- **Sentetik kapsam:** eski `/executive` sayfasında hypervisor_id'si boş ZZ-FAKE olayları `external_key` ile dışlanır; `zz-hwdemo-*` sunucuları sentetik sayılır (Yönetici raporları dışlar; kayıt silinmedi).
- Rapor markdown'ında KPI «2 — /2» biçimi «2 /2» olarak düzeltildi.
- **Düzeltme (yönetici paketi kilidi):** `exec_snapshot.produce_bundle` advisory kilidini oturum bağlantısında alıyor, `rollback()` sonrası kilit başka havuz bağlantısında bırakılmaya çalışılıp başarısız oluyor ve kilit havuzda sızıyordu (sonraki üretimler sessizce `None`; tam takımda `test_produce_writes_locked_row` sıra bağımlı hatası). Kilit artık özel bağlantıda alınıp bırakılıyor; iki regresyon testi eklendi.
- **Rapor içeriği EN:** OpenShift ve Yönetici hazır raporlarının başlık, KPI etiketi, sütun, durum sözcüğü, not, öneri, kapsam-dışı nedeni ve yöntem metni arayüz dili İngilizce iken İngilizce görünür (Hazır Raporlar sayfası, markdown, sohbet özeti). Kayıt Türkçe kalır; çeviri çıktı sınırında (`services/report_i18n.py`, API `lang`). Varlık/küme/sunucu adları çevrilmez. Sohbette cevap dili mesajdan seçilir. `test_report_i18n.py` iki motordaki her metnin çevirisini zorunlu kılar.

### Giriş ekranı yenilendi + gerçek OIDC SSO
- **Yeni giriş ekranı:** iki temaya (koyu/açık) uyumlu iki bölmeli tasarım; ainew merkezli 6 bileşenli (vSphere, OpenShift, Windows, Exadata, OLVM, Linux) animasyonlu hub; dil seçici + tema anahtarı; dar ekran uyumlu. «Parolamı unuttum» ve «Beni hatırla» YOK (parolayı admin sıfırlar). AD açıksa «Active Directory / Yerel hesap» sekmeleri görünür (yalnız ipucu; backend yerel/AD'yi otomatik ayırır). MFA kayıt/doğrulama adımları aynen korundu.
- **Kullanıcı tarafından değiştirilebilir marka:** Ayarlar → Kurumsal Kimlik: uygulama adı, logo, şirket adı, giriş alt başlığı, alt bilgi metni (boşsa «Datatem Teknoloji» varsayılanı; «Varsayılana dön»). Varsayılan uygulama adı artık `ainew`.
- **SSO artık gerçekten çalışıyor (OIDC Authorization Code + PKCE S256):** «Kurumsal SSO ile devam et» düğmesi yalnız SSO tam yapılandırılmışsa görünür; yerel giriş her zaman açık kalır (acil durum). state/nonce/PKCE Redis'te (Redis yoksa SSO kapalı kalır), id_token imzası JWKS ile doğrulanır (RS/ES/PS; HS256/none reddedilir), grup→rol eşlemesi tam eşleşme (alt dize yok), eşleşen grup yoksa giriş reddedilir; yerel parolalı hesapla ad çakışması reddedilir; token URL'de taşınmaz (60 sn tek kullanımlık kod → `POST /auth/sso/exchange`); SSO girişinde MFA'yı kimlik sağlayıcı yapar. Ayarlar → Güvenlik → Kimlik'te yeni SSO formu ve «Yapılandırmayı test et» (discovery + JWKS). Kimlik sağlayıcıda redirect URI: `https://<ainew>/api/v1/auth/sso/callback`.
- Açık temada yan menü kaydırma çubuğunun siyah kalması düzeltildi (Tailwind 4 `scrollbar-*` sınıfları temaya duyarlı kuralları eziyordu; sınıflar kaldırıldı).
- Dropt'a dokunulmadı. Test: 33 yeni backend testi + gerçek tarayıcı (Playwright) e2e'si — 62/62 (`scripts/e2e_login/`: sahte OIDC IdP + senaryo; her iki tema, dar ekran, yerel giriş, kilitlenme, MFA, SSO rolleri/ret/replay, marka düzenleme). Gerçek AD / gerçek IdP (Keycloak, Entra) ile doğrulama kullanıcıdadır.

### Bağımlılık yükseltmesi (tüm bileşenler en üst sürüm)
- **Backend:** Python 3.11→3.14; FastAPI 0.104→0.162, Starlette 0.27→1.10, Pydantic 2.5→2.14, SQLAlchemy 2.0→2.1, NumPy 2, Pandas 3, Celery 5.6, LangGraph 1.x, LangChain-core 1.x, ChromaDB 1.x, Paramiko 5, PyPDF 6, Ansible 14 vb. `redis-py` kombu uyumu için 6.4'te tutuldu (kombu `<6.5`).
- **ChromaDB kaldırıldı:** düzeltmesi olmayan 5 açık taşıyordu ve yalnız eski veriyi pgvector'a taşımak için kullanılıyordu. Paket yoksa taşıma atlanır; pgvector boşken eski `chroma.sqlite3` varsa UYARI loglanır, veri silinmez (`rag_chroma_migrate.py`).
- **Güvenlik:** `python-jose` (+`ecdsa`, `rsa`) → **PyJWT** (mevcut HS256 oturum token'ları geçerli kalır); `setuptools` güncellendi (torch CPU index'i eski sürüm sunuyordu); `bcrypt` 5 için Dropt'ta 72 bayt kırpma açıkça yapılır. Backend `pip-audit`: yalnız ChromaDB (düzeltmesi yok); Dropt: 0; frontend `npm audit`: 0.
- **SQLAlchemy 2.1:** `postgresql://` varsayılan sürücüsü psycopg (v3)'e değişti; `app/__init__.py` psycopg2'yi AÇIKÇA korur (mevcut `.env` dosyaları değişmeden çalışır).
- **Frontend:** React 18→19, Vite 5→8, Tailwind 3→4 (`@layer base` düzeltmesi, sınıf adı geçişleri), react-router 6→7, Recharts 2→3, Mermaid 12, jsPDF 4, TanStack Table 9 (legacy katman), TypeScript 6.0, Vitest 5, Node 20→26, nginx 1.31; `xlsx` SheetJS 0.20.3'e; kullanılmayan ESLint paketleri kaldırıldı.
- **Dropt:** Python 3.12→3.14, tüm bağımlılıklar güncel.
- **Paket (offline):** Pushgateway v1.11.0→v1.11.4; Prometheus v2.55.1→v3.15.1 (dev ortam zaten 3.13 ile aynı yapılandırmada çalışıyordu; `promtool check config` geçti; TSDB biçimi uyumlu, gerekirse 2.55.x'e geri dönüş desteklenir). TimescaleDB/PostgreSQL/Redis major sürümleri veri etkilediği için DEĞİŞTİRİLMEDİ.
- Doğrulama: backend pytest 4557 geçti / 10 başarısız (yükseltmeden ÖNCE de aynı 10); frontend tsc 0 hata, Vitest 280/280; OpenAPI 802 işlem önce/sonra birebir aynı.

### Gerileme taraması (Adım 20; ayrıntı `docs/chat-quality/plan.md`)
- **Sanallaştırma turu çökmesi giderildi:** canlı akış sonrası iş parçacığı ile orkestratör aynı DB oturumunu eşzamanlı kullanıyordu; artık kendi oturumu var. Doğrulayıcı engeli de turu çökertiyordu (`note_path` anahtar çakışması) — düzeltildi.
- **Linux sohbet:** «mtv-testserver …» gibi adlar artık hostname/IP listesi sanılmıyor; «X sunucusunun uptime/disk değeri nedir?» canlı veriyle cevaplanıyor.
- **OpenShift/Sanallaştırma:** hypervisor verilmeyen KubeVirt VM sorusu tüm kaynakları sorguluyor (sahte/ulaşılamayan kaynak «0 VM» yapmıyor); çok cluster'lı pod listesi node ayrıntısını da veriyor; grafik cevabında iç tablo adı gösterilmiyor.
- İnsan testi İH20 kullanıcıdadır; Adım 20 «Kapandı» değildir.

### Grafik gelmiyor + yazılıp silinen cevap (Adım 19; ayrıntı `docs/chat-quality/plan.md`)
- **Kök neden bulundu:** model cevaplarında VM/host adlarındaki `-` yerine kırılmaz tire (U+2011) yazıyordu; kullanıcı adı kopyalayıp «grafiğini getir» deyince ad eşleşmiyor, hızlı grafik yolu atlanıp ~2 dk'lık LLM cevabı geliyordu. Artık kullanıcı girdisi (Yönetici, Linux/OpenShift, Windows, Sanallaştırma) ve model çıktısı normal tireye çevriliyor; aynı soru ~2 sn'de 2 grafik veriyor.
- **Sanallaştırma kanıt guard'ı:** reddedilen cevap silinirken artık «Cevap araç kanıtıyla uyuşmadı, yeniden üretiliyor…» gösteriliyor ve yeniden üretim canlı akıyor (önceden ~23 sn sessiz bekleme); ret nedeni ve ilk cevap başı loga yazılıyor.
- İnsan testi İH19 kullanıcıdadır; Adım 19 «Kapandı» değildir.

### Sohbet alanı + genel ölçek (Adım 18; ayrıntı `docs/chat-quality/plan.md`)
- **Genel ölçek %90:** tüm arayüz (login dahil) rem tabanlı olduğundan tek satırla (`index.css` → `html { font-size: 90% }`) küçüldü; geri almak için satırı silmek yeterli.
- **Sohbet alanı büyüdü (5 asistan ekranı):** üst bantlar sıkılaştırıldı (hub başlığı + sekmeler tek satır, sohbet çubuğu/istatistik şeridi/banner inceltildi), geçmiş çubuğu 256→224 px, giriş alanı kompakt, mesaj sütunu daha geniş. 1366×768'de mesaj alanı +%26…+%47.
- **Sohbet yazısı varsayılan 12 px**; «Yazı» seçici 11/12/13/15.
- **Hata düzeltmesi:** DEMO bandı açıkken sohbetin alt kısmı (giriş kutusu) kırpılabiliyordu; sohbet kökü sabit yükseklik yerine `flex-1` oldu.
- İnsan testi İH18 kullanıcıdadır; Adım 18 «Kapandı» değildir.

### Canlı akış kapsamı (Adım 17; ayrıntı `docs/chat-quality/plan.md`)
- **Windows ve Linux/OpenShift sohbeti:** araç döngüsünün son turu canlı akar (tek geçiş, ikinci üretim yok); kesik/hatalı/sızıntılı turda ikinci üretim `think` düşük + düşünme iletimiyle çalışır.
- **Sanallaştırma sohbeti:** LLM cevabı artık sonda topluca değil token token akar; araç turlarının düşünmesi/araç adımları görünür; kanıt guard'ı reddederse ekran geri alınıp doğru cevap yazılır.
- **«Düşünme süreci» paneli** Linux/OpenShift, Windows ve Sanallaştırma ekranlarında (rol kapılı: `chat_stream_thinking`, vars. yalnız admin). Ortak yardımcı `services/chat_live_final.py`; tek anahtar `chat_unified_stream_final`.
- İnsan testi İH17 kullanıcıdadır; Adım 17 «Kapandı» değildir.

### Sohbet yazı boyutu (Adım 16; ayrıntı `docs/chat-quality/plan.md`)
- Tüm NL sohbet ekranlarında (Yönetici, Linux, Windows, Sanallaştırma, OpenShift) varsayılan yazı 14 → **13 px**; başlıklar gövdenin ≤ 1,25 katı (eskiden h2 ≈ 20 px), tablo/kod gövdeye oranlı.
- Model seçicinin yanında **«Yazı: A A A A»** seçici (12/13/14/16 px, tarayıcıda kalıcı). Diğer sayfalar etkilenmez.
- Sayfa bazlı akış ölçümü plan.md'de (düşünme paneli/tek geçiş yalnız Yönetici'de; Sanallaştırma LLM cevabı akmıyor).

### Cevap bütünlüğü ve kapsam (Adım 15; ayrıntı `docs/chat-quality/plan.md`)
- **Kanıt guard'ı:** kapsamlı (uzun + kanıt sayılarını kullanan) cevap, içinde «veri bulunamadı» satırı ya da bazı host adlarının eksikliği yüzünden artık çöpe atılmıyordu — eskiden ~1 dk sessiz yeniden üretim + kuru tablo oluyordu. Tetikleyen koşul adı loglanır (`no_data`/`invented_ip`/`no_names`/`no_anchor`); `ha` alt-dize hatası giderildi.
- **Özet fallback'i:** sayaç sözlükleri (örn. job başına hata) sıralı tablo olur; başlık sadeleşti.
- **«Genel durum / tüm altyapı» soruları** vCenter+Linux yerine vCenter+Linux+Windows+OpenShift verisi toplar (yalnız veri toplama; varsayılan kısa cevap kuralı değişmedi).

### Canlı akış (Adım 14; Atlas incelemesi, ayrıntı `docs/chat-quality/plan.md`)
- **Tek geçiş:** birleşik sohbette araçlı son tur doğrudan kullanıcıya akar; ikinci üretim çağrısı kalktı (`chat_unified_stream_final`). Kesik/hatalı/nudge'lı turlarda otomatik eski yola düşer.
- **«Düşünme süreci»:** modelin akıl yürütmesi araç aşamasında canlı gösterilir (`chat_stream_thinking`: off/admin/all, vars. admin); cevap/kayıt/önbelleğe karışmaz.
- **Aralıklı gönderim:** hazır cevaplar (envanter, netleştirme, önbellek…) tek patlama yerine ≤ ~1,2 sn'ye yayılır.
- Orkestratör: `replace_answer` kayıtlı kısmi metni de sıfırlar (çift metin birikmesi giderildi).
- **Akış neden görünmüyordu (kök neden düzeltildi):** `GZipMiddleware` SSE yanıtını tamponluyordu (tarayıcı gzip ister, `curl` istemez); artık `text/event-stream` sıkıştırılmaz (`core/gzip_sse.py`). Kesik/sızıntılı canlı cevapta tek hızlı yeniden deneme, ilerleme bekçisi yeniden açılır, ikinci üretimde de düşünme gösterilir (`chat_final_think`).
- İnsan testi İH14 kullanıcıdadır; Adım 14 «Kapandı» değildir.

### Eşzamanlılık ve kapasite sertleştirmesi (Adım 13; ayrıntı `docs/chat-quality/plan.md`)
- **Sohbet AI kapısı v2 (`ai_gate`):** sayaç + liste yerine lease ZSET (çöken turun slotu 240 sn'de kendiliğinden düşer, çift release zararsız); ölü bekleyen baştaki sırayı tıkayamaz; bekleme `asyncio.sleep` (iş parçacığı tutmaz — `chat_io` havuzu dolmaz).
- **Kullanıcı deneyimi:** kullanıcı başına eşzamanlı tur sınırı (`chat_user_max_active_turns`, vars. 2) ve kuyruk üst sınırı (`chat_gate_max_queue`, vars. 20) → tur oluşturulmadan HTTP 429 + Türkçe mesaj; kısa/kavramsal soru için hızlı şerit (`chat_gate_fast_bonus_sec`); tek bekleme bütçesi (`chat_gate_max_wait_sec`) + dostça zaman aşımı; kuyruk olayında sıra + tahmini süre; aynı oturumda turlar sırayla (`chat_session_serial_enabled`).
- **Ölçüm:** `GET /metrics/chat-gate` (Prometheus) ve `scripts/chat_bench/concurrency_eval.py` (N eşzamanlı soru).
- **Linux sunucular:** çekmecede «Düzenle» (ad/IP/donanım özellikleri, SSH kimliği, Donanım/BMC hesabı — yalnız Admin); `PUT /servers/{id}` operatör+, `GET /hw/bmc/server-account/{id}`.
- **LLM semafor lease:** 900 sn → 90 sn + canlı sahip yenilemesi (restart sonrası ölü sahip slotu ≤ 90 sn tutar). Ollama paralelliği ile `llm_max_concurrent` eşit tutulmalı (dev: 3).
- İnsan testi İH13 kullanıcıdadır; Adım 13 «Kapandı» değildir.

## [1.0.9.42] - 2026-10-26

### Sohbet kalite programı (Adım 7–11; ayrıntı `docs/chat-quality/plan.md`)
- **Adım 7 — veriye dayalılık doğrulayıcısı:** uydurma varlık/komut/iç terim sınıfları `chat_grounding_mode` (off/shadow/enforce) ile engellenir; yanlış öncül düzeltmeleri.
- **Adım 8/8R — dürüstlük ve RAG:** modül filtreli RAG araması, alaka eşiği (`rag_min_relevance_*`), lexical süre sınırı (`rag_lexical_timeout_ms`), seed düzeltmesi; incidents saklama (hazır, kapalı).
- **Adım 9 — cevap önbelleği:** yalnız kavramsal + tam eşleşme; anahtar `platform:ids_hash:rbac_sig`, TTL 24 sa (`chat_cache_*`); `/chat/feedback` kimlik ister, 👎 girdiyi düşürür; `done.from_cache`.
- **Adım 10 — ilerleme olayları:** ilk token öncesi `progress` SSE olayları (aşama ≤ 60, kalp atışı ≤ 720, `chat_progress_*`); 4 sohbet sayfasında canlı durum metni. Veri/argüman/sonuç içermez.
- **Adım 11 — event döngüsü koruması:** sohbet için ayrı 96 işçili `chat_io` havuzu (`core/chat_executor.py`); LLM/SQL/Redis/HTTP çağrıları döngüden çıkarıldı; `create_turn(loop=…)`; olay toplayıcılarında O(N·M) ORM taraması `services/event_dedupe.py` ile SQL'e taşındı (vCenter/oVirt/OpenShift-Virt/virt_log); tanı: `[LoopWatchdog]` (`LOOP_WATCHDOG=0` kapatır) ve `[SSELag]`. 3 paralel sohbette en uzun sessizlik 11,4 → 5,98 sn.
- 32 yeni Gelişmiş ayar (`docs/deployment.md` tablosu); AI mimari belgeleri (TR/EN) ve `.cursor/rules` güncellendi.
- İnsan testleri (İH6–İH10) kullanıcıdadır; ilgili adımlar «Kapandı» değildir.

### Sanallaştırma — v42 eksikleri
- E2: What-if, toplu yerleşim, host-arızası (N+1) ve "VM nereye" tek yerleşim çekirdeğini (`capacity.placement.place_vms`) kullanır; aynı VM için aynı SIĞAR/SIĞMAZ kararı.
- E3: vCenter "ayrılmış failover host" politikası: ayrılmış host'lar yerleşime kapalı, kapasiteleri rezerv; host listesi okunamazsa 1 host varsayımı etiketli. Slot politikasında (Host failures tolerated) boş slot yoksa VM sığmaz (`ha_slots`); 1 slot/VM varsayımı ve slot sayısının son okumadan geldiği notla gösterilir.
- E6: OpenShift Virt vCPU:çekirdek oranı VMI okumasından / HCO'dan (`cpuAllocationRatio`) alınır; okunamazsa varsayım etiketli.
- E7: Kapasite › Eşikler'de cluster/instance override'ları listelenir (PolicyOverrides).
- E9: Sohbet PDF dışa aktarımına yöntem notları ve kanıt eklendi.
- Önce/sonra ölçümü (v1.0.9.41 ↔ main, aynı DB): cluster sayıları, N+1 tablosu, runway ve "nereye sığar/en fazla N" kararlarında 0 fark; tek fark E6 `cpu_request` etiketi. Eşit boyutlu VM'lerde yerleşim sırası doğal sıraya döndürüldü. E3 kuralları (ayrılmış host, HA slot) bu ortamda HA politikalı vCenter olmadığı için yalnız testle doğrulandı. Rapor: `docs/release/kapasite-once-sonra-20261013.md`.

### Sanallaştırma — hedef ortam analizi düzeltmeleri
- **Envanter eşleştirme:** link-local/loopback/multicast IP'ler (169.254.x vb.) ve başka bir VM'e (`hypervisor_vm_id` dolu) bağlı kayıtlar IP/ad yedeğiyle devralınmaz; aynı IP'yi paylaşan VM'ler artık tek `servers` kaydında birleşmez (aynı hypervisor + aynı ad + aynı IP ise VM kimliği biçim değişimi — KubeVirt UID → `ns/ad` — hâlâ devralınır).
- **Datastore kuralı (`vmw.datastore.accessible`):** önem ve kanıt bağlama göre ayrılır — hiçbir host'a bağlı olmayan (boş) datastore `low`, NFS ve tüm bağlı host'larda erişilemiyor `medium`, diğerleri `critical`. Kanıta mount/host sayısı, tür, kapasite, boş yüzde ve senaryo eklendi.
- **Uplink kuralı:** uplink'siz standart switch (dış bağlantısız/izole) yedeksizlik bulgusu değil, kanıtta `isolated_switches`; detay `ad (N uplink)`.
- **VM listesi ve Monitoring araması** sunucu tarafında (`q`, `hypervisor_id`, debounce 400 ms) çalışır; sayfalama dışındaki VM'ler de bulunur.
- **Depolama göstergesi:** host metriklerindeki paylaşımlı datastore çift sayımı kaldırıldı; `/hypervisors/host-metrics` benzersiz datastore'lardan `datastore_summary` döner.
- **Kapasite sayfası performansı:** `/virt-insights/capacity` ve host-arızası matrisi kısa ömürlü (120 sn) Redis/bellek önbelleğinde; eşik/override değişince ve envanter/karar katmanı turu bitince geçersiz kılınır.
- **Baseline kaldırma:** `DELETE /virt-insights/baseline` (operatör; kapsam zorunlu) + Değişiklikler sekmesinde "Baseline'ı kaldır" (snapshot geçmişi korunur); değişiklik satırları `has_baseline` döner.
- **N+1 raporu etiketleri/birimleri:** durum kodları okunur etiketlere (Yeterli/Sınırda/Yetersiz…), sütun başlıkları birim ve tooltip ile.
- **Uyum skoru şeffaflığı:** skor = Başarılı/(Başarılı+Başarısız); hücrede başarılı/ölçülen sayısı ve tooltip.
- **Centrify:** sütun migrasyonu her sütunu ayrı işlemde çalıştırır; kısmi başarısızlıkta "tamamlandı" yerine uyarı, DB erişilemezse "atlandı" loglanır.

### Sanallaştırma — ölçek (1000 sahte VM) testinden çıkan düzeltmeler
- **Anomali taraması:** `detect_all_anomalies` naive `utcnow()` ile tz-aware `metrics.timestamp` karşılaştırıyordu (`TypeError`); her turda hata dönüyordu, artık tz-aware.
- **Senaryo hesapları (`move`, `simulate`, `host-failure`, `bulk-placement`, `reclaim-sim`, iç içe senaryo):** `build_capacity(with_reclaim=False)` ile reclaim toplamı/aksiyonlar hesaplanmaz (bu uçlar kullanmıyor); `move` yalnız kaynak cluster'ı hesaplar. 1000 VM'de: bulk 3,4 → 0,3 sn, move 4,0 → 0,6 sn, reclaim-sim 1,1 → 0,3 sn, host-failure 1,0 → 0,3 sn.
- **Envanter sync kayıt fazı:** `learned_facts` tek SELECT ile toplu okunur (eskiden fact başına), VM başına commit yerine 10 VM'de bir + tur sonunda commit (fact yazımı SAVEPOINT içinde), bulunan kayıt tekrar sorgulanmaz. 1000 VM: 33 sn → 16 sn.
- **Paralel hypervisor sync:** `sync_all_hypervisors` birden fazla hypervisor'u (en çok 4) kendi DB oturumunda paralel çalıştırır; ulaşılamayan biri (10 sn zaman aşımı) turu geciktirmez.
- **`learned_facts` yazımı:** değişmeyen fact'in son-onay damgası en çok saatte bir güncellenir (`FACT_CONFIRM_MIN_INTERVAL`); değer/kaynak değişirse hemen yazılır. Sync kayıt fazı 16 sn → 7 sn (kararlı durumda ~4,6 ms/VM; başlangıç 33 sn). `times_confirmed` artık "sync sayısı" değil "onaylanan saat dilimi sayısı"dır.
- **Datastore fact'leri (sohbet isteği yolunda):** `store_live_datastore_facts` fact başına SELECT/UPDATE yerine parça başına tek sorgu + aynı sıklık sınırı; 1000 VM'de datastore soru sonrası gecikme 6,8–8,6 sn → ~0,2 sn.
- **Kapasite önbelleği:** TTL 600 sn; ESX/OLVM/OCP host metrik turu, envanter ve karar katmanı turu sonunda önbellek düşürülüp varsayılan `/capacity` yanıtı hemen yeniden hesaplanır (`invalidate_and_prewarm`); ilk kullanıcı isteği önbellekten gelir (0,07 sn). `reclaim_rollup_by_cluster` `vm_allocations`'ı tek kez yükler (soğuk hesap 1,74 → 0,87 sn).
- **`/virt-insights/vms`:** önce sıralanıp sonra kesilir (eskiden envanter sırasındaki ilk N kayıt alınıyordu); `total` döner.
- **`/hypervisors/host-metrics`:** envanter yedeğinden gelen `datastore_summary.count` doldurulur (OLVM).

### Sanallaştırma / AIOps — takip düzeltmeleri
- **OLVM `list_vms` 500:** engine `follow=host,cluster,nics,guest_operating_system` isteğine HTTP 500 dönüyordu; yedek yalnız 400/404'te çalışıyordu → VM sync 11 gün boyunca başarısızdı. Artık herhangi bir `OVirtError`'da tam follow → `follow=nics` → düz liste zinciri denenir; eksik alanlar VM başına detay çağrısıyla tamamlanır. Hepsi başarısız olursa hata fırlatılır (sessiz boş liste yok, prune çalışmaz).
- **Sync bayatlığı görünür:** periyodik tur sonucu (`sync_all_hypervisors`) artık `meta_data.sync_job` + `hypervisors.status` alanına yazılır (hata → `ERROR`, `last_error_at`; başarı → `ONLINE`, `last_success_at`); elle başlatılmış çalışan tarama ezilmez. Yeni bulgu `inv.sync.stale` (VMware/OLVM/OCP Virt, `platform` varlığı): son başarılı sync eşikten eskiyse FAIL (eşik = max(6 sa, 3 × `inventory_sync_interval_minutes`); ≥72 sa → yüksek). Sahte envanter (`fake_seed`) sync/toplama/OCP metrik/event turlarında atlanır.
- **Incident gürültüsü:** OpenShift `Pod/<ad>-<rastgele>` olayları aynı kök neden için tek incident'a gruplanır (`normalize_k8s_object`; StatefulSet `-0` korunur). `auto_*` kaynaklı, sahiplenilmemiş, `open` incident'lar 24 saattir güncellenmediyse `resolved` olur (silme yok; `resolution` yazılır). Otomatik RCA yalnız son 24 saatte açılmış incident'lara çalışır.
- **EN arayüz:** datastore bulgusunun senaryoya özel önerisi (unmount / NFS erişilemiyor) İngilizce karşılığıyla gösterilir.
- **VM kartı:** vCPU/RAM 0 veya boşken "0 vCPU • 0 GB" yerine yalnız değeri olan alan (yoksa "—") gösterilir.
- **Test aracı:** `scripts/fake_virt_seed.py seed-ocp 500` / `cleanup-ocp` / `cleanup-all` — karışık OS'lu (Windows, Ubuntu, RHEL, CentOS, Rocky, Alma, Oracle, Debian, SLES, Fedora, guest-agent'sız) sahte OpenShift Virt envanteri. Hem Sanallaştırma (`ZZ-FAKE-OpenShift` hypervisor) hem OpenShift modülü (`ZZ-FAKE-OCP` cluster: node, proje, workload, `ocp_resource_metrics`) tarafında görünür; cluster overview ve KubeVirt VM listesi DB'den üretilir (`services/openshift/fake_cluster.py`). Sahte kayıtlar (`meta_data.fake_seed`) gerçek sync/event/monitoring/bulgu/ESX turlarında atlanır; metrikleri `services/fake_refresh.py` her ESX metrik turunda tazeler (pencereler dolup envanter "veri yok" olmaz). Bilinen sınır: OCP Insights (bulgu/kapasite/reclaim), topology, YAML, konsol ve güç/klon işlemleri sahte cluster'da çalışmaz (canlı API gerekir).

### Güvenlik ve paketleme
- Centrify DEMO veri uçları (`POST/DELETE /centrify-mgmt/demo/seed`) varsayılan KAPALI (`CENTRIFY_DEMO_ENABLED=true` yalnız geliştirme/demo) ve yalnız `admin` rolüne açık (RBAC kuralı + uç bağımlılığı). Önceden operatör rolü yeterliydi ve `DELETE` Centrify tablolarını boşaltıyordu.
- Kurulum kılavuzuna (`docs/INSTALL_RHEL.md`) "kurulumdan sonra varsayılan yönetici parolasını ve `compose.env`/`.env` varsayılanlarını değiştirin" uyarısı eklendi (yalnız doküman).
- `scripts/release.sh`: `backend/VERSION` artık kök `VERSION` ile birlikte yazılır ve commit'lenir.

## [1.0.9.41] - 2026-10-13

### Sanallaştırma — yedek (Veeam), kapasite ve yöntem şeffaflığı
- Kapasite Planlama → Eşikler: her eşiğin yanına tıklanabilir (i) yardım simgesi eklendi; kısa ve net açıklama + izinli aralık/varsayılan gösterilir.
- Dilim F.0 (DEMO kapısı): DEMO yedek sağlayıcısı varsayılan KAPALI (`BACKUP_DEMO_ENABLED=true` yalnız dev); gerçek sağlayıcı varken yok sayılır (karışmaz); `backup` yeteneğini açmaz; bulguları `platform=backup_demo` altında tutulup denetim kanıtı/rapor/skorlardan dışlanır; ISO A.8.13 kanıtı demo veriden üretilmez; açıkken her ekranda “DEMO VERİ — gerçek Veeam değil” bandı. Testler izole geçici Postgres DB'de (koşullu skip yok). Demo modunda `virt_backup_status`/`virt_rpo_compliance` “DEMO veri” etiketiyle açık; bayrak kapanınca çözülen demo bulguları `resolved_reason=demo_disabled` alır ve kapanan bulgu/çözüm süresi metriklerine girmez (`closure_metrics`).
- Dilim T (yöntem şeffaflığı): her bulgu/kart/metrik için sabit sınıf rozeti (Veri, Hesap, Tahmin, Kural, Eşleştirme, AI) + (i); içerik tek kaynak `services/method_registry.py` → `GET /api/v1/methods`; "Nasıl hesaplıyoruz?" sayfası (`/methods`, Ayarlar › Hakkında'dan da erişilir); AI metinleri `AiBlock` ile ayrı gösterilir; sohbet yanıtlarında "Kaynak: <tool> (<sınıf>), <saat>" satırı ve "AI genel bilgisi — ortamınızdan alınmadı" işareti; sistem prompt'unda SAYI KURALI; kayıtsız check/tool/bileşen id'si CI'yi kırar. Kapasite/Geri Kazanım/Yedek/Değişiklik/Sağlık/OpenShift kapasite/İzleme ekranlarına uygulandı. Kapasite yanıtına `as_of`, geri kazanıma `computed_at` eklendi.
- Dilim B (yedek çerçevesi): `not_applicable` bulgu durumu (skor/payda dışı), capability registry (`GET /capabilities`), sohbet tool `requires_capability` filtresi, `integration_instances`+`bk_*` tabloları, `BackupProvider` protokolü. Veeam'siz ortamda Yedek UI/tool yok.
- Dilim C/D/E (yedek): Veeam VBR salt-okunur REST adaptörü + DEMO/fixture sağlayıcı (`/integrations/backup`), Sanallaştırma › Yedek & DR (RPO, işler, depolar, eşleşmeyen nesneler, hedef politikalar, ISO A.8.13 kanıtı, depo what-if, yedek hatası↔drift korelasyonu), sohbet tool `virt_backup_status`/`virt_rpo_compliance` (yalnız backup capability varken), yedek bulguları (`bk.*`), incident timeline'a yedek oturumları. Madde 14 snapshot_remove ön kontrol, N+1 tek-host NA, Değişiklikler baseline mesajı, besleme yaşı ve konsolidasyon bulguları. Doğrulanmamış Veeam alanları (değişmezlik/şifreleme/CBT) kodlanmadı.
- Dilim C (tamamlama): kapasite eşikleri artık `capacity_policies` tablosunda (Kapasite Planlama › Eşikler sekmesi, `GET/PUT /virt-insights/capacity/policy`, yalnız admin yazar); what-if'te "mevcut VM'i klonla" (aranabilir VM seçici); `hw.host.sensor_repeat` (30 günde ≥3 ayrı günde sensör alarmı); Yedek & DR'de kapalı VM'ler "Korumasız (kapalı)" olarak ayrışır; DEMO rozet kontrastı.
- Geri Kazanım: "aşırı boyutlu" tespiti dinamik (30 günlük p95 CPU → önerilen vCPU, asgari %25 küçülme, güven düzeyi; `rs_*` eşikleri Kapasite › Eşikler'den ayarlanır); sahipsiz disk satırlarına kanıt/sınıf (VM'den çıkarılmış / VM silinmiş / API doğruladı / doğrula). Sol menü: Entegrasyonlar › Veeam (UC4 Automic altında); Envanter Merkezi Veeam kartı aktif sağlayıcı sayısını gösterir.
- Kapasite What-if v2 (H, H.0): ortak senaryo motoru (vCenter/OLVM/OpenShift), cluster/host/resource pool hiyerarşisi ve kapsam, **Host devre dışı kalırsa (N+1)** matrisi (riske göre sıralı, simülasyon notu, Bulgular bağlantıları, `cap.sim.host_failure_matrix`), runway (Theil–Sen, ≥14 gün), geri kazanım simülasyonu, toplu yerleşim; kapsam filtresi çiplerle (opsiyonel); What-if varsayımlarında affinity/DRS/rezervasyon/VLAN kontrol edilmediği ve OpenShift virt-launcher ek belleğinin 'doküman varsayımı' olduğu belirtilir.
- Referans paketleri (G): `ref.feed.stale`, resmi kaynak allowlist'i, üretim tarihi + SHA-256, paket yokluğunda bulgular korunur; dashboard kartında (i) ve doğrulanmış resmi kaynak bağlantıları.
- Yöntem şeffaflığı (T2): Linux/Windows/Exadata rozetleri, AWR/log RCA AiBlock, sohbet kaynak satırı, rapor/PDF Yöntem notları; Yöntemler sayfasında kolon sıralama.
- Bulgular: donanım sensör kanıtı, bağlam bloğu (Etki → N+1 satırına bağlantı), AI yorumu (`finding_ai_*`).
- Yedek: Veeam revizyon seçiminde 'alanları doğrulanmadı' uyarısı (12.x ve 1.3-rev2); harici LLM açıkken Yedekleme sağlayıcısı sayfasında uyarı — uzak LLM'e yalnız VM/iş/depo adları ve durum/RPO özeti gider (`services/backup/egress.py`). `requires_capability` yoksa bulgu üretilmez (ölü `check_capabilities_met` kaldırıldı); bulgu sonuçları `RESULT_*` sabitleriyle (AST testi).
- `.env.example`: `VCENTER_TOPOLOGY_COLLECT` (varsayılan kapalı) ve `CAPACITY_ENGINE` notu. Dokümanlar (TR/EN): Veeam, Yedek & DR, N+1, runway, geri kazanım, toplu yerleşim; yedek kapsamı '13 madde (Madde 6 — ServiceNow/Teams hariç)'.

### Ortak LLM katmanı, RAG ve zaman
- Ortak LLM gateway/transport/bütçe/zamanlayıcı katmanı, Ollama runtime algılama, sohbet metrikleri, gelişmiş LLM ayarları.
- RAG: hibrit embedding, pgvector store değişiklikleri, migrasyon betikleri; zaman: `timeutil` (UTC/ISO), metrik zaman dilimi kayması düzeltmesi.

### Automic (UC4)
- İzleme, collector, salt okunur asistan, entegrasyon sihirbazı, dokümanlar ve testler (`automic` modülü).

### Test altyapısı
- Canlı DB'ye giden testler izole geçici DB'ye taşındı (`capacity_policy`, `reclaim_dynamic`, prom catalogs, `rag_pgvector`); tüm backend paketi canlı DB erişilemezken geçer.

### Bilinen sınırlamalar
- İlk kurulumun tek bir müşteride **canary** olarak yapılması önerilir.
- Tek yerleşim mantığı (E2: /placement, toplu yerleşim, What-if ve N+1 ayrı yolları), HA rezerv politikaları (E3: ayrılmış failover host / slot) ve HyperConverged `vmiCPUAllocationRatio` okuması (E6) henüz yok.
- Cluster bazında eşik override arayüzü (E7) ve sohbet PDF 'Yöntem notları' (E9) sonraki sürümde.
- Gerçek VBR fixture'ı (B11) ve `VCENTER_TOPOLOGY_COLLECT` ölçümü (E8) canlı ortam gerektirdiğinden yapılmadı; F9 kalanları (senaryo kaydetme, donanım ekleme/emekliye ayırma, overcommit değişikliği, lisans etkisi, site/DR failover), gerçek VLAN/portgroup kontrolü, NUMA toplama ve OLVM data center ↔ storage domain eşlemesi yok.
- Automic: 57 soruluk benchmark (N=2/N=5) bu sürümün son kodunda koşulmadı; açık işler k2, j5. Canlı sohbet/Automic smoke testi koşulmadı (yönetici parolası ortamda varsayılandan farklı).
- Testlerde `ensure_schema` kaynaklı kalıntı canlı-DB riski tam elenmedi.

## [1.0.9.40] - 2026-10-06

### Ana dashboard herkese açık, Yönetici raporu, OpenShift yetki düzeltmeleri
- **Dashboard** (`/dashboard`; admin'de "Modüllerim" paneli gösterilmez) artık her kimliği doğrulanmış kullanıcıya açık ve açılış sayfası; içerik kullanıcının modüllerine göre süzülür, "Modüllerim" paneli erişilebilir alanlara kısayol verir. Linux envanteri yalnız `linux` modülü olan kullanıcıda sorgulanır.
- **Yönetici › Raporlar** (`/executive/reports`, `GET /ops/executive-report`): Linux, Windows, Sanallaştırma, OpenShift ve Exadata için tek sayfalık deterministik rapor (genel durum, ortam tablosu, öne çıkan bulgular, açık olaylar, öneriler); Markdown indirme ve yazdır/PDF. Yalnız `executive` modülü / admin.
- **OpenShift › Planlama ve Denetim** (Kapasite, Geri Kazanım, Sağlık, Değişiklikler) yalnız admin: menü, rota ve ilgili `/ocp-insights/*` uçları.
- **Level 1 dashboard bölümü** (ana dashboard'ın en altında, `level1` modülü olanlara; veri `GET /level1/dashboard`): uygulamaya bağlı yalnız Level 1 kullanıcıları (çevrimiçi/son 24 saat; diğer modül kullanıcıları listelenmez), son işlem yapılan sunucular, son işlemler, KPI'lar (24s işlem, başarı oranı, çalışan/hatalı iş, hazır sunucu), 7 günlük eğilim, en çok kullanılan kullanıcı/işlem türü, dikkat gerektirenler (hatalı işler, ulaşılamayan sunucular). Dropt'a `GET /api/dashboard` eklendi (dropt-api imajı yeniden derlenmeli).
- Level 1: dropt bridge oturumu, dropt DB kullanıcı sıra (sequence) geriliği nedeniyle ilk girişte 500 verebiliyordu; sıra düzeldi (kod değişikliği gerekmedi).

### Düzeltme — Ayarlar › Monitoring: OCP Thanos "self-signed certificate" bağlantı hatası
- OpenShift/Virtualization Thanos kaynağında **Bağlantı testi** `CERTIFICATE_VERIFY_FAILED` veriyordu: test `verify_ssl` (varsayılan True) değerini uyguluyor, çalışma zamanı sorguları ise değeri yok sayıp sabit `verify=False` kullanıyordu; üstelik "SSL doğrula" anahtarı yalnız "Other" kaynaklarda görünüyordu (OCP için kapatılamıyordu).
- Artık anahtar **tüm bağlamalarda** görünür ve test + OCP/Virtualization/Other sorguları + Prometheus proxy aynı kuralı (`prom_verify`) kullanır. OCP/Virtualization için varsayılan TLS doğrulaması kapalı (self-signed route); kullanıcı anahtarı açıp kaydedince gerçekten uygulanır. Eski kayıtlar veri değişikliği olmadan eski davranışta kalır.
- `monitoring-sources/test`: yalnız `source_id` gönderildiğinde `verify_ssl` artık dikkate alınır; sertifika hatasında "SSL doğrula'yı kapatın" ipucu eklendi.
- OpenShift Thanos kaynağında saklı `sha256~…` OAuth token'ı (~24 saat) dolunca sorgular ve test `HTTP 401` veriyordu. Artık geçersiz token, OpenShift modülündeki kayıtlı küme girişiyle otomatik yenilenir (`services/openshift/ocp_token.py`; bellekte tutulur, DB'ye yazılmaz; yoklama 5 dk önbellekli, başarısızlıkta saklı token kullanılır). Formda elle girilen token olduğu gibi sınanır.
- Ayarlar › Monitoring › OpenShift kaynağında Bearer token alanının yanına **(i) bilgi balonu**: Thanos URL'sini, kalıcı salt-okur ServiceAccount token'ını (`cluster-monitoring-view`), süresiz secret yöntemini ve geçici `oc whoami -t` token'ını `oc` komutlarıyla açıklar (TR/EN).
- Paketleme: `scripts/build-distribution.sh` artık `.env.bak*` ve `.env.local` dosyalarını pakete **koymaz** (önceki paketlere eski rotasyon yedekleri `.env.bak-rotate-*` sızıyordu).

### OpenShift Virtualization — ISO / CD-ROM ve sağ tık menüsü
- VM ⋯ menüsüne **ISO / CD-ROM**: mevcut PVC'yi (aynı namespace → doğrudan, erişilebilen başka namespace → CDI DataVolume ile klon) CD-ROM olarak bağlama, takılı CD-ROM'u çıkarma, "ilk önce bu CD-ROM'dan başlat" seçeneği.
- **İstemci bilgisayardan ISO yükleme**: tarayıcı → ainew → CDI upload proxy akışı (bellekte biriktirmez, ilerleme çubuğu); yüklenince isteğe bağlı VM'e bağlama. nginx'e `iso-upload` için sınırsız gövde / tamponsuz konum eklendi.
- VM satırında **sağ tık menüsü** (güç işlemleri + konsol + ⋯ menüsündeki tüm işlemler); satır içi yinelenen güç düğmeleri kaldırıldı.
- Düzeltme: disk ekleme ve Multus ağ atama strategic-merge-patch (CRD'de desteklenmez) yerine GET → merge-patch ile çalışır.
- Yeni uçlar (admin): `GET .../kubevirt/iso-sources`, `GET|POST .../vms/{ns}/{vm}/cdrom(s)`, `DELETE .../cdrom/{disk}`, `POST .../kubevirt/iso-upload`.

### Güvenlik — sayfa bazlı yetkilendirme (RBAC v2)
- İlke: bir sayfaya yetkisi olan kullanıcı o sayfadaki her şeyi yapar; ancak sayfa içindeki link/buton yetkisi olmayan modülün sayfasına götüremez.
- `core/module_policy.py`: yol öneki → sahip modül (`RULES`) + sayfa-içi çapraz kullanımı açıkça tanımlayan `GRANTS` (modül → sayfanın kullandığı uç). Listede olmayan hiçbir uç açılmaz.
- **Monitoring** modülü hub'ın tüm sekmelerini (Linux, Windows, OpenShift, Sanallaştırma, Zabbix/Diğer) ve yalnız onların çağırdığı uçları açar; platform komuta merkezleri / envanter / olay uçları kapalı.
- **Yönetici** (`executive`) genel okuma yetkisi kaldırıldı: yalnız `/ops/executive-summary` + Tüm Altyapı sohbeti (envanter özeti dahil). Komuta merkezi, platform envanteri ve olay uçları 403.
- Sayfa-içi çapraz kullanım (GRANTS): Windows sunucular ve OpenShift MTV paneli `GET /hypervisors/`; Hypervisors sayfası `/snapshots/server/*`; sohbet sayfaları `GET /servers/*`.
- Yalnız admin sayfalarının kullandığı `/rag`, `/tasks`, `/mcp` uçları admin'e alındı; `/level1`, `/integrations` yalnız kendi modülüne.
- Frontend: `config/routeAccess.ts` rota-modül tablosu + `LinkGuard` (yetkisiz modüle giden dahili bağlantıya tıklama engellenir, uyarı gösterilir); Monitoring hub sekmeleri `monitoring` modülüyle açılır.


### Güvenlik — modül izolasyonu (RBAC)
- Yetkisi olmayan modülün **hiçbir** API/sayfasına link, kısa yol, dashboard veya doğrudan URL ile erişilemez. Global middleware (`core/module_policy.py`) her `/api/v1` isteğini yol önekine göre modüle eşler; yetki yoksa 403. Yeni router sınıflandırılmadan kullanıcıya açılmaz (yalnız admin; test her route'un kapsandığını doğrular).
- Daha önce yalnız token geçerliliği kontrol ediliyordu: modülü olmayan kullanıcı envanter, olay, ayar, Windows `run-ps`, Ansible ad-hoc, MCP `call-tool`, SSH terminal ve OpenShift pod exec / VM console uçlarına ulaşabiliyordu.
- Middleware pasif / silinmiş kullanıcıyı ve MFA ara token'ını da reddeder (kısa TTL önbellek; modül ataması değişince anında geçerli).
- `platform=` parametreli ortak uçlar (olay, incident, ops, metrics, platform-reports) ilgili modül olmadan 403. `executive` platform verisinde yalnız okuma.
- Rol tabanı: `run-ps`, kimlik bilgisi yazma, `/mcp/*` → admin; ad-hoc / playbook / reboot / sync / bulk-delete → operator. Terminal, pod exec ve VM console WebSocket'leri modül + operator ister.
- Unified chat: yetkisiz platform soruları reddedilir; envanter özeti ve sunucu listeleri yetkisiz platformdan arındırılır (`admin` / `ai_automation` / `executive` kısıtsız).
- Frontend: `/dashboard` ve `/mcp` yalnız admin; `/terminal/:id` ve OpenShift VM console sayfaları modül ister; menüde Dashboard bağlantısı yalnız admin.

### Sanallaştırma karar katmanı (VMware · OLVM · OCP Virt)
- Ortak bulgu motoru: `infra_check_runs` / `infra_findings` / `infra_finding_exceptions`, kontrol kataloğu, periyodik fleet job `virt_insights` (aralık Ayarlar’dan). REST `/virt-insights/*` (`require_module("virtualization")`).
- Yeni ekranlar: `/virt/capacity` (effective kapasite, N+1, runway, what-if, yerleşim), `/virt/reclaim`, `/virt/health` (sağlık, ISO 27001 uyum + CSV/JSON, istisna, referans paketleri, yazma hesabı), `/virt/changes` (yapılandırma geçmişi, baseline, sapma). Dashboard’a 4 özet kartı; virt incident’a zaman çizelgesi.
- Raporlar: **Kapasite Planı (N+1)** ve **Denetim Kanıtı** (`/infra-reports`).
- Komut taslakları (PowerCLI / `oc`, geri alma satırıyla; uygulama çalıştırmaz).
- Offline CVE/VMSA, KB ve yükseltme/HCL paketleri (JSON yükleme; KB isteğe bağlı RAG).
- Onaylı düzeltme (VMware): izin listesi (snapshot sil, NTP restart/ayar, SSH durdur), okuma hesabından ayrı mühürlü yazma hesabı, Agent bekleyen aksiyon onayı, rollback bilgisi.
- Sohbet: READ_ONLY `virt_capacity_simulate`, `virt_placement_recommend`, `virt_reclaim_summary`, `virt_health_findings`, `virt_incident_timeline`; `h_capacity_n1` deterministik N+1 yanıtı. `virt_remediate` LLM’e görünmez (`Tool.llm_visible=False`).
- Erişim yalnız vCenter / OLVM Manager / OpenShift API; host bağlantısı yok.
- vCenter SOAP isteklerine `SOAPAction: urn:vim25/<apiVersion>` eklendi (karar katmanı istemcisi); aksi halde `layoutEx`, lockdown, vMotion ve datastore tarayıcısı eski API ile boş dönüyordu.
- Tek host’lu cluster’da HA rezervi `single_host` (effective Memory boş kalmıyordu); güç durumu `POWERED_ON` normalize.

### OpenShift karar katmanı
- Yeni sayfaların (Kapasite, Geri Kazanım, Sağlık, Değişiklikler; sanallaştırma + OpenShift) başlığı yanına (i) bilgi simgesi: sayfa nedir / ne için / nasıl kullanılır (TR+EN).
- Değişiklikler sayfasına **Mevcut durumu baseline yap** (operator): tür seçerek toplu ilk baseline. `POST /virt-insights/baseline` ve `/ocp-insights/baseline` kaynak/platform boşken tümüne uygulanır.
- Sol menü: Kapasite / Geri kazanım / Sağlık (/ Değişiklikler) artık hem Sanallaştırma hem OpenShift grubunda **Planlama ve Denetim** alt grubunda.
- `/openshift/changes`: node, MachineConfigPool, operatör sürümü ve cluster yapılandırması (proxy [kimlik bilgisi maskeli], OAuth, APIServer, Scheduler, Ingress) değişiklik geçmişi + baseline; baseline sapması `drift.entity.baseline` bulgusu (`platform=ocp`). REST `/ocp-insights/changes`, `/ocp-insights/baseline`.
- Kapasite senaryosu `POST /ocp-insights/capacity/simulate`: seçilen node'lar drene edilirse ve/veya yeni pod'lar eklenirse request doluluğu, sığma sonucu, eklenebilecek pod sayısı.
- Node risk kartı `GET /ocp-insights/node-risk` (Sağlık sayfası): tekrar eden NotReady / baskı / reboot / bağlantı kesintisi olayları; tahmin yok.
- OpenShift envanter sayfasında 4 özet kartı; OCP incident zaman çizelgesine yapılandırma değişiklikleri eklendi.
- Sanallaştırma incident zaman çizelgesi yapılandırma değişikliği sorgusu yalnız sanallaştırma platformlarıyla sınırlandı.
- OCP incident detayına zaman çizelgesi + kök neden adayları: `/ocp-insights/incident-timeline/{id}` (DB olayları, aktif bulgular, salt okunur canlı pod durumu / K8s event / pod log hata satırları — sırlar maskeli).
- `/openshift/capacity`, `/openshift/reclaim`, `/openshift/health`; REST `/ocp-insights/*` (`require_module("openshift")`). Worker N+1, PVC / request geri kazanımı, ClusterOperator / MCP / Compliance Operator / güncelleme bulguları.

## [1.0.9.39] - 2026-10-05

### Centrify / Level 1
- Zone yönetimi (WinRM → ADEdit): rol, komut, atama, computer, unix profil sync.
- Zone başına tek `list_zone_inventory` + WinRM throttle (`CENTRIFY_SYNC_*`).
- Rol↔komut üyeliği ve login bayrakları senkronu; tepeden (parent) komut eşlemesi.
- AI hesaplayıcılar: effective access, login teşhisi, expiring, similar roles/commands, explain role/command.
- Centrify chat: `require_module("level1")`, tool çıktısı `<<<CENTRIFY_TOOL_DATA>>>`.
- REST: `/centrify-mgmt/query/*`. Demo seed yalnızca API ile; dağıtım tar’ında demo satırı yok.

### Kurulum / güncelleme
- `update-rhel.sh` / `install-rhel.sh` / `fix-load-ainew-images.sh`: parçalı imaj arşivleri (`.part*`) varken birleşmiş `.tar.gz` **her zaman** yeniden üretilir. Eski birleşmiş backend tar’ı boyuta bakılarak atlanıp yeni sürüm etiketinin eski imajı göstermesi engellendi.
- Update sonrası `ainew-backend` / `ainew-frontend` sürüm etiketleri yoksa işlem durur (Dropt doğrulaması gibi).

### OpenShift Monitoring
- `ocp_resource_metrics` sync: aynı örnek anında mükerrer `(kind, object_key)` (özellikle birden fazla virt-launcher → aynı VM) UniqueViolation ile tüm commit’i düşürüp tabloyu boş bırakıyordu; satırlar birleştirilerek tekilleştirildi.

### Zabbix Other monitoring
- Monitoring hub: Zabbix kaynağı için Özet / Hosts / Grafikler / Problems / Match map (`/monitoring/zabbix/*`).
- Semantic catalog + item key match map (`cpu_util`, `mem_used_pct`, `fs_used_pct`, …).
- Unified sohbet: `zabbix_query` (READ-ONLY; mesajda tam label); `custom_prometheus_query` Zabbix’e delege eder.

## [1.0.9.38] - 2026-09-29

### OpenShift Access / RBAC
- Yeni sayfa `/openshift/access`: Users, Groups, Identities, Roles, ClusterRoles, RoleBindings, ClusterRoleBindings, ServiceAccounts, subject arama, token can-i, OAuth IdP (küme API, salt okunur).
- Namespaceli listeler (Roles / RoleBindings / SA) ve can-i / SA subject: proje listesinden namespace listbox.
- Sohbet: `ocp_access_query` (READ-ONLY).

### OpenShift teşhis (sohbet)
- `ocp_pod_logs` — pod log okuma; çok-container pod’da otomatik app container seçimi.
- `ocp_resource_yaml` — kaynak YAML okuma. Apply/patch yok; düzeltme metin önerisi.

### OpenShift Monitoring
- `/openshift/monitoring`: Virt tarzı özet + overlay grafikler (Node/Pod/VM). `metrics.k8s.io` → Timescale `ocp_resource_metrics` (saklama 30 gün, örnek ~60 sn). Cluster seçici; kimlik `(cluster_id, kind, object_key)`. Deploy öncesi geçmiş yok (API geriye doldurulamaz).
- Prometheus modu: Kubernetes Views (Global / Namespaces / Nodes / Pods) + GPU DCGM / kubevirt şablonları; hub `/monitoring`; Other kaynaklar label + `collector_type`.
- Sohbet: `ocp_monitoring_query` / `ocp_prometheus_query`. `/openshift/chat` + `/grafik` OCP Timescale serisi.
- `/grafik` Top-N zinciri (linux / virt / ocp): isim yoksa önce sırala, sonra seri.

## [1.0.9.37] - 2026-09-18

### Sohbet grafikleri
- Prometheus’ta olup envanterde olmayan Linux host’lar `/graph` ile çizilir; instance eşlemesi FQDN ile birebir.
- “I/O” disk okuma/yazma serisine gider; disk doluluk yüzdesi ile karışmaz.

### Sohbet PDF ve grafik ölçeği
- PDF lejantında seri adı, min–max ve son değer yazar.
- Düşük yüzde serilerinde Y ekseni 0–100’e sabitlenmez; dalga okunur. Geniş kullanımda 0–100 kalır.
- 12 saatlik pencerede saat ekseni yaklaşık saatliktir; dikey ızgara dalgayı saate bağlar.
- Sohbet silinince veya temizlenince akan yanıt iptal edilir (Linux, Windows, Unified, Virt).

## [1.0.9.36] - 2026-09-14

### Sanallaştırma — çoklu vCenter
- Nesne kimliği `(hypervisor_id, ad)`; aynı adlı VM, ESXi ve datastore ikinci vCenter'da birleşmez.
- Monitoring, seri sorguları, raporlar, virt sohbet grafikleri ve envanter senkronu bu kimliği kullanır.
- Monitoring'de vCenter seçimi VM/ESXi/Datastore ekseninin hemen önünde; çoklu seçim, varsayılan ilk vCenter.
- Envanter eşleştirme ve birleştirme başka vCenter'ın Server satırını sahiplenmez.

### Sohbet grafikleri ve PDF
- Aralık penceresi yuvarlanmaz (ör. 10 gün 10 gün kalır); eksen aralığa göre saat veya gün gösterir.
- Açık temada grafik tooltip'i okunur.
- Sohbet PDF: `/graph` grafikleri ve mermaid / `ainew-diagram` çizimleri SVG olarak gömülür.

### Düzeltme
- Monitoring VM listesi, SQLAlchemy `in_()` boolean hatası yüzünden 500 vermez.

## [1.0.9.35] - 2026-09-13

### Raporlar (Kapasite / Tahmin / Risk / Konsolidasyon)
- Tahmin: trend uyumu ile eşiğe-tarih belirsizliği ayrıldı; CPU p95+%50 eğim notu; büyüme formatı düzeltildi (`%/gün`).
- Floor kuralı: yalnızca düşük/yok trend güvende; medium+ düşüşte ham extrapolasyon; ham 12ay değeri şeffaf.
- Kapasite / Risk / Konsolidasyon / Tahmin: kural tabanlı yorum (`narrative`); tek host’ta filo/host yorum tekrarı kaldırıldı.
- Konsolidasyon: `virt_vm_metrics` ile idle / usage-based oversized; SLA event_proxy şeffaflığı; özel raporda `as_of` / empty.

## [1.0.9.34] - 2026-09-12

### Sanallaştırma Monitoring
- Yeni sayfa: Sanallaştırma → Monitoring (`/virt/monitoring`) — vCenter/Timescale SoT, Prometheus karışmaz.
- Kaynak grafikleri: 15m–60g aralık, VM/ESXi/datastore ekseni, çoklu nesne overlay (en fazla 8), metrik slot’ları.
- Ortam özeti, kapasite, top tüketiciler, ESXi filo karşılaştırması, 24s olay zaman çizelgesi.

### Sohbet grafikleri (`/graph` `/grafik` `/chart`)
- Linux/Windows/Virt/Unified: Recharts zaman serisi + çapraz overlay (`chat_charts` → `meta.charts`).
- Linux/Windows: Timescale `metric_data`, boşsa salt okunur Prom `query_range` (scrape yok).
- Virt: Monitoring `query_series`; aynı birim overlay, farklı birimler ayrı grafik; SSH/WinRM geçmiş eğri değil.

### AI / routing
- Olumsuz pencere (`intent_text`); virt filo perf DB→QueryPerf; virt chat RAG; diyagram `ainew-diagram` / React Flow.
- AI Mimari GUIDE (TR/EN) + Cursor kuralı güncellendi.

### UI
- OS ikonları: VMware (yeşil katman), Ubuntu, Debian, Linux Tux; vCenter adı/Photon/VCSA tanıma.

## [1.0.9.33] - 2026-09-11

### AI / sohbet
- Unified evidence-retry, `data_status`, context kesilme notu, coverage-miss UI, multi-clause check.
- Düşük güven routing LLM hint; harici sağlayıcı tool-calling; Exadata DB envanter tool’ları.
- Linux×virt I/O korelasyonu (`linux_virt_io_correlate`, join şartlı).
- Unified kanıt rozeti (high/medium/low — model güveni değil).
- `/diagram` `/draw` `/görselleştir` `/şema`: Mermaid çıktı + kısa yorum; frontend `ChatMermaid` (açık kart, kontrast harden).
- Path etiketi düzeltmesi: `[/boot]` / Windows `\` Mermaid şekil sözdizimini kırıyordu → sanitize + prompt kuralı.
- AI Mimari GUIDE (TR/EN) + Ayarlar → Hakkında PDF pack; Cursor mimari kuralı.

## [1.0.9.31] - 2026-09-09

### AI / LLM
- Uzak model kopunca sessiz local fallback yok; fail-fast + kibar hata; ayar yayını ile worker yeniden bağlanır.
- LLM token kullanımı admin sohbet UI’da (SSE metadata); context hard-gate + karakter/token kalibrasyonu.
- Boş yanıt / Ollama tool-parse kaçaklarında final-cevap nudge + geçici LLM hatalarında 1 otomatik retry.
- Sohbet iptali (AbortController + Redis kooperatif iptal) tüm AI chat modüllerinde.

### RAG
- Re-index Celery worker’da; içerik hash ile incremental embed; concurrency / seed backoff.
- Eski/orphan RAG event chunk bakım işi.

### Kapasite / raporlar
- Theil–Sen eğim, eşik gün belirsizlik aralığı, GB/gün büyüme; Linux kapasite raporlarında trend.
- Rapor metodolojisi info tooltip’leri.

### Sanallaştırma asistanı
- Birleşik Scope / entity projection; VM disk↔datastore eşlemesi; tek varlık sorularında filo dump yok.
- `db_virt_cross_match` VM ekseni + host_vm_count; `db_metric_trend` min/max değer filtresi + spike/sustained `pattern`.
- Disk latency “veri yok” ≠ 0.0; VMware Tools running/version persist; VM network (net_rx/tx_kbps) trend metrikleri.
- `metric_data` bileşik PK + ON CONFLICT; `cpu_ready_pct` vCPU normalizasyonu / backfill.

### UI
- Açık tema: sağ tık menü ve sabit hex arka planların light remap’i.

## [1.0.9.29] - 2026-09-04

### OpenShift / KubeVirt asistan
- Cluster sağlık/operatör (`ocp_cluster_status`), storage PV/PVC/SC (`ocp_storage_overview`), Multus NAD (`ocp_network_overview`), DataVolume, Live Migration, ResourceQuota/LimitRange, KubeVirt VM detay ve snapshot/restore tool'ları eklendi.
- `kubevirt_vm_detail` alan projeksiyonu: kullanıcı ne sordıysa yalnız onu döner (varsayılan kısa özet; full dump yok).
- OpenShiftCluster üzerinden KubeVirt erişimi (ayrı hypervisor kaydı zorunlu değil); `openshift_ask` canlı sürüm kullanır.

### Raporlar / Chat
- Özel raporlar (custom reports) + platform Altyapı Raporları kataloğuna entegrasyon; RBAC `custom_reports` modülü.
- Snapshot boyutu (SOAP layout + datastore browser), çıktı direktifleri (`/table` `/json` `/brief`), bilgi kirliliği / entity filtreleri, kapasite analitiği ve LLM context budget ayarı.

## [1.0.9.27] - 2026-08-15

### Chat / Prometheus
- Sohbet metrikleri **instance JOIN**: tek tablo, bir satır = bir scrape `instance`. Ayrı CPU/RAM sıralamalarını modelin birleştirmesi yok; boş hücre “exporter yok” uydurması değil.
- Üç katman: kısa ad (`cpu`/`ram`/`disk`/ağ) = Canlı Metrikler preset; `detay` = aile (CPU mode, mount, swap, load5/15); `kapsamlı` = `node_*` isimleri + az sayıda named host’ta örnek seri (filo dump yok).
- Çok sunucu × çok metrik aynı tabloda. Hostname **öneki** (`oprbigdata` → oprbigdata3/5/13). Scrape / `prometheus.yml` / target JSON değişmedi.

## [1.0.9.26] - 2026-08-15

### Chat / RAG mimarisi
- RAG araması Postgres `rag_embeddings` (pgvector). `$DATA_DIR/chroma` volume eski Chroma için (migrate/rollback); silinmez.
- Sohbet turları (`chat_turns`) + Redis olay günlüğü + FIFO AI kapısı; 2 uvicorn worker API’yi uzun SSE sırasında kilitlemez.
- Varsayılanlar kod/compose/`.env.example`: `UVICORN_WORKERS=2`, `AINEW_SERVICE_ROLE=all`, `CHAT_AI_MAX_CONCURRENT=3`, `DB_POOL_SIZE=20`, `DB_MAX_OVERFLOW=30`. Kurulum dizinine bağlı host yolu yok; `RAG_CHROMA_PATH` container içi `/app/chroma`.
- Prod `docker-compose` ve entrypoint aynı default’u kullanır (`install-rhel.sh` bu sayıları `.env`’e kazımaz).
- Ayarlar → RAG: eklenen runbook listesi ilk 5 satır + kaydırma; doküman içi arama (başlık, sayfa, benzerlik, alıntı).

### RAG seed (ilk kurulum)
- Gömülü runbook’lar `docs/rag_seed/*.md` + `manifest.json`; tar ve prod compose `./docs/rag_seed:/app/docs/rag_seed:ro`.
- Backend açılışında embedding hazır olana kadar seed yeniden denenir (chunk’lar Postgres).
- Dağıtım imajına `docs/rag_seed` kopyalanır (volume yoksa bile).

## [1.0.9.25] - 2026-08-14

### Düzeltildi — Chat / RAG donması
- Chroma path başına tek `PersistentClient` + kilit; her koleksiyon için yeni client DuckDB kilidinde sohbeti (Linux dahil) asıyordu.
- RAG koleksiyon sorguları sıralı. Boş indekste query atlanır.
- Tüm Altyapı: “sunucuları listele / kaç sunucu var” DB envanter kısayolu (RAG/SSH yok). “listeler misin” kalıbı tanınır.
- Unified envanter özeti AI Ready adlarını 40 ile sınırlar.

### Uzak AI
- Zorunlu alanlar yalnızca Gateway URL + Model. Virtual Key ve API Key isteğe bağlı (test/kayıt “Kimlik gerekli” 400 kalkar).
- `remote_llm_enabled()` artık API key istemez; açık + URL yeterli.

### Dağıtım paketi
- `build-distribution.sh` çalışma ağacındaki `data/` (Postgres/Dropt envanteri) tar’a koymaz.

### Level 1 / Operasyon merkezi
- Seçim çubuğu (Wi‑Fi + İşlemler) her zaman görünür. Seçim yokken İşlemler kapalı; bağlantı testi tüm envanteri (onay sonrası) tarar. Seçim varken eski davranış: yalnızca seçilenler + İşlemler menüsü.
- Toplu bağlantı testi varsayılan arka planda başlar; özet kutusu sürüklenebilir.

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
