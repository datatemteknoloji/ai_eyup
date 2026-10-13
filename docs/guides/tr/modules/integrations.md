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
| Automic (UC4) | `/integrations/automic` | Automic kaynak DB (Oracle) salt okunur bağlantı sihirbazı, test, keşif, toplama — ayrıntı: Otomasyon GUIDE (`modules/automation.md`); DBA yetkileri: `automic-source-dba-grants.md` |

## Akış

Ekle → test → kaydet → senkron → ilgili domain menüsü. Kimlikler şifreli; GUIDE sır dökmez.

## RBAC

Entegrasyon yazmak `integrations` ister. Sanallaştırma dashboard’u `virtualization` ister — ikisi ayrıdır. Automic sistem yönetimi `integrations`, görüntüleme/asistan `automation` ister.
