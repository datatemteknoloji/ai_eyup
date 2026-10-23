# ainew — Entegrasyonlar GUIDE

Modül `integrations`: dış kaynakları ainew envanterine bağlama yeri. Operasyon menüleri (Sanallaştırma, OCP, …) bağlantıdan **sonra** dolar.

## Menüler

| Menü | Yol | İşlem |
|------|-----|--------|
| Envanter hub | `/integrations` | Kaynak özeti |
| UCMDB | `/integrations/ucmdb` | CMDB import |
| vCenter / OLVM | `/integrations/hypervisors` | VMware, oVirt, Proxmox, Hyper-V, OCP virt |
| Fiziksel hostlar | `/integrations/physical-hosts` | SSH/WinRM hedefleri |
| Exadata | `/integrations/exadata` | Rack |
| OpenShift | `/integrations/openshift` | Cluster API |
| Yedekleme (Veeam VBR) | `/integrations/backup` | Salt okunur Veeam REST bağlantısı (yalnız admin): endpoint, kullanıcı (önerilen rol Backup Viewer), REST API revizyonu, CA/SSL. Bağlantı yoksa Yedek & DR menüsü görünmez. 1.3-rev1 dışı revizyonlar "alanları doğrulanmadı" uyarısıyla seçilebilir. Harici LLM açıkken yedek verisinin (VM/iş/depo adları) modele gittiği uyarılır |
| Donanım yönetimi (Dell OME / HPE OneView–OVGD) | `/integrations/hardware` | Opsiyonel, salt-okunur REST (yalnız admin): OME 4.x veya OneView appliance(lar)ı / Global Dashboard; iLO/iDRAC’e doğrudan bağlanılmaz. Kimlik doğrulama yalnız BİR kez denenir; reddedilirse senkron durur (hesap kilitlenmesin) ve yalnız başarılı “Bağlantıyı test et” sürdürür. Veri “Donanım” sayfasında (`/hardware`, `hardware` modülü) ve fiziksel sunucu çekmecesindeki “Donanım” kartında görünür. Bağlantı yoksa menü/kart görünmez. |
| Automic (UC4) | `/integrations/automic` | Automic kaynak DB (Oracle) salt okunur bağlantı sihirbazı, test, keşif, toplama — ayrıntı: Otomasyon GUIDE (`modules/automation.md`); DBA yetkileri: `automic-source-dba-grants.md` |

## Akış

Ekle → test → kaydet → senkron → ilgili domain menüsü. Kimlikler şifreli; GUIDE sır dökmez.

## RBAC

Entegrasyon yazmak `integrations` ister. Sanallaştırma dashboard’u `virtualization` ister — ikisi ayrıdır. Automic sistem yönetimi `integrations`, görüntüleme/asistan `automation` ister. Yedekleme (Veeam) bağlantısını yalnız admin yönetir; Yedek & DR sayfaları `virtualization` ister. Donanım yönetimi bağlantısını yalnız admin yönetir; Donanım sayfası ve kartı (BMC IP, seri/service tag içerir) ayrı `hardware` modülü ister (varsayılan yalnız Admin; `/servers` API’lerine BMC bilgisi eklenmez).
