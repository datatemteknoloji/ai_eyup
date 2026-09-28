# VMware / vCenter — ainew operasyon haritası (1–8, 11, 13)

Bu runbook, Virt chat’in **ortam kanıtı** ile cevap vermesi gereken konuları
araçlara bağlar. Genel teori için değil; hangi tool’un neyi okuduğu için.

## 1 Mimari
- Hiyerarşi: vCenter → Datacenter → Cluster → Host → VM / Datastore / Network.
- Araç: `db_list_clusters`, `db_list_esx_hosts(cluster=…)`, `db_list_vms(cluster=…)`,
  `db_list_datastores`, `db_virt_cross_match`.
- Resource Pool / VDS / Network: `vcenter_property_read`
  (object_type=ResourcePool | DistributedVirtualSwitch | Network | HostSystem
  config.network.*). Folder/tag yoksa “sorguda dönmedi” de.

## 2 Cluster (HA / DRS)
- `db_list_clusters`: ha_enabled, admission, slots, ha_verdict, drs_behavior,
  migration threshold, effective CPU/RAM.
- Detay path: ClusterComputeResource dasConfig / drsConfig.
- “X cluster’daki host/VM”: önce cluster adını doğrula, sonra **cluster=** ile listele.
  Host tool’unda cluster yoksa TÜM ESXi sızıntısı olur — yasak.

## 3 Compute
- Kullanım: Timescale + `db_metric_trend` / `vcenter_perf_query`
  (cpu_pct, ready, costop, mem, balloon, swap).
- Darboğaz: `virt_bottleneck_diagnose` (VM mi host mu).
- Shares/reservation/limit: VM `config.cpuAllocation` / `memoryAllocation` property_read.

## 4 Storage
- Kapasite/IOPS/latency: `db_list_datastores` + monitoring series.
- Tip (VMFS/NFS/vSAN): Datastore `summary.type`.
- Multipath / APD-PDL ipucu: HostSystem `config.storageDevice.multipathInfo` +
  datastore `summary.accessible`.
- vSAN disk-group FTT derinliği sync’te yok → property veya “bu ortamda vSAN detay
  sync yok” (uydurma politika yazma).

## 5 Networking
- Trafik: host/VM net_rx/tx, dropped metrikleri.
- vSS: HostSystem `config.network.vswitch` / `portgroup`.
- VDS: `DistributedVirtualSwitch` property_read (MTU, uplink).
- NSX: ainew sync yok → yoksa söyle, uydurma firewall kuralı yazma.

## 6 VM yaşam döngüsü (READ)
- Liste/detay: `db_list_vms`, `db_vm_detail`.
- Tools / template / hardware: VM property veya detail alanları.
- Snapshot: `vcenter_list_vm_snapshots`, `vcenter_snapshot_summary` (boyut).
- Clone/template oluşturma/power: READ-ONLY — yapma; yalnız gözlem.

## 7 Migration
- `vcenter_live_tasks` / events: MigrateVM, RelocateVM, Storage vMotion.
- Fail: task error mesajı; EVC uyumsuzluğu property/cluster’dan çıkarım.
- Long-distance gereksinim: genel bilgi + görev hatası; latency ölçümü yoksa uydurma.

## 8 Yedek / DR
- Snapshot yaşı/zinciri riski + alarm.
- SRM / vSphere Replication / Veeam: entegrasyon yoksa “ortamda SRM verisi yok”.
- CBT ayrı sync yok.

## 11 Monitoring
- UI: Virt monitoring = **vCenter API → Timescale** (Prometheus toggle yok).
- Chat: `virt_health_overview`, `db_virt_alarms`, `vcenter_live_alarms`,
  `vcenter_live_tasks`, perf query, metric trend.

## 13 Troubleshooting
- CPU ready / disk latency / balloon → bottleneck tool.
- HA risk → db_list_clusters ha_verdict + alarm/event.
- Host notResponding / maintenance → host fields + events.
- Datastore erişim → accessible + multipath.
- PSOD / VAMI / cert expiry: log/tool yoksa “bu surface sync edilmiyor”.

## Kapsam kuralı
Kullanıcı cluster / host / datastore / VM adı verdiyse cevap evreni = o kapsam.
`cluster=` ve `name_filter` karıştırma.
