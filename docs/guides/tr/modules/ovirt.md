# ainew — oVirt / OLVM GUIDE

oVirt ve Oracle Linux Virtualization Manager **ayrı bir RBAC modülü değildir**. Yetki: `virtualization` (görünüm/sohbet) + `integrations` (bağlantı).

## Mimari

```mermaid
flowchart LR
  UI[Entegrasyonlar → vCenter/OLVM] --> API[hypervisor type=kvm]
  API --> OV[oVirt REST :443]
  OV --> SYNC[VM / host / datastore]
  SYNC --> MENU[Sanallaştırma dashboard / rapor / sohbet]
```

## Nerede ne yapılır

1. **Entegrasyonlar → vCenter/OLVM** (`/integrations/hypervisors`): tip oVirt/KVM, API adresi, kullanıcı/şifre, **Bağlantıyı test et**, kaydet, **VM senkron**.  
2. **Sanallaştırma → Dashboard** (`/hypervisors`): host, VM, depolama.  
3. **Altyapı raporları** (`/infra-reports`): kapasite.  
4. **Asistan** (`/virt/chat`): motor/cluster/VM adı ile sorun.

vCenter ile aynı menüler; ayıran kayıt tipi (`kvm` vs `vmware`) ve REST vs SOAP’tır.

## Senaryo

OLVM ekle → senkron → “şu data domain doluluk ve VM listesi”.

## Limitler

Ayrı “oVirt” sol menü grubu yoktur. Engine erişilemezse senkron boş kalır. Level 1, oVirt API’si değildir (hedef Linux SSH işleridir).
