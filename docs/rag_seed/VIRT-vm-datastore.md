# Sanallaştırma — VM güç / datastore

## Kaynak sırası (ainew)
1. **DB** (son sync): `db_list_vms`, `db_vm_detail`, `db_list_datastores`, `db_list_esx_hosts`.
2. `stale=true` veya boşsa canlı: `vcenter_ask` / alarm-task araçları.
3. OpenShift Virtualization (KubeVirt) VM’ler hypervisor satırında olmayabilir — OCP yüzeyinden bak.

## Datastore dolu
- VM power-on / snapshot / clone fail, `no space`.
- Kapasite vs erişilebilir: `accessible=false` ayrı sorundur (path, APD).
- İnce (thin) provision görünür boşluk yanıltır; gerçek free’ye bak.

## VM güç
- `poweredOff` / `suspended` vs guest tools not running.
- Host maintenance, HA restart, DRS migrate ortasında geçici NotResponding.

## ainew
Virt / Tüm Altyapı: VM adı veya “datastore doluluk”. Tüm VM listesi cap’lidir; “tüm VM’ler” onay ister.
