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
| Donanım yönetimi (Dell OME / HPE OneView–OVGD) | `/integrations/hardware` | Salt-okunur REST (yalnız admin); tek «Donanım yönetim aracı ekle» düğmesi: **Dell OpenManage Enterprise (OME)**, **HPE OneView Global Dashboard (OVGD, appliance'lar otomatik keşfedilir)** veya **HPE OneView (tek appliance)**: OME 4.x veya OneView appliance(lar)ı / Global Dashboard; iLO/iDRAC’e doğrudan bağlanılmaz. Kimlik doğrulama yalnız BİR kez denenir; reddedilirse senkron durur (hesap kilitlenmesin) ve yalnız başarılı “Bağlantıyı test et” sürdürür. Veri; Linux/Windows sunucu çekmecesinde ve ESXi host panelinde “Donanım” kartı + liste rozeti olarak, **Olaylar/Incident** akışında (kritik sağlık, aktif kritik alarm → olay → incident; tekrarlayan uyarı → uyarı olayı), incident detayında «İlgili donanım» (etki alanı: VM, iş servisi, küme HA riski) ve filo ekranında (`/hardware`, `hardware` modülü: filo, şasi, alarm, garanti/yenileme raporu, eşleşmeyenler için öneri + elle bağlama) görünür. Bağlantı yoksa menü, kart, rozet ve `/hardware` adresi görünmez/yönlendirilir. |
| Automic (UC4) | `/integrations/automic` | Automic kaynak DB (Oracle) salt okunur bağlantı sihirbazı, test, keşif, toplama — ayrıntı: Otomasyon GUIDE (`modules/automation.md`); DBA yetkileri: `automic-source-dba-grants.md` |

## Akış

Ekle → test → kaydet → senkron → ilgili domain menüsü. Kimlikler şifreli; GUIDE sır dökmez.

## RBAC

Entegrasyon yazmak `integrations` ister. Sanallaştırma dashboard’u `virtualization` ister — ikisi ayrıdır. Automic sistem yönetimi `integrations`, görüntüleme/asistan `automation` ister. Yedekleme (Veeam) bağlantısını yalnız admin yönetir; Yedek & DR sayfaları `virtualization` ister. Donanım yönetimi bağlantısını yalnız admin yönetir; İki seviyeli yetki: Linux/Windows/Sanallaştırma kullanıcıları kendi sunucularının donanım **özetini** (sağlık, model, şasi/yuva, garanti, alarm) kart/rozet/incident kartında görür; BMC IP, seri/service tag, UUID, firmware ve konsol bağlantısı ile filo ekranı ayrı `hardware` modülü ister (varsayılan yalnız Admin; `/servers` API’lerine BMC bilgisi eklenmez). Elle eşleştirme (`/hw/links`) yalnız ainew içine yazar ve en az operatör rolü ister. **Host donanım günlükleri (Faz 3a, varsayılan KAPALI):** Gelişmiş Ayarlar → «Host donanım logları» açılırsa ESXi host'lardan vCenter üzerinden IPMI SEL ve vmkernel/vmkwarning donanım kayıtları (vCenter rolünde `Global.Diagnostics` gerekir) okunur ve mevcut Linux/Windows log toplayıcılarının donanım kayıtları (MCE, EDAC/ECC, WHEA, PSU, ısı) ayrıştırılır; iLO/iDRAC'e bağlanılmaz, yeni port/firewall/hesap gerekmez, donanıma yazılmaz. Sonuç Linux/Windows çekmecesinde ve ESXi host panelinde «Donanım günlükleri» kartı olarak yalnız kayıt varken görünür; kayıtlar 30 gün saklanır, metinler maskelenir. Donanım sağlayıcısı (OME/OneView) şart değildir.
