# OpenShift — node NotReady / MachineConfig

## Belirtiler
- `oc get nodes` NotReady, pod’lar diğer node’lara kaçıyor, MachineConfigPool degraded.

## Teşhis
```text
oc get nodes -o wide
oc describe node NAME
oc get mcp
oc get pods -n openshift-machine-config-operator
```

## Sık kökler
- kubelet/CRI-O down, disk pressure, PID/memory pressure.
- MachineConfig drain takılı (PDB).
- Sertifika / proxy / registry.
- Zaman kayması NTP.

## Not
Node NotReady ≠ cluster ölü. API ayaktaysa teşhis mümkün. etcd/API ayrı felaket senaryosu.

## ainew
`openshift_ask` / node listesi. ESXi host NotReady ile karıştırma.
