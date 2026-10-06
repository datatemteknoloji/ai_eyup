# Changelog

Bu dosya, GitHub Release notlarının kalıcı ve air-gapped (internetsiz) müşteri
ortamlarında da erişilebilir bir kopyasıdır — internet erişimi olmayan
kurulumlarda `github.com/.../releases` sayfasına bakılamadığı için, paketle
birlikte gelen bu dosya sürüm geçmişini görmenin tek yoludur.

Format [Keep a Changelog](https://keepachangelog.com/) yaklaşımına yakındır.
Yeni bir release oluştururken bu dosyaya da bir madde eklemek için
`scripts/release.sh` kullanın (bkz. o script'in başlığı).

## [Unreleased]

## [1.0.9.40] - 2026-10-06

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
