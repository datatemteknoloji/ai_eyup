# OpenShift / KubeVirt / MTV — Backend Fonksiyon Referansı

Bu belge, Atlas'ın OpenShift entegrasyonunun **backend katmanını** başka bir uygulamaya
taşımak için hazırlanmıştır. Yalnızca sunucu tarafı anlatılır; arayüz kapsam dışıdır.

**Baz alınan sürüm:** `e725fcf` commit'i (sekmeli detay ekranı, VM yaşam döngüsü,
proje/olay uçları ve sanallaştırma özeti eklenmeden önceki hal).

**Bağımlılıklar:** `httpx`, `sqlalchemy`, `fastapi`, `cryptography` (Fernet).
Küme ile tüm iletişim **REST üzerinden Bearer token** ile yapılır; `oc`/`kubectl`
ikilisine veya kubeconfig dosyasına ihtiyaç yoktur.

---

## 1. Mimari

Üç servis dosyası, tek bir küme bağlantı kaydını paylaşır:

| Dosya | Sorumluluk |
|---|---|
| `services/openshift_service.py` | Bağlantı kaydı, küme görünürlüğü, kaynak listeleme/YAML, pod & log, iş yükü aksiyonları |
| `services/kubevirt_service.py` | OpenShift Virtualization (KubeVirt) VM listesi, detay, güç, VNC hedefi |
| `services/mtv_service.py` | MTV/Forklift ile VMware → OpenShift VM taşıma |

`kubevirt_service` ve `mtv_service`, `openshift_service`'in `_client`, `_get`,
`get_cluster` yardımcılarını yeniden kullanır. Yani **taşırken önce
`openshift_service` alınmalıdır**.

### Ortak HTTP istemcisi

```python
def _client(cluster: Dict) -> httpx.Client:
    return httpx.Client(
        base_url=cluster["api_url"],                      # https://api.kume:6443
        headers={"Authorization": f"Bearer {cluster['token']}"},
        verify=bool(cluster.get("verify_ssl")),
        timeout=15,
    )

def _get(c, path, params=None) -> Optional[Dict]:
    """404/403 → None (opsiyonel kaynaklar sessizce atlanır), diğer hatalar raise."""
```

Bu `_get` deseni önemlidir: kümede kurulu olmayan operatörler (KubeVirt, MTV, Multus)
404 döner ve kod çökmek yerine "kurulu değil" olarak raporlar.

### Hata tipi

```python
class OpenShiftError(Exception): ...
```
Servis katmanı bu tipi fırlatır; router katmanı HTTP koduna çevirir (genelde 400/502).

---

## 2. Bağlantı yönetimi (`openshift_service`)

Küme kayıtları tek bir `AppSetting` satırında JSON olarak tutulur; **token Fernet ile
şifrelenir ve hiçbir API yanıtında dönmez**.

| Fonksiyon | İmza | Açıklama |
|---|---|---|
| `list_clusters()` | `-> List[Dict]` | Kayıtlı kümeler (token hariç) |
| `get_cluster(cluster_id, include_token=False)` | `-> Optional[Dict]` | Tek küme; `include_token=True` yalnızca servis içi kullanım için |
| `save_cluster(name, api_url, token, verify_ssl, created_by, cluster_id=None)` | `-> Dict` | Ekler veya günceller. `cluster_id` doluysa güncelleme; token boş bırakılırsa mevcut korunur |
| `delete_cluster(cluster_id)` | `-> bool` | Kaydı siler (kümeye dokunmaz) |
| `test_connection(cluster_id)` | `-> {"ok", "version", "api_groups"}` | Erişim + token geçerliliği. 401'i "token geçersiz" mesajına çevirir |

`save_cluster` doğrulaması: `api_url` **https://** ile başlamalı, ad boş olamaz,
yeni kayıtta token zorunlu.

### Gereken küme yetkisi (minimum)

Salt-okunur görünürlük için `cluster-reader` yeterlidir:

```bash
oc create sa atlas-viewer -n default
oc adm policy add-cluster-role-to-user cluster-reader -z atlas-viewer -n default
oc create token atlas-viewer -n default --duration=8760h
```

Yazma özellikleri (iş yükü ölçekleme, pod silme, MTV, VM güç işlemleri) için ek
ClusterRole gerekir — bkz. `mtv_service.RBAC_YAML`.

### Serial console / VNC (KubeVirt)

`cluster-reader` **console/vnc subresource** vermez. SA `403` alırsa:

```bash
oc apply -f - <<'EOF'
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: ainew-kubevirt-console
rules:
  - apiGroups: ["subresources.kubevirt.io"]
    resources: ["virtualmachineinstances/console", "virtualmachineinstances/vnc"]
    verbs: ["get"]
EOF
oc adm policy add-cluster-role-to-user ainew-kubevirt-console -z ainew-viewer -n default
```

(SA adı entegrasyonda kullandığınız isimle aynı olmalı.)

---

## 3. Küme görünürlüğü

### `cluster_overview(cluster_id) -> Dict`

Tek çağrıda kümenin röntgeni. Dönen alanlar:

```jsonc
{
  "cluster":   { "id", "name", "api_url", "verify_ssl" },
  "version":   "v1.34.6",
  "operators": [ { "group": "kubevirt.io", "label": "...", "installed": true } ],
  "migration_ready":   true,          // KubeVirt + CDI + MTV kurulu mu
  "migration_missing": ["..."],
  "nodes": [ {
      "name", "ready", "roles": ["control-plane","worker"],
      "cpu": "8", "memory_gb": 62.8, "kubelet", "os",
      "usage":    { "cpu_millicores": 883, "memory_gb": 20.07 },  // metrics API yoksa null
      "pressure": ["MemoryPressure"]                              // varsa
  } ],
  "capacity": {
      "cpu_cores": 24, "cpu_used_cores": 4.05,
      "memory_gb": 188.4, "memory_used_gb": 73.3,
      "nodes_total": 3, "nodes_ready": 3, "pods_running": 236
  },
  "storage_classes": [ { "name", "provisioner", "default" } ],
  "network_attachment_definitions": [ { "name", "namespaces", "example_ns" } ],  // CRD yoksa null
  "namespaces": { "total": 82, "user": ["..."] },
  "kubevirt_vms": 3                    // KubeVirt kuruluysa
}
```

Aranan operatörler `OPERATOR_GROUPS` sabitinde tanımlıdır:
`kubevirt.io`, `cdi.kubevirt.io`, `forklift.konveyor.io`, `migration.openshift.io`.

### `cluster_health(cluster_id) -> Dict`

ClusterOperator ve node sağlığı: `degraded`, `progressing`, `unavailable` operatörler;
`nodes_not_ready`, `nodes_pressured`; ClusterVersion'dan `version`, `updating`,
`update_message`; MachineConfigPool durumları (`updating`, `degraded`, `ready`).

### `topology(cluster_id, namespace) -> Dict`

Bir namespace'in uygulama haritası — **Istio/servis mesh gerektirmez**.

```jsonc
{
  "namespace": "openshift-mtv",
  "nodes": [ {
      "id": "Deployment/forklift-api", "kind": "Deployment", "name": "forklift-api",
      "app": "forklift",                      // app.kubernetes.io/part-of veya app
      "desired": 1, "ready": 1, "healthy": true,
      "image": "mtv-api-rhel9@sha256:...",
      "pods":     [ { "name", "phase", "healthy" } ],
      "services": [ { "name", "ports": ["443→8443"], "type" } ],
      "routes":   [ { "name", "host", "tls" } ]
  } ],
  "edges": [ { "from", "to", "kind": "connects-to" } ],   // app.openshift.io/connects-to
  "pod_count": 8, "service_count": 8, "route_count": 4
}
```

İlişkilendirme mantığı: iş yükü `spec.selector.matchLabels` → pod'lar;
pod etiketleri → `service.spec.selector`; servis adı → `route.spec.to.name`.

---

## 4. Kaynak listeleme ve YAML

### `RESOURCE_KINDS` tablosu

```python
RESOURCE_KINDS = {
  "deployments":  {"path": "/apis/apps/v1", "ns": True,  "label": "Deployment"},
  "statefulsets": {"path": "/apis/apps/v1", "ns": True,  "label": "StatefulSet"},
  "daemonsets":   {"path": "/apis/apps/v1", "ns": True,  "label": "DaemonSet"},
  "replicasets":  {"path": "/apis/apps/v1", "ns": True,  "label": "ReplicaSet"},
  "pods":         {"path": "/api/v1",       "ns": True,  "label": "Pod"},
  "services":     {"path": "/api/v1",       "ns": True,  "label": "Service"},
  "configmaps":   {"path": "/api/v1",       "ns": True,  "label": "ConfigMap"},
  "persistentvolumeclaims": {"path": "/api/v1", "ns": True, "label": "PVC"},
  "routes":       {"path": "/apis/route.openshift.io/v1", "ns": True, "label": "Route"},
  "virtualmachines": {"path": "/apis/kubevirt.io/v1", "ns": True, "label": "VirtualMachine"},
  "persistentvolumes": {"path": "/api/v1",  "ns": False, "label": "PersistentVolume"},
  "nodes":        {"path": "/api/v1",       "ns": False, "label": "Node"},
  "storageclasses": {"path": "/apis/storage.k8s.io/v1", "ns": False, "label": "StorageClass"},
}
```

Yeni tür eklemek için tabloya bir satır eklemek yeterlidir.

| Fonksiyon | Dönüş |
|---|---|
| `list_resources(cluster_id, kind, namespace=None)` | `[{ "name", "namespace", "age", "info" }]` — `info` türe özel kısa özet (ör. Deployment'ta `2/2`, Route'ta host, Pod'da faz) |
| `get_resource_yaml(cluster_id, kind, name, namespace=None)` | `{ "yaml": "..." }` — `managedFields` temizlenir |

### İş yükü aksiyonları (yazma izni gerekir)

| Fonksiyon | Ne yapar |
|---|---|
| `scale_workload(cluster_id, kind, namespace, name, replicas)` | `/scale` alt kaynağına merge-patch |
| `restart_workload(cluster_id, kind, namespace, name)` | `kubectl rollout restart` eşdeğeri (`kubectl.kubernetes.io/restartedAt` anotasyonu) |
| `delete_pod(cluster_id, namespace, name)` | Pod'u siler; controller varsa yeniden oluşturulur |

---

## 5. Pod, log ve config

| Fonksiyon | Dönüş / not |
|---|---|
| `list_pods(cluster_id, namespace)` | `[{ "name", "phase", "reason", "ready": "2/2", "restarts", "node", "age", "healthy", "containers": [...] }]` |
| `pod_detail(cluster_id, namespace, pod)` | Container durumları, imajlar, koşullar, son olaylar |
| `pod_logs(cluster_id, namespace, pod, container=None, tail=300, previous=False)` | `{ "logs": "..." }`. `tail` 1–5000 arasına sıkıştırılır; `previous=True` çökmüş örneğin logu. 403 → "log okuma yetkisi yok" |
| `list_configmaps(cluster_id, namespace)` | `[{ "name", "keys", "age" }]` |
| `get_configmap(cluster_id, namespace, name)` | `{ "name", "namespace", "data": {...} }` |

> **Güvenlik notu:** Secret okuma bilinçli olarak yoktur. Secret içeriği istenirse
> ayrı bir yetki modeliyle eklenmelidir.

Log uç noktası doğrudan Kubernetes API'sini kullanır:
`GET /api/v1/namespaces/{ns}/pods/{pod}/log?container=…&tailLines=…&timestamps=true`

---

## 6. Depolama ve ağ

### `storage_overview(cluster_id) -> Dict`
```jsonc
{
  "storage_classes": [ { "name", "provisioner", "default", "reclaim", "binding", "params" } ],
  "persistent_volumes": [ { "name", "capacity_gb", "phase", "storage_class",
                            "claim": "ns/pvc-adı", "access_modes", "reclaim" } ],
  "persistent_volume_claims": [ { "name", "namespace", "phase", "capacity_gb",
                                  "storage_class", "volume" } ]
}
```

### `network_overview(cluster_id) -> Dict`
Multus NAD'leri (tip/bridge/VLAN çözümlemesiyle), servisler, route'lar ve
cluster network yapılandırması.

---

## 7. KubeVirt (`kubevirt_service`)

Alan adları VMware/oVirt ile **kasıtlı olarak hizalanmıştır** (`power_state`,
`cpu_count`, `memory_mb`, `ip_address`), böylece çoklu platform arayüzü tek şema kullanır.

| Fonksiyon | Açıklama |
|---|---|
| `list_vms(cluster_id)` | Tüm namespace'lerdeki VM'ler. VMI'lerden canlı IP/node bilgisi, **tek toplu metrics çağrısıyla** VM başına `usage: {cpu_millicores, memory_mb}` |
| `get_vm(cluster_id, ns, name)` | Diskler (kaynak, bus, PVC claim, boyut), NIC'ler (tip/binding/model), guest OS, hostname, node, makine tipi, canlı kullanım, launcher pod adı |
| `power_action(cluster_id, ns, name, action, actor)` | `start`/`stop`/`restart`. `subresources.kubevirt.io` üzerinden. 409 → "zaten çalışıyor/durmuş" olarak yumuşatılır |
| `vnc_target(cluster_id, ns, name)` | Tarayıcı konsolu için websocket hedefi (`wss://…/vnc`, `plain.kubevirt.io` alt protokolü, Bearer token) |

Güç durumu eşlemesi (`_STATE`): `Running/Starting/Migrating → poweredOn`,
`Stopped/Stopping/Provisioning/Terminating → poweredOff`, `Paused → suspended`.

Birim dönüştürücüler: `_mem_to_mb` (`2Gi`→MB), `_size_to_gb`, `_cpu_to_millicores`
(`123456789n`/`250m`/`2` → millicore).

### VNC websocket proxy notu
VNC, ham TCP değil **Kubernetes API alt kaynağı** olarak sunulur. Proxy kurarken
`websockets` kütüphanesinin sürümüne dikkat: 13.x'te başlık parametresi
`extra_headers`, 14+'te `additional_headers`.

---

## 8. MTV / Forklift ile VM taşıma (`mtv_service`)

Atlas taşımanın motorunu yazmaz; kümedeki **Forklift operatörünün CRD'lerini** yönetir:
`Provider` → `NetworkMap` + `StorageMap` → `Plan` → `Migration`.

Sabitler: `NS = "openshift-mtv"`, `FORKLIFT = "/apis/forklift.konveyor.io/v1beta1"`.

### Provider (kaynak vCenter)

| Fonksiyon | Açıklama |
|---|---|
| `list_providers(cluster_id)` | `[{ "name", "type", "url", "ready", "error", "vddk" }]` |
| `create_vsphere_provider(cluster_id, conn_id, actor, vddk_init_image="")` | vCenter kimliğini kümede Secret olarak oluşturur, Provider CR'ını uygular |
| `set_provider_vddk(cluster_id, provider_name, vddk_image, actor)` | VDDK init imajını tanımlar/kaldırır |

> **VDDK kritik:** tanımlanmazsa diskler vCenter'dan HTTPS/curl ile çekilir ve
> taşıma tipik olarak **5–10 kat yavaş** olur.

### Eşleme ve plan

| Fonksiyon | Açıklama |
|---|---|
| `migration_targets(cluster_id)` | Hedef envanteri: storage class'lar + ağlar (pod ağı + NAD'ler, ada göre tekilleştirilmiş) |
| `source_refs(conn_id, vm_morefs)` | **Seçili VM'lerin fiilen kullandığı** kaynak datastore/ağ listesi (tüm envanter değil) + NIC sayısı uyarıları |
| `create_plan(cluster_id, plan_name, provider_name, conn_id, vms, target_namespace, storage_class, network, warm, actor, storage_map=None, network_map=None)` | NetworkMap + StorageMap + Plan CR'larını uygular |
| `list_plans(cluster_id)` | `[{ "name", "state", "vm_count", "target_namespace", "warm", "started", "error" }]` |
| `start_plan(cluster_id, plan_name, actor)` | Migration CR'ı oluşturur |
| `plan_status(cluster_id, plan_name)` | VM başına faz + `pipeline` adımları (Initialize, DiskAllocation, ImageConversion, DiskTransferV2v, VirtualMachineCreation) ve ilerleme |
| `migration_pods(cluster_id, plan_name)` | Taşımanın çalışan pod'ları (virt-v2v/importer) — durum, restart, CPU/bellek |
| `cancel_plan(cluster_id, plan_name, actor)` | Migration CR'ına `spec.cancel` yazar; **plan korunur**, tekrar başlatılabilir |
| `delete_plan(cluster_id, plan_name, actor)` | Plan + eşlemeler + migration kayıtları (taşınmış VM'lere dokunmaz) |

`storage_map` / `network_map` biçimi:
```python
storage_map = [{"source_id": "datastore-12", "storage_class": "nfs-storage"}]
network_map = [{"source_id": "network-7", "type": "multus",
                "name": "localnet", "namespaces": ["default", "vm-migrasyon"]}]
```
Verilmezse tüm kaynaklar tek hedefe eşlenir (geriye uyumlu kaba eşleme).

### Taşımada öğrenilen tuzaklar

Bunlar gerçek bir göç denemesinde ortaya çıktı; yeni uygulamada aynı hatalara
düşmemek için:

1. **Forklift admission webhook'u**, planı oluşturan service account'un **hedef
   namespace'te VM yaratabilmesini** şart koşar. `kubevirt.io/virtualmachines: create`
   izni yoksa plan 400 ile reddedilir.
2. **Multus NAD'i**, planın hedef namespace'inde **veya** `openshift-mtv` içinde
   olmalıdır. Başka namespace'teki kopya reddedilir. NAD namespace'i plan
   oluşturulurken **canlı** çözülmelidir (OVN, NAD'i yeni namespace'e sonradan kopyalar).
3. **Aynı ağa bağlı birden çok NIC** hem Multus hem pod ağında reddedilir
   (*"Multiple VM NICs mapped to the same Multus NAD"*). Plan oluşturmadan önce
   kontrol edip kullanıcıyı uyarmak gerekir.
4. Kubernetes hata gövdesi (`message` + `details.causes`) **yüzeye çıkarılmalıdır**;
   aksi halde kullanıcı yalnızca "oluşturulamadı" görür ve sebep bulunamaz.

### RBAC

`mtv_service.RBAC_YAML` sabiti, kümede bir kez uygulanacak Role/ClusterRole ve
binding'leri içerir (Forklift CRD'leri, secret'lar, KubeVirt okuma + güç işlemleri,
VNC, iş yükü aksiyonları, hedef namespace oluşturma). Panelde kullanıcıya
gösterilip `oc apply -f -` ile uygulatılır.

---

## 9. HTTP uç noktaları (`routers/openshift.py`)

Tümü `/api/openshift` öneki altında.

### Bağlantı ve görünürlük
```
GET    /clusters
POST   /clusters                                   (admin)
DELETE /clusters/{cluster_id}                      (admin)
POST   /clusters/{cluster_id}/test
GET    /clusters/{cluster_id}/health
GET    /clusters/{cluster_id}/overview
GET    /clusters/{cluster_id}/namespaces
GET    /clusters/{cluster_id}/topology?namespace=
```

### Kaynaklar, pod ve log
```
GET    /clusters/{cluster_id}/resource-kinds
GET    /clusters/{cluster_id}/resources?kind=&namespace=
GET    /clusters/{cluster_id}/resource-yaml?kind=&name=&namespace=
GET    /clusters/{cluster_id}/pods?namespace=
GET    /clusters/{cluster_id}/pods/{namespace}/{pod}
GET    /clusters/{cluster_id}/pods/{namespace}/{pod}/logs?container=&tail=&previous=
GET    /clusters/{cluster_id}/configmaps?namespace=
GET    /clusters/{cluster_id}/configmaps/{namespace}/{name}
GET    /clusters/{cluster_id}/storage
GET    /clusters/{cluster_id}/network
POST   /clusters/{cluster_id}/workload/scale        (admin)
POST   /clusters/{cluster_id}/workload/restart      (admin)
POST   /clusters/{cluster_id}/pod/delete            (admin)
```

### KubeVirt
```
GET    /clusters/{cluster_id}/kubevirt/vms
GET    /clusters/{cluster_id}/kubevirt/vms/{namespace}/{name}
POST   /clusters/{cluster_id}/kubevirt/power        (viewer engelli)
```

### MTV
```
GET    /clusters/{cluster_id}/mtv/rbac
GET    /clusters/{cluster_id}/mtv/providers
POST   /clusters/{cluster_id}/mtv/providers                     (admin)
PUT    /clusters/{cluster_id}/mtv/providers/{name}/vddk         (admin)
GET    /clusters/{cluster_id}/mtv/targets
POST   /clusters/{cluster_id}/mtv/source-refs
GET    /clusters/{cluster_id}/mtv/plans
POST   /clusters/{cluster_id}/mtv/plans                         (admin)
GET    /clusters/{cluster_id}/mtv/plans/{plan}/status
GET    /clusters/{cluster_id}/mtv/plans/{plan}/pods
POST   /clusters/{cluster_id}/mtv/plans/{plan}/start            (admin)
POST   /clusters/{cluster_id}/mtv/plans/{plan}/cancel           (admin)
DELETE /clusters/{cluster_id}/mtv/plans/{plan}                  (admin)
```

---

## 10. Taşıma sırasında dikkat edilecekler

1. **Bloklayan I/O:** Tüm servis fonksiyonları senkron `httpx` kullanır. FastAPI'de
   `async def` route içinden çağrılırsa event loop bloklanır. Ya route'u düz `def`
   yapın (FastAPI otomatik threadpool'a alır) ya da `run_in_executor` ile sarın.
2. **Token güvenliği:** `get_cluster(..., include_token=True)` yalnızca servis içinde
   kullanılmalı; API yanıtlarına asla sızmamalı.
3. **Opsiyonel operatörler:** `_get`'in 404/403 → `None` davranışı korunmalı; aksi
   halde KubeVirt/MTV kurulu olmayan kümede tüm sayfa çöker.
4. **Metrics API:** `metrics.k8s.io` her kümede olmayabilir. Kullanım alanları
   (`usage`, `capacity.*_used_*`) `None` olabilir; arayüz bunu karşılamalıdır.
5. **Zaman aşımı:** İstemci 15 sn ile sınırlıdır. Büyük kümelerde `list_resources`
   ve `topology` için bu değeri artırmak gerekebilir.
6. **Ölçek:** `list_resources` ve `topology` bir namespace'i tam tarar. Binlerce
   nesneli namespace'lerde sunucu tarafı sayfalama eklenmelidir.
