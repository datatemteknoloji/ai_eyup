# OpenShift — Pending / CrashLoopBackOff

## Ayırım
- **Pending:** schedule edilemedi (kaynak, taint, PVC, image pull bekliyor).
- **CrashLoopBackOff:** schedule oldu, container çıkış kodu ≠ 0, restart döngüsü.
- **ImagePullBackOff:** registry/auth/tag.

## Teşhis
```text
oc get pod -A | grep -E 'Pending|CrashLoop|ImagePull|Error'
oc describe pod NAME -n NS
oc logs NAME -n NS --tail=80
oc get events -n NS --sort-by=.lastTimestamp | tail
```

## Sık kökler
Pending: CPU/memory request, node selector, PVC Bound değil, insufficient storage.
CrashLoop: config/env, permission (SCC/fsGroup), liveness çok agresif, bağımlı servis yok.
ImagePull: pull secret, tag latest kaymış, air-gap mirror.

## ainew
OpenShift Chat / Tüm Altyapı: “pending pod”, “crashloop”, proje adı. Linux SSH araçlarını OCP sorusunda kullanma.
