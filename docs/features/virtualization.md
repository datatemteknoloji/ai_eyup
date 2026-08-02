# Sanallaştırma / Hypervisor Yönetimi

> **Diataxis:** How-to + Reference

ainew, 5 farklı hypervisor tipini tek bir envanterde yönetir: **VMware vCenter**,
**oVirt/KVM**, **Proxmox VE**, **Microsoft Hyper-V** ve **OpenShift Virtualization
(KubeVirt)**. Her hypervisor eklendiğinde, üzerindeki VM'ler otomatik olarak
`servers` tablosuna senkronize edilir ve platform genelinde (dashboard, AIOps,
raporlar) fiziksel sunucularla aynı şekilde görünür — ama metrikleri **farklı bir
kaynaktan** gelir (bkz. [Metrik Mimarisi](../explanation-metrics-architecture.md)).

## Nasıl yapılır: Yeni bir hypervisor bağlama

1. **Entegrasyonlar → Sanallaştırma** sayfasına gidin (`/hypervisors` veya
   `/integrations/hypervisors`).
2. "Yeni Hypervisor Ekle" ile tipi seçin ve aşağıdaki tabloya göre bağlantı
   bilgilerini girin.
3. **Bağlantıyı Test Et** ile doğrulayın — başarılıysa kaydedin.
4. Kayıttan sonra **VM'leri Senkronize Et** ile ilk taramayı başlatın
   (`background=true` varsayılan — ilerleme çubuğuyla arka planda çalışır).
5. Senkronizasyon bitince VM'ler **Sunucular** listesinde ve ilgili platform
   AIOps sayfalarında görünür.

### Bağlantı bilgileri (tipe göre)

| Tip | `type` değeri | Host alanı | Varsayılan port | Kimlik doğrulama |
|---|---|---|---|---|
| VMware vCenter | `vmware` | IP/FQDN | 443 (HTTPS/SOAP) | Kullanıcı adı + şifre |
| oVirt / KVM | `kvm` | IP/FQDN | 443 (REST) | Kullanıcı adı + şifre |
| Proxmox VE | `proxmox` | IP/FQDN | 8006 (REST) | Kullanıcı adı + şifre |
| Microsoft Hyper-V | `hyperv` | IP/FQDN | 5985 (WinRM) | Domain/local kullanıcı + şifre |
| OpenShift Virtualization | `openshift_virt` | `api_url` (Kubernetes API) | — | Token **veya** kullanıcı adı + şifre (OAuth) |

Kaynak: `backend/app/api/hypervisors.py` (`TestConnectionRequest`, `test_connection`),
`backend/app/models/hypervisor.py` (`HypervisorType`).

**Önemli:** `hostname` alanı sadece görüntüleme amaçlı bir **etiket** olabilir
("Vcenter datatem" gibi) — bağlantı kurulurken her zaman `ip_address` (varsa)
tercih edilir, yoksa `hostname` denenir. Hypervisor eklerken host alanına
**çözümlenebilir bir IP veya FQDN** girin; sadece görünen ad girerseniz VM
metrik senkronizasyonu (vCenter QuickStats) başarısız olur.

## Nasıl yapılır: VM senkronizasyonunu tetikleme

- **Tek hypervisor:** `POST /api/v1/hypervisors/{id}/sync-vms?background=true`
- **Tüm hypervisor'lar:** `POST /api/v1/hypervisors/sync-all-vms`
- Senkronizasyon durumu: `GET /api/v1/hypervisors/{id}/sync-status`

Her iki uç nokta da bilinçli olarak **senkron (`def`)** tanımlanmıştır — VM
senkronizasyonu dakikalarca sürebilen bloklayan SOAP/REST çağrıları yapar;
`async def` olsaydı bu süre boyunca **tüm platformun** event loop'u kilitlenirdi
(bkz. [Ölçek ve Performans](../scale-and-performance.md)).

## Nasıl yapılır: vCenter olay (event) senkronizasyonu

vCenter tabanlı hypervisor'lar için VM yaşam döngüsü olayları (start/stop/migrate/
snapshot vb.) ayrıca senkronize edilebilir:

- Tek hypervisor: `POST /api/v1/hypervisors/{id}/sync-vcenter-events`
- Tüm vCenter'lar: `POST /api/v1/hypervisors/sync-vcenter-events`

Bu, `system_events` tablosuna `vcenter_event` tipi kayıtlar ekler ve
Sanallaştırma AIOps (Events/Incidents) sayfalarında görünür.

## Referans: Host metrikleri

`GET /api/v1/hypervisors/{id}/host-metrics` — ESX/host seviyesinde CPU, bellek,
depolama kullanımı döner (VM değil, fiziksel host). Manuel tetikleme:
`POST /api/v1/hypervisors/{id}/host-metrics/sync`.

## Referans: Sanallaştırma AI Chat ("Sor")

`/hypervisors/ask*` uç noktaları, envanterdeki VM/host/datastore verisi
üzerinde doğal dilde soru sorma imkânı sunar (`/virt/chat` sayfası). Bu, tool-
calling tabanlı bir agent değildir — envanter verisi üzerinde bağlam
oluşturup LLM'e soran, salt-okunur bir Q&A katmanıdır. Detay için
[Agentic AI](agent.md) dokümanına bakın (agent ile karıştırılmamalı).

## Sorun giderme

| Belirti | Olası neden | Çözüm |
|---|---|---|
| Bağlantı testi "Giriş başarısız" | Yanlış host/port/şifre | Bilgileri kontrol edin; vCenter için port her zaman 443 |
| VM'ler senkronize oluyor ama metrikleri "Scrape yok" gösteriyor | Hypervisor `hostname` alanı görünen ad, `ip_address` boş | Hypervisor kaydını düzenleyip geçerli bir IP/FQDN girin |
| Sanallaştırma sayfası uzun süre "yükleniyor" gösteriyor | vCenter host'a ağ erişimi yok (timeout ~300s) | `test-connection` senkron olduğu için bu artık platformu kilitlemez, ama kendi isteği zaman aşımına uğrar — vCenter erişimini kontrol edin |
| VM Node Exporter kurulu ama fiziksel sunucu listesinde "sızıyor" | Eski bir kurulumdan kalan Node Exporter hedefi | `monitoring.py`'daki `matched_instances` ön-filtresi bunu otomatik hariç tutar (v1.0.9.16+) |

## İlgili
- [Metrik Mimarisi (VM vs Fiziksel)](../explanation-metrics-architecture.md) — Explanation
- [Ölçek ve Performans](../scale-and-performance.md) — Reference + How-to
- [AIOps Pipeline](aiops.md) — Explanation + How-to
- [API Reference](../api-reference.md) — Reference

---
Back to [Documentation Index](../index.md)
