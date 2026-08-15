# Sanallaştırma — HA / DRS / alarm

## HA
- Host isolate vs APD: VM’ler diğer host’ta restart olmalı; datastore erişilemezse restart da fail.
- Admission control slot yetersiz → failover yok.
- Hostd/vpxa down ≠ guest down.

## DRS
- Soft/hard affinity; maintenance mode tahliye edemez.
- CPU/RAM imbalance tek başına arıza değildir.

## Alarm / event
- ainew: önce `db_virt_alarms` (sync), sonra canlı `vcenter_live_alarms` / tasks.
- Snapshot yaşı, heartbeat, datastore usage alarmları sık yinelenir — kök nedeni alarm adından ayır.

## KubeVirt
vCenter listesi boş olsa bile OCP’te VirtualMachine varsa bu da sanallaştırmadır. “HV kaydı yok = virt yok” deme.
