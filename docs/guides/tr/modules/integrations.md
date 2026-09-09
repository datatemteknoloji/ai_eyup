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

## Akış

Ekle → test → kaydet → senkron → ilgili domain menüsü. Kimlikler şifreli; GUIDE sır dökmez.

## RBAC

Entegrasyon yazmak `integrations` ister. Sanallaştırma dashboard’u `virtualization` ister — ikisi ayrıdır.
