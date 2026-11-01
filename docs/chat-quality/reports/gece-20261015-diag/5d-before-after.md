# 5d — ÖNCE / SONRA (rapor + KPI; salt-okunur anlık görüntü)

Kaynak: `scripts/diag_report_power_snapshot.py` (önce: bağlama öncesi kod; sonra: bağlama sonrası). Güç durumu = kanonik `chat_quality.power_state` (Running/up/poweredOn/POWERED_ON = açık; Stopped/down/poweredOff/POWERED_OFF = kapalı; Paused/Starting/unknown = ikisi de değil).

| Yer | Alan | ESKİ | YENİ |
|---|---|---|---|
| `kpi:hypervisors.get_quick_stats (vms_powered_on)` | `vms_powered_on` | 1018 | 1466 |
| `kpi:ops_center.executive_summary` | `platforms.virtualization.vm_running_count` | 1448 | 1466 |
| `kpi:virt_ops_center.build_virt_command_center` | `totals.vm_running` | 1129 | 1469 |
| `report:consolidation` | `consolidation_potential.reclaimable_disk_gb` | 73788 | 14348 |
| `report:consolidation` | `consolidation_potential.reclaimable_ram_gb` | 8205.4 | 1385.4 |
| `report:consolidation` | `consolidation_potential.reclaimable_vcpu` | 2371 | 396 |
| `report:consolidation` | `powered_off_vms.count` | 534 | 86 |
| `report:consolidation` | `powered_off_vms.wasted_disk_gb` | 73788 | 14348 |
| `report:consolidation` | `powered_off_vms.wasted_ram_gb` | 8205.4 | 1385.4 |
| `report:consolidation` | `powered_off_vms.wasted_vcpu` | 2371 | 396 |
| `report:consolidation` | `usage_metrics_coverage.powered_on_vms` | 1018 | 1466 |
| `report:executive_summary` | `infrastructure.vm_powered_off` | 534 | 86 |
| `report:executive_summary` | `infrastructure.vm_powered_on` | 1018 | 1466 |
| `report:finance` | `powered_off_savings` | 282658.0 | 47508.0 |
| `report:resource_usage` | `summary.powered_on_vms` | 1018 | 1466 |

**Değişmeyenler:** `virt_monitoring.build_overview inventory.vms_running` 1018 → 1018 (yalnız VMware kapsamı; VMware'de `ilike '%on%'` ile kanonik aynı sonucu veriyor); `openshift_virt_host_metrics` (DB'ye yazan sync; çağrılmadı) için ifade karşılaştırması: `ZZ-FAKE-OpenShift` eski ifade (`'on' in ps`) **103** ↔ kanonik **443** (bu hypervisor'da `Running` 443 VM; eski alt dize ifadesi `Running`'i açık saymıyordu, yalnız status=ONLINE olanları sayıyordu), gerçek `oVirt (OpenShift Virt)` 5 ↔ 5. `virt_reclaim.py` SQL (vm_usage, last_powered_on): ham değerler doğrulandı (poweredOn/POWERED_ON/up; `Running/Stopped` yok) → SQL kanonik `_ON` kümesinden üretildi; sonuç eşdeğer (870 / 886 satır çalıştı).

**Bilerek bağlanmayan 3 yer (BLOKE değil, KARAR BEKLİYOR):** `report_engine.py` içindeki VMware Tools denetimleri (executive öneri satırı, risk raporu `no_tools_vms`, güvenlik/uyum `powered_on_non_compliant`). Kanonik «açık» ile bağlanınca `security_compliance.vmware_tools.powered_on_non_compliant` 8 → **456** oluyordu (KubeVirt/oVirt VM'lerinde VMware Tools kavramı yok; tools_status 'unknown' → «eksik» sayılıyor). Güç durumu değil, tools uygulanabilirliği (hypervisor türü) sorusu; eski davranış korundu, satırlar `5d-ATLANDI` ile işaretli.
