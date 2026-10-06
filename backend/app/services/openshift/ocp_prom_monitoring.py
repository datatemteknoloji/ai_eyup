"""
OpenShift Prometheus monitoring.

Şablonlar:
  - views (varsayılan): Kubernetes Views — Global / Namespaces / Nodes / Pods
    (Grafana OpenShift klasörü ile uyumlu PromQL; cluster= filtresi yok — tek cluster)
  - gpu: DCGM GPU (kenarda seçilebilir)
  - kubevirt: kubevirt_vmi_* (kenarda seçilebilir)

API/Timescale SoT'a dokunmaz; bound openshift Prometheus kaynağından okur.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional

import httpx

from app.services.monitoring_sources import (
    load_sources_from_db,
    load_sources_runtime,
    list_by_binding,
    resolve,
    prom_base_url,
    prom_headers,
    prom_verify,
    MonitoringSource,
)

logger = logging.getLogger(__name__)

TEMPLATES = [
    {"id": "views", "title": "Kubernetes Views", "default": True,
     "views": ["global", "namespaces", "nodes", "pods"]},
    {"id": "gpu", "title": "GPU / DCGM", "default": False},
    {"id": "kubevirt", "title": "KubeVirt VMI", "default": False},
]

# Catalog: id → (promql template, unit, family)
DCGM_CATALOG = [
    {"id": "gpu_util", "title": "GPU Utilization", "unit": "%", "family": "gpu",
     "help": "GPU işlem biriminin anlık kullanım yüzdesi. Yüksek ve sürekli değerler iş yükünün GPU’yu doldurduğunu gösterir.",
     "query": "DCGM_FI_DEV_GPU_UTIL"},
    {"id": "gpu_temp", "title": "GPU Temperature", "unit": "°C", "family": "gpu",
     "help": "GPU sıcaklığı (°C). Susturulmuş/soğutma sorunlarında yükselir; termal throttle riskini izlemek için kullanılır.",
     "query": "DCGM_FI_DEV_GPU_TEMP"},
    {"id": "gpu_power", "title": "GPU Power", "unit": "W", "family": "gpu",
     "help": "GPU’nun çektiği güç (Watt). Enerji bütçesi ve power-limit / throttle analizinde kullanılır.",
     "query": "DCGM_FI_DEV_POWER_USAGE"},
    {"id": "gpu_fb_used", "title": "GPU Framebuffer Used", "unit": "MiB", "family": "gpu",
     "help": "GPU bellek (framebuffer) kullanımı. OOM / model sığmama sorunlarında yükselir.",
     "query": "DCGM_FI_DEV_FB_USED"},
    {"id": "gpu_fb_free", "title": "GPU Framebuffer Free", "unit": "MiB", "family": "gpu",
     "help": "Boş GPU bellek miktarı. Düşükse yeni iş yükü veya daha büyük modeller sığmayabilir.",
     "query": "DCGM_FI_DEV_FB_FREE"},
    {"id": "gpu_sm_clock", "title": "GPU SM Clock", "unit": "MHz", "family": "gpu",
     "help": "Streaming Multiprocessor saat hızı. Throttle veya power-limit durumunda düşebilir.",
     "query": "DCGM_FI_DEV_SM_CLOCK"},
    {"id": "gpu_tensor", "title": "Tensor Core Utilization", "unit": "%", "family": "gpu",
     "help": "Tensor core kullanım oranı. AI/ML eğitim ve çıkarım yoğunluğunu gösterir.",
     "query": "DCGM_FI_DEV_TENSOR_UTIL"},
]

KUBEVIRT_CATALOG = [
    {"id": "vmi_cpu", "title": "VMI CPU Usage", "unit": "cores", "family": "kubevirt",
     "help": "OpenShift Virtualization sanal makinelerinin (VMI) CPU kullanım hızı (çekirdek). Her VMI kendi serisi olarak görünür.",
     "query": "rate(kubevirt_vmi_cpu_usage_seconds_total[5m])"},
    {"id": "vmi_memory", "title": "VMI Memory Used", "unit": "bytes", "family": "kubevirt",
     "help": "VMI’nin kullandığı bellek miktarı. Konuk işletim sistemi + hipervizör bakışındaki working set’e yakındır.",
     "query": "kubevirt_vmi_memory_used_bytes"},
    {"id": "vmi_storage_read", "title": "VMI Storage Read", "unit": "B/s", "family": "kubevirt",
     "help": "VMI disk okuma trafiği (bayt/sn). Yavaş disk veya yüksek I/O şikayetlerinde okuma tarafını ayırır.",
     "query": "rate(kubevirt_vmi_storage_read_traffic_bytes_total[5m])"},
    {"id": "vmi_storage_write", "title": "VMI Storage Write", "unit": "B/s", "family": "kubevirt",
     "help": "VMI disk yazma trafiği (bayt/sn). Yoğun yazma, snapshot veya yedekleme etkisini gösterir.",
     "query": "rate(kubevirt_vmi_storage_write_traffic_bytes_total[5m])"},
    {"id": "vmi_net_rx", "title": "VMI Network Receive", "unit": "B/s", "family": "kubevirt",
     "help": "VMI’ye gelen ağ trafiği (bayt/sn). Servis/VM arası giriş bant genişliğini izler.",
     "query": "rate(kubevirt_vmi_network_receive_bytes_total[5m])"},
    {"id": "vmi_net_tx", "title": "VMI Network Transmit", "unit": "B/s", "family": "kubevirt",
     "help": "VMI’den giden ağ trafiği (bayt/sn). Çıkış bant genişliği ve olası network saturation için.",
     "query": "rate(kubevirt_vmi_network_transmit_bytes_total[5m])"},
]

# Grafana Kubernetes / Views — cluster label yok (tek cluster OCP)
# pick: grafik serisi için çoklu seçim boyutu; yoksa aggregate (her zaman çizilir)
# Boş seçimde pick’li chart veri döndürmez (Top-N yok).
VIEWS_CATALOG = [
    # Grafana k8s_views_* birebir (cluster/$job yok; rate→5m; increase→1h; windows hedefleri atlandı).
    {"id": "vg_global_cpu_usage", "title": "Global CPU  Usage", "unit": "cores", "family": "views_global", "pick": None, "queries": [{"legend": "Real Linux", "expr": "avg(sum by (instance, cpu) (rate(node_cpu_seconds_total{mode!~\"idle|iowait|steal\"}[5m])))"}, {"legend": "Requests", "expr": "sum(kube_pod_container_resource_requests{resource=\"cpu\"}) / sum(machine_cpu_cores)"}, {"legend": "Limits", "expr": "sum(kube_pod_container_resource_limits{resource=\"cpu\"}) / sum(machine_cpu_cores)"}]},
    {"id": "vg_global_ram_usage", "title": "Global RAM Usage", "unit": "bytes", "family": "views_global", "pick": None, "queries": [{"legend": "Real Linux", "expr": "sum(node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes) / sum(node_memory_MemTotal_bytes)"}, {"legend": "Requests", "expr": "sum(kube_pod_container_resource_requests{resource=\"memory\"}) / sum(machine_memory_bytes)"}, {"legend": "Limits", "expr": "sum(kube_pod_container_resource_limits{resource=\"memory\"}) / sum(machine_memory_bytes)"}]},
    {"id": "vg_nodes", "title": "Nodes", "unit": "", "family": "views_global", "pick": None, "query": "count(count by (node) (kube_node_info))"},
    {"id": "vg_kubernetes_resource_count", "title": "Kubernetes Resource Count", "unit": "", "family": "views_global", "pick": None, "queries": [{"legend": "Namespaces", "expr": "sum(kube_namespace_labels)"}, {"legend": "Running Containers", "expr": "sum(kube_pod_container_status_running)"}, {"legend": "Running Pods", "expr": "sum(kube_pod_status_phase{phase=\"Running\"})"}, {"legend": "Services", "expr": "sum(kube_service_info)"}, {"legend": "Endpoints", "expr": "sum(kube_endpoint_info)"}, {"legend": "Ingresses", "expr": "sum(kube_ingress_info)"}, {"legend": "Deployments", "expr": "sum(kube_deployment_labels)"}, {"legend": "Statefulsets", "expr": "sum(kube_statefulset_labels)"}, {"legend": "Daemonsets", "expr": "sum(kube_daemonset_labels)"}, {"legend": "Persistent Volume Claims", "expr": "sum(kube_persistentvolumeclaim_info)"}, {"legend": "Horizontal Pod Autoscalers", "expr": "sum(kube_hpa_labels)"}, {"legend": "Configmaps", "expr": "sum(kube_configmap_info)"}, {"legend": "Secrets", "expr": "sum(kube_secret_info)"}, {"legend": "Network Policies", "expr": "sum(kube_networkpolicy_labels)"}, {"legend": "Nodes", "expr": "count(count by (node) (kube_node_info))"}]},
    {"id": "vg_namespaces", "title": "Namespaces", "unit": "", "family": "views_global", "pick": None, "query": "count(kube_namespace_labels)"},
    {"id": "vg_cpu_usage", "title": "CPU Usage", "unit": "cores", "family": "views_global", "pick": None, "queries": [{"legend": "Real Linux", "expr": "sum(rate(node_cpu_seconds_total{mode!~\"idle|iowait|steal\"}[5m]))"}, {"legend": "Requests", "expr": "sum(kube_pod_container_resource_requests{resource=\"cpu\"})"}, {"legend": "Limits", "expr": "sum(kube_pod_container_resource_limits{resource=\"cpu\"})"}, {"legend": "Total", "expr": "sum(machine_cpu_cores)"}]},
    {"id": "vg_ram_usage", "title": "RAM Usage", "unit": "bytes", "family": "views_global", "pick": None, "queries": [{"legend": "Real Linux", "expr": "sum(node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes)"}, {"legend": "Requests", "expr": "sum(kube_pod_container_resource_requests{resource=\"memory\"})"}, {"legend": "Limits", "expr": "sum(kube_pod_container_resource_limits{resource=\"memory\"})"}, {"legend": "Total", "expr": "sum(machine_memory_bytes)"}]},
    {"id": "vg_running_pods", "title": "Running Pods", "unit": "", "family": "views_global", "pick": None, "query": "sum(kube_pod_status_phase{phase=\"Running\"})"},
    {"id": "vg_cluster_cpu_utilization", "title": "Cluster CPU Utilization", "unit": "cores", "family": "views_global", "pick": None, "query": "avg(sum by (instance, cpu) (rate(node_cpu_seconds_total{mode!~\"idle|iowait|steal\"}[5m])))"},
    {"id": "vg_cluster_memory_utilization", "title": "Cluster Memory Utilization", "unit": "bytes", "family": "views_global", "pick": None, "query": "sum(node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes) / sum(node_memory_MemTotal_bytes)"},
    {"id": "vg_cpu_utilization_by_namespace", "title": "CPU Utilization by namespace", "unit": "cores", "family": "views_global", "pick": None, "query": "sum(rate(container_cpu_usage_seconds_total{image!=\"\"}[5m])) by (namespace)"},
    {"id": "vg_memory_utilization_by_namespace", "title": "Memory Utilization by namespace", "unit": "bytes", "family": "views_global", "pick": None, "query": "sum(container_memory_working_set_bytes{image!=\"\"}) by (namespace)"},
    {"id": "vg_cpu_utilization_by_instance", "title": "CPU Utilization by instance", "unit": "cores", "family": "views_global", "pick": None, "query": "avg(sum by (instance, cpu) (rate(node_cpu_seconds_total{mode!~\"idle|iowait|steal\"}[5m]))) by (instance)"},
    {"id": "vg_memory_utilization_by_instance", "title": "Memory Utilization by instance", "unit": "bytes", "family": "views_global", "pick": None, "query": "sum(node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes) by (instance)"},
    {"id": "vg_cpu_throttled_seconds_by_namespace", "title": "CPU Throttled seconds by namespace", "unit": "cores", "family": "views_global", "pick": None, "query": "sum(rate(container_cpu_cfs_throttled_seconds_total{image!=\"\"}[5m])) by (namespace) > 0"},
    {"id": "vg_cpu_core_throttled_by_instance", "title": "CPU Core Throttled by instance", "unit": "cores", "family": "views_global", "pick": None, "query": "sum(rate(node_cpu_core_throttles_total[5m])) by (instance)"},
    {"id": "vg_kubernetes_pods_qos_classes", "title": "Kubernetes Pods QoS classes", "unit": "", "family": "views_global", "pick": None, "queries": [{"legend": "{{ qos_class }} pods", "expr": "sum(kube_pod_status_qos_class) by (qos_class)"}, {"legend": "Total pods", "expr": "sum(kube_pod_info)"}]},
    {"id": "vg_kubernetes_pods_status_reason", "title": "Kubernetes Pods Status Reason", "unit": "", "family": "views_global", "pick": None, "query": "sum(kube_pod_status_reason) by (reason)"},
    {"id": "vg_oom_events_by_namespace", "title": "OOM Events by namespace", "unit": "", "family": "views_global", "pick": None, "query": "sum(increase(container_oom_events_total[1h])) by (namespace) > 0"},
    {"id": "vg_container_restarts_by_namespace", "title": "Container Restarts by namespace", "unit": "", "family": "views_global", "pick": None, "query": "sum(increase(kube_pod_container_status_restarts_total[1h])) by (namespace) > 0"},
    {"id": "vg_global_network_utilization_by_device", "title": "Global Network Utilization by device", "unit": "B/s", "family": "views_global", "pick": None, "queries": [{"legend": "Received : {{ device }}", "expr": "sum(rate(node_network_receive_bytes_total{device!~\"(veth|azv|lxc).*\"}[5m])) by (device)"}, {"legend": "Transmitted : {{ device }}", "expr": "- sum(rate(node_network_transmit_bytes_total{device!~\"(veth|azv|lxc).*\"}[5m])) by (device)"}]},
    {"id": "vg_network_saturation_packets_dropped", "title": "Network Saturation - Packets dropped", "unit": "B/s", "family": "views_global", "pick": None, "queries": [{"legend": "Linux Packets dropped (receive)", "expr": "sum(rate(node_network_receive_drop_total[5m]))"}, {"legend": "Linux Packets dropped (transmit)", "expr": "- sum(rate(node_network_transmit_drop_total[5m]))"}]},
    {"id": "vg_network_received_by_namespace", "title": "Network Received by namespace", "unit": "B/s", "family": "views_global", "pick": None, "queries": [{"legend": "__auto", "expr": "sum(rate(container_network_receive_bytes_total[5m])) by (namespace)"}, {"legend": "Transmitted : {{ namespace }}", "expr": "- sum(rate(container_network_transmit_bytes_total[5m])) by (namespace)"}]},
    {"id": "vg_total_network_received_with_all_virtual_devices_", "title": "Total Network Received (with all virtual devices) by instance", "unit": "B/s", "family": "views_global", "pick": None, "queries": [{"legend": "Received bytes in {{ instance }}", "expr": "sum(rate(node_network_receive_bytes_total[5m])) by (instance)"}, {"legend": "Transmitted bytes in {{ instance }}", "expr": "- sum(rate(node_network_transmit_bytes_total[5m])) by (instance)"}]},
    {"id": "vg_network_received_without_loopback_by_instance", "title": "Network Received (without loopback)  by instance", "unit": "B/s", "family": "views_global", "pick": None, "queries": [{"legend": "Received bytes in {{ instance }}", "expr": "sum(rate(node_network_receive_bytes_total{device!~\"(veth|azv|lxc|lo).*\"}[5m])) by (instance)"}, {"legend": "Transmitted bytes in {{ instance }}", "expr": "- sum(rate(node_network_transmit_bytes_total{device!~\"(veth|azv|lxc|lo).*\"}[5m])) by (instance)"}]},
    {"id": "vg_network_received_loopback_only_by_instance", "title": "Network Received (loopback only) by instance", "unit": "B/s", "family": "views_global", "pick": None, "queries": [{"legend": "Received bytes in {{ instance }}", "expr": "sum(rate(node_network_receive_bytes_total{device=\"lo\"}[5m])) by (instance)"}, {"legend": "Transmitted bytes in {{ instance }}", "expr": "- sum(rate(node_network_transmit_bytes_total{device=\"lo\"}[5m])) by (instance)"}]},
    {"id": "vn_namespace_s_usage_on_total_cluster_cpu_in", "title": "Namespace(s) usage on total cluster CPU in %", "unit": "%", "family": "views_ns", "pick": None, "scope": "namespace", "query": "sum(rate(container_cpu_usage_seconds_total{namespace=~\"$namespace\", image!=\"\"}[5m])) / sum(machine_cpu_cores)"},
    {"id": "vn_namespace_s_usage_on_total_cluster_ram_in", "title": "Namespace(s) usage on total cluster RAM in %", "unit": "%", "family": "views_ns", "pick": None, "scope": "namespace", "query": "sum(container_memory_working_set_bytes{namespace=~\"$namespace\", image!=\"\"}) / sum(machine_memory_bytes)"},
    {"id": "vn_kubernetes_resource_count", "title": "Kubernetes Resource Count", "unit": "", "family": "views_ns", "pick": None, "scope": "namespace", "queries": [{"legend": "Running Pods", "expr": "sum(kube_pod_info{namespace=~\"$namespace\"})"}, {"legend": "Services", "expr": "sum(kube_service_info{namespace=~\"$namespace\"})"}, {"legend": "Ingresses", "expr": "sum(kube_ingress_info{namespace=~\"$namespace\"})"}, {"legend": "Deployments", "expr": "sum(kube_deployment_labels{namespace=~\"$namespace\"})"}, {"legend": "Statefulsets", "expr": "sum(kube_statefulset_labels{namespace=~\"$namespace\"})"}, {"legend": "Daemonsets", "expr": "sum(kube_daemonset_labels{namespace=~\"$namespace\"})"}, {"legend": "Persistent Volume Claims", "expr": "sum(kube_persistentvolumeclaim_info{namespace=~\"$namespace\"})"}, {"legend": "Horizontal Pod Autoscalers", "expr": "sum(kube_hpa_labels{namespace=~\"$namespace\"})"}, {"legend": "Configmaps", "expr": "sum(kube_configmap_info{namespace=~\"$namespace\"})"}, {"legend": "Secrets", "expr": "sum(kube_secret_info{namespace=~\"$namespace\"})"}, {"legend": "Network Policies", "expr": "sum(kube_networkpolicy_labels{namespace=~\"$namespace\"})"}]},
    {"id": "vn_namespace_s_cpu_usage_in_cores", "title": "Namespace(s) CPU Usage in cores", "unit": "cores", "family": "views_ns", "pick": None, "scope": "namespace", "queries": [{"legend": "Real", "expr": "sum(rate(container_cpu_usage_seconds_total{namespace=~\"$namespace\", image!=\"\"}[5m]))"}, {"legend": "Requests", "expr": "sum(kube_pod_container_resource_requests{namespace=~\"$namespace\", resource=\"cpu\"} and on(namespace, pod) max by (namespace, pod) (kube_pod_status_phase{phase=\"Running\", namespace=~\"$namespace\"} == 1))"}, {"legend": "Limits", "expr": "sum(kube_pod_container_resource_limits{namespace=~\"$namespace\", resource=\"cpu\"} and on(namespace, pod) max by (namespace, pod) (kube_pod_status_phase{phase=\"Running\", namespace=~\"$namespace\"} == 1))"}, {"legend": "Cluster Total", "expr": "sum(machine_cpu_cores)"}]},
    {"id": "vn_namespace_s_ram_usage_in_bytes", "title": "Namespace(s) RAM Usage in bytes", "unit": "bytes", "family": "views_ns", "pick": None, "scope": "namespace", "queries": [{"legend": "Real", "expr": "sum(container_memory_working_set_bytes{namespace=~\"$namespace\", image!=\"\"})"}, {"legend": "Requests", "expr": "sum(kube_pod_container_resource_requests{namespace=~\"$namespace\", resource=\"memory\"} and on(namespace, pod) max by (namespace, pod) (kube_pod_status_phase{phase=\"Running\", namespace=~\"$namespace\"} == 1))"}, {"legend": "Limits", "expr": "sum(kube_pod_container_resource_limits{namespace=~\"$namespace\", resource=\"memory\"} and on(namespace, pod) max by (namespace, pod) (kube_pod_status_phase{phase=\"Running\", namespace=~\"$namespace\"} == 1))"}, {"legend": "Cluster Total", "expr": "sum(machine_memory_bytes)"}]},
    {"id": "vn_cpu_usage_by_pod", "title": "CPU usage by Pod", "unit": "cores", "family": "views_ns", "pick": None, "scope": "namespace", "query": "sum(rate(container_cpu_usage_seconds_total{namespace=~\"$namespace\", image!=\"\", pod=~\"$pod\"}[5m])) by (pod)"},
    {"id": "vn_memory_usage_by_pod", "title": "Memory usage by Pod", "unit": "bytes", "family": "views_ns", "pick": None, "scope": "namespace", "query": "sum(container_memory_working_set_bytes{namespace=~\"$namespace\", image!=\"\", pod=~\"$pod\"}) by (pod)"},
    {"id": "vn_cpu_throttled_seconds_by_pod", "title": "CPU Throttled seconds by pod", "unit": "cores", "family": "views_ns", "pick": None, "scope": "namespace", "query": "sum(rate(container_cpu_cfs_throttled_seconds_total{namespace=~\"$namespace\", image!=\"\", pod=~\"$pod\"}[5m])) by (pod) > 0"},
    {"id": "vn_kubernetes_pods_qos_classes", "title": "Kubernetes Pods QoS classes", "unit": "", "family": "views_ns", "pick": None, "scope": "namespace", "queries": [{"legend": "{{ qos_class }} pods", "expr": "sum(kube_pod_status_qos_class{namespace=~\"$namespace\"}) by (qos_class)"}, {"legend": "Total pods", "expr": "sum(kube_pod_info{namespace=~\"$namespace\"})"}]},
    {"id": "vn_kubernetes_pods_status_reason", "title": "Kubernetes Pods Status Reason", "unit": "", "family": "views_ns", "pick": None, "query": "sum(kube_pod_status_reason) by (reason)"},
    {"id": "vn_oom_events_by_namespace_pod", "title": "OOM Events by namespace, pod", "unit": "", "family": "views_ns", "pick": None, "scope": "namespace", "query": "sum(increase(container_oom_events_total{namespace=~\"$namespace\"}[1h])) by (namespace, pod) > 0"},
    {"id": "vn_container_restarts_by_namespace_pod", "title": "Container Restarts by namespace, pod", "unit": "", "family": "views_ns", "pick": None, "scope": "namespace", "query": "sum(increase(kube_pod_container_status_restarts_total{namespace=~\"$namespace\"}[1h])) by (namespace, pod) > 0"},
    {"id": "vn_nb_of_pods_by_state", "title": "Nb of pods by state", "unit": "", "family": "views_ns", "pick": None, "scope": "namespace", "queries": [{"legend": "Ready", "expr": "sum(kube_pod_container_status_ready{namespace=~\"$namespace\", pod=~\"$pod\"})"}, {"legend": "Running", "expr": "sum(kube_pod_container_status_running{namespace=~\"$namespace\", pod=~\"$pod\"})"}, {"legend": "Waiting", "expr": "sum(kube_pod_container_status_waiting{namespace=~\"$namespace\"})"}, {"legend": "Restarts Total", "expr": "sum(kube_pod_container_status_restarts_total{namespace=~\"$namespace\"})"}, {"legend": "Terminated", "expr": "sum(kube_pod_container_status_terminated{namespace=~\"$namespace\"})"}]},
    {"id": "vn_nb_of_containers_by_pod", "title": "Nb of containers by pod", "unit": "", "family": "views_ns", "pick": None, "scope": "namespace", "query": "sum(kube_pod_container_info{namespace=~\"$namespace\", pod=~\"$pod\"}) by (pod)"},
    {"id": "vn_replicas_available_by_deployment", "title": "Replicas available by deployment", "unit": "", "family": "views_ns", "pick": None, "scope": "namespace", "query": "sum(kube_deployment_status_replicas_available{namespace=~\"$namespace\"}) by (deployment)"},
    {"id": "vn_replicas_unavailable_by_deployment", "title": "Replicas unavailable by deployment", "unit": "", "family": "views_ns", "pick": None, "scope": "namespace", "query": "sum(kube_deployment_status_replicas_unavailable{namespace=~\"$namespace\", pod=~\"$pod\"}) by (deployment)"},
    {"id": "vn_pods_with_unexpected_status", "title": "Pods with unexpected status", "unit": "", "family": "views_ns", "pick": None, "scope": "namespace", "query": "sum(kube_pod_status_phase{phase!~\"Running|Succeeded\", namespace=~\"$namespace\"}) by (pod) > 0"},
    {"id": "vn_container_image_used", "title": "Container Image Used", "unit": "cores", "family": "views_ns", "pick": None, "scope": "namespace", "query": "count(rate(container_cpu_usage_seconds_total{namespace=~\"$namespace\", image!=\"\", pod=~\"$pod\"}[5m])) by (image)"},
    {"id": "vn_persistent_volumes_capacity_and_usage_in", "title": "Persistent Volumes - Capacity and usage in %", "unit": "%", "family": "views_ns", "pick": None, "scope": "namespace", "query": "max(kubelet_volume_stats_used_bytes{namespace=~\"$namespace\"}) by (persistentvolumeclaim, namespace) / max(kubelet_volume_stats_capacity_bytes{namespace=~\"$namespace\"}) by (persistentvolumeclaim, namespace)"},
    {"id": "vn_persistent_volumes_capacity_and_usage_in_bytes", "title": "Persistent Volumes - Capacity and usage in bytes", "unit": "bytes", "family": "views_ns", "pick": None, "scope": "namespace", "queries": [{"legend": "{{ namespace }} - {{ persistentvolumeclaim }} - Used", "expr": "max(kubelet_volume_stats_used_bytes{namespace=~\"$namespace\"}) by (persistentvolumeclaim, namespace)"}, {"legend": "{{ namespace }} - {{ persistentvolumeclaim }} - Capacity", "expr": "max(kubelet_volume_stats_capacity_bytes{namespace=~\"$namespace\"}) by (persistentvolumeclaim, namespace)"}]},
    {"id": "vn_persistent_volumes_inodes", "title": "Persistent Volumes - Inodes", "unit": "bytes", "family": "views_ns", "pick": None, "scope": "namespace", "query": "1 - (sum(kubelet_volume_stats_inodes_used{namespace=~\"$namespace\"}) by (persistentvolumeclaim) / sum(kubelet_volume_stats_inodes{namespace=~\"$namespace\"}) by (persistentvolumeclaim))"},
    {"id": "vn_network_bandwidth_by_pod", "title": "Network - Bandwidth by pod", "unit": "B/s", "family": "views_ns", "pick": None, "scope": "namespace", "queries": [{"legend": "Received - {{ pod }}", "expr": "sum(rate(container_network_receive_bytes_total{namespace=~\"$namespace\", pod=~\"$pod\"}[5m])) by (pod)"}, {"legend": "Transmitted - {{ pod }}", "expr": "- sum(rate(container_network_transmit_bytes_total{namespace=~\"$namespace\", pod=~\"$pod\"}[5m])) by (pod)"}]},
    {"id": "vn_network_packets_rate_by_pod", "title": "Network - Packets Rate by pod", "unit": "B/s", "family": "views_ns", "pick": None, "scope": "namespace", "queries": [{"legend": "Received - {{ pod }}", "expr": "sum(rate(container_network_receive_packets_total{namespace=~\"$namespace\", pod=~\"$pod\"}[5m])) by (pod)"}, {"legend": "Transmitted - {{ pod }}", "expr": "- sum(rate(container_network_transmit_packets_total{namespace=~\"$namespace\", pod=~\"$pod\"}[5m])) by (pod)"}]},
    {"id": "vn_network_packets_dropped_by_pod", "title": "Network - Packets Dropped by pod", "unit": "B/s", "family": "views_ns", "pick": None, "scope": "namespace", "queries": [{"legend": "Received - {{ pod }}", "expr": "sum(rate(container_network_receive_packets_dropped_total{namespace=~\"$namespace\", pod=~\"$pod\"}[5m])) by (pod)"}, {"legend": "Transmitted - {{ pod }}", "expr": "- sum(rate(container_network_transmit_packets_dropped_total{namespace=~\"$namespace\", pod=~\"$pod\"}[5m])) by (pod)"}]},
    {"id": "vn_network_errors_by_pod", "title": "Network - Errors by pod", "unit": "B/s", "family": "views_ns", "pick": None, "scope": "namespace", "queries": [{"legend": "Received - {{ pod }}", "expr": "sum(rate(container_network_receive_errors_total{namespace=~\"$namespace\", pod=~\"$pod\"}[5m])) by (pod)"}, {"legend": "Transmitted - {{ pod }}", "expr": "- sum(rate(container_network_transmit_errors_total{namespace=~\"$namespace\", pod=~\"$pod\"}[5m])) by (pod)"}]},
    {"id": "vd_cpu_usage", "title": "CPU  Usage", "unit": "cores", "family": "views_nodes", "pick": 'instance', "query": "avg(sum by (cpu) (rate(node_cpu_seconds_total{mode!~\"idle|iowait|steal\", instance=~\"$instance\"}[5m])))"},
    {"id": "vd_ram_usage", "title": "RAM Usage", "unit": "bytes", "family": "views_nodes", "pick": 'instance', "query": "sum(node_memory_MemTotal_bytes{instance=~\"$instance\"} - node_memory_MemAvailable_bytes{instance=~\"$instance\"}) / sum(node_memory_MemTotal_bytes{instance=~\"$instance\"})"},
    {"id": "vd_pods_on_node", "title": "Pods on node", "unit": "", "family": "views_nodes", "pick": 'node', "query": "sum(kube_pod_info{node=~\"$node\"})"},
    {"id": "vd_list_of_pods_on_node_node", "title": "List of pods on node ($node)", "unit": "", "family": "views_nodes", "pick": 'node', "query": "kube_pod_info{node=~\"$node\"}"},
    {"id": "vd_cpu_used", "title": "CPU Used", "unit": "cores", "family": "views_nodes", "pick": 'instance', "query": "sum(rate(node_cpu_seconds_total{mode!~\"idle|iowait|steal\", instance=~\"$instance\"}[5m]))"},
    {"id": "vd_cpu_total", "title": "CPU Total", "unit": "cores", "family": "views_nodes", "pick": 'node', "query": "sum(machine_cpu_cores{node=~\"$node\"})"},
    {"id": "vd_ram_used", "title": "RAM Used", "unit": "bytes", "family": "views_nodes", "pick": 'instance', "query": "sum(node_memory_MemTotal_bytes{instance=~\"$instance\"} - node_memory_MemAvailable_bytes{instance=~\"$instance\"})"},
    {"id": "vd_ram_total", "title": "RAM Total", "unit": "bytes", "family": "views_nodes", "pick": 'node', "query": "sum(machine_memory_bytes{node=~\"$node\"})"},
    {"id": "vd_uptime", "title": "uptime", "unit": "", "family": "views_nodes", "pick": 'instance', "query": "sum(node_time_seconds{instance=~\"$instance\"} - node_boot_time_seconds{instance=~\"$instance\"})"},
    {"id": "vd_cpu_usage_2", "title": "CPU Usage", "unit": "%", "family": "views_nodes", "pick": 'instance', "query": "avg(rate(node_cpu_seconds_total{instance=~\"$instance\"}[5m]) * 100) by (mode)"},
    {"id": "vd_memory_usage", "title": "Memory Usage", "unit": "bytes", "family": "views_nodes", "pick": 'instance', "queries": [{"legend": "RAM Used", "expr": "node_memory_MemTotal_bytes{instance=~\"$instance\"} - node_memory_MemFree_bytes{instance=~\"$instance\"} - (node_memory_Cached_bytes{instance=~\"$instance\"} + node_memory_Buffers_bytes{instance=~\"$instance\"})"}, {"legend": "RAM Total", "expr": "node_memory_MemTotal_bytes{instance=~\"$instance\"}"}, {"legend": "RAM Cache", "expr": "node_memory_Cached_bytes{instance=~\"$instance\"}"}, {"legend": "RAM Buffer", "expr": "node_memory_Buffers_bytes{instance=~\"$instance\"}"}, {"legend": "RAM Free", "expr": "node_memory_MemFree_bytes{instance=~\"$instance\"}"}, {"legend": "SWAP Used", "expr": "node_memory_SwapTotal_bytes{instance=~\"$instance\"} - node_memory_SwapFree_bytes{instance=~\"$instance\"}"}, {"legend": "SWAP Total", "expr": "node_memory_SwapTotal_bytes{instance=~\"$instance\"}"}]},
    {"id": "vd_cpu_usage_by_pod", "title": "CPU usage by Pod", "unit": "cores", "family": "views_nodes", "pick": 'node', "query": "sum(rate(container_cpu_usage_seconds_total{node=~\"$node\", image!=\"\"}[5m])) by (pod)"},
    {"id": "vd_memory_usage_by_pod", "title": "Memory usage by Pod", "unit": "bytes", "family": "views_nodes", "pick": 'node', "query": "sum(container_memory_working_set_bytes{node=~\"$node\", image!=\"\"}) by (pod)"},
    {"id": "vd_number_of_cpu_core_throttled", "title": "Number of CPU Core Throttled", "unit": "cores", "family": "views_nodes", "pick": 'instance', "query": "sum(rate(node_cpu_core_throttles_total{instance=~\"$instance\"}[5m]))"},
    {"id": "vd_system_load", "title": "System Load", "unit": "", "family": "views_nodes", "pick": 'instance', "queries": [{"legend": "1m", "expr": "node_load1{instance=~\"$instance\"}"}, {"legend": "5m", "expr": "node_load5{instance=~\"$instance\"}"}, {"legend": "15m", "expr": "node_load15{instance=~\"$instance\"}"}]},
    {"id": "vd_context_switches_interrupts", "title": "Context Switches & Interrupts", "unit": "", "family": "views_nodes", "pick": 'instance', "queries": [{"legend": "Context switches", "expr": "rate(node_context_switches_total{instance=~\"$instance\"}[5m])"}, {"legend": "Interrupts", "expr": "rate(node_intr_total{instance=~\"$instance\"}[5m])"}]},
    {"id": "vd_file_descriptors", "title": "File Descriptors", "unit": "", "family": "views_nodes", "pick": 'instance', "queries": [{"legend": "Maximum file descriptors", "expr": "node_filefd_maximum{instance=~\"$instance\"}"}, {"legend": "Allocated file descriptors", "expr": "node_filefd_allocated{instance=~\"$instance\"}"}]},
    {"id": "vd_time_sync", "title": "Time Sync", "unit": "", "family": "views_nodes", "pick": 'instance', "queries": [{"legend": "Estimated error in seconds", "expr": "node_timex_estimated_error_seconds{instance=~\"$instance\"}"}, {"legend": "Maximum error in seconds", "expr": "node_timex_maxerror_seconds{instance=~\"$instance\"}"}]},
    {"id": "vd_network_usage_bytes_s", "title": "Network usage (bytes/s)", "unit": "B/s", "family": "views_nodes", "pick": 'instance', "queries": [{"legend": "In", "expr": "sum(rate(node_network_receive_bytes_total{instance=~\"$instance\"}[5m]))"}, {"legend": "Out", "expr": "- sum(rate(node_network_transmit_bytes_total{instance=~\"$instance\"}[5m]))"}]},
    {"id": "vd_network_errors", "title": "Network errors", "unit": "B/s", "family": "views_nodes", "pick": 'instance', "queries": [{"legend": "In", "expr": "sum(rate(node_network_receive_errs_total{instance=~\"$instance\"}[5m]))"}, {"legend": "Out", "expr": "- sum(rate(node_network_transmit_errs_total{instance=~\"$instance\"}[5m]))"}]},
    {"id": "vd_network_usage_packet_s", "title": "Network usage (packet/s)", "unit": "B/s", "family": "views_nodes", "pick": 'instance', "queries": [{"legend": "In", "expr": "sum(rate(node_network_receive_packets_total{instance=~\"$instance\"}[5m]))"}, {"legend": "Out", "expr": "- sum(rate(node_network_transmit_packets_total{instance=~\"$instance\"}[5m]))"}]},
    {"id": "vd_network_total_drops", "title": "Network total drops", "unit": "B/s", "family": "views_nodes", "pick": 'instance', "queries": [{"legend": "In", "expr": "sum(rate(node_network_receive_drop_total{instance=~\"$instance\"}[5m]))"}, {"legend": "Out", "expr": "- sum(rate(node_network_transmit_drop_total{instance=~\"$instance\"}[5m]))"}]},
    {"id": "vd_tcp_currently_established", "title": "TCP Currently Established", "unit": "", "family": "views_nodes", "pick": 'instance', "query": "node_netstat_Tcp_CurrEstab{instance=~\"$instance\"}"},
    {"id": "vd_nf_conntrack", "title": "NF Conntrack", "unit": "", "family": "views_nodes", "pick": 'instance', "queries": [{"legend": "NF Conntrack entries", "expr": "node_nf_conntrack_entries{instance=~\"$instance\"}"}, {"legend": "NF Conntrack limit", "expr": "node_nf_conntrack_entries_limit{instance=~\"$instance\"}"}]},
    {"id": "vd_persistent_volumes_usage_in", "title": "Persistent Volumes - Usage in %", "unit": "%", "family": "views_nodes", "pick": 'node', "query": "max(kubelet_volume_stats_used_bytes{node=~\"$node\"}) by (persistentvolumeclaim, namespace) / max(kubelet_volume_stats_capacity_bytes{node=~\"$node\"}) by (persistentvolumeclaim, namespace)"},
    {"id": "vd_persistent_volumes_usage_in_gb", "title": "Persistent Volumes - Usage in GB", "unit": "bytes", "family": "views_nodes", "pick": 'node', "queries": [{"legend": "A", "expr": "max(kubelet_volume_stats_used_bytes{node=~\"$node\"}) by (persistentvolumeclaim, namespace)"}, {"legend": "B", "expr": "max(kubelet_volume_stats_capacity_bytes{node=~\"$node\"}) by (persistentvolumeclaim, namespace)"}]},
    {"id": "vd_persistent_volumes_inodes", "title": "Persistent Volumes - Inodes", "unit": "bytes", "family": "views_nodes", "pick": 'node', "query": "sum(kubelet_volume_stats_inodes_used{node=~\"$node\"}) by (persistentvolumeclaim) / sum(kubelet_volume_stats_inodes{node=~\"$node\"}) by (persistentvolumeclaim) * 100"},
    {"id": "vd_fs_usage_in", "title": "FS usage in %", "unit": "%", "family": "views_nodes", "pick": 'instance', "query": "100 - ((node_filesystem_avail_bytes{instance=~\"$instance\"} * 100) / node_filesystem_size_bytes{instance=~\"$instance\"})"},
    {"id": "vd_fs_inode_usage_in", "title": "FS inode usage in %", "unit": "%", "family": "views_nodes", "pick": 'instance', "query": "100 - (node_filesystem_files_free{instance=~\"$instance\"} / node_filesystem_files{instance=~\"$instance\"} * 100)"},
    {"id": "vd_reads_by_disk_bytes", "title": "Reads by disk (bytes)", "unit": "B/s", "family": "views_nodes", "pick": 'instance', "query": "rate(node_disk_read_bytes_total{instance=~\"$instance\"}[5m])"},
    {"id": "vd_writes_by_disk_bytes", "title": "Writes by disk (bytes)", "unit": "B/s", "family": "views_nodes", "pick": 'instance', "query": "rate(node_disk_written_bytes_total{instance=~\"$instance\"}[5m])"},
    {"id": "vd_completed_reads_by_disk", "title": "Completed reads by disk", "unit": "B/s", "family": "views_nodes", "pick": 'instance', "query": "rate(node_disk_reads_completed_total{instance=~\"$instance\"}[5m])"},
    {"id": "vd_completed_writes_by_disk", "title": "Completed writes by disk", "unit": "B/s", "family": "views_nodes", "pick": 'instance', "query": "rate(node_disk_writes_completed_total{instance=~\"$instance\"}[5m])"},
    {"id": "vd_disk_s_io_s", "title": "Disk(s) io/s", "unit": "B/s", "family": "views_nodes", "pick": 'instance', "query": "rate(node_disk_io_now{instance=~\"$instance\"}[5m])"},
    {"id": "vd_fs_device_errors", "title": "FS - Device Errors", "unit": "bytes", "family": "views_nodes", "pick": 'instance', "query": "sum(node_filesystem_device_error{instance=~\"$instance\"}) by (mountpoint)"},
    {"id": "vp_created_by", "title": "Created by", "unit": "", "family": "views_pods", "pick": 'pod', "scope": "namespace", "query": "kube_pod_info{namespace=~\"$namespace\", pod=~\"$pod\"}"},
    {"id": "vp_running_on", "title": "Running on", "unit": "", "family": "views_pods", "pick": 'pod', "scope": "namespace", "query": "kube_pod_info{namespace=~\"$namespace\", pod=~\"$pod\"}"},
    {"id": "vp_pod_ip", "title": "Pod IP", "unit": "", "family": "views_pods", "pick": 'pod', "scope": "namespace", "query": "kube_pod_info{namespace=~\"$namespace\", pod=~\"$pod\"}"},
    {"id": "vp_priority_class", "title": "Priority Class", "unit": "", "family": "views_pods", "pick": 'pod', "scope": "namespace", "query": "kube_pod_info{namespace=~\"$namespace\", pod=~\"$pod\", priority_class!=\"\"}"},
    {"id": "vp_qos_class", "title": "QOS Class", "unit": "", "family": "views_pods", "pick": 'pod', "scope": "namespace", "query": "kube_pod_status_qos_class{namespace=~\"$namespace\", pod=~\"$pod\"} > 0"},
    {"id": "vp_last_terminated_reason", "title": "Last Terminated Reason", "unit": "", "family": "views_pods", "pick": 'pod', "scope": "namespace", "query": "kube_pod_container_status_last_terminated_reason{namespace=~\"$namespace\", pod=~\"$pod\"}"},
    {"id": "vp_last_terminated_exit_code", "title": "Last Terminated Exit Code", "unit": "", "family": "views_pods", "pick": 'pod', "scope": "namespace", "query": "kube_pod_container_status_last_terminated_exitcode{namespace=~\"$namespace\", pod=~\"$pod\"}"},
    {"id": "vp_total_pod_cpu_requests_usage", "title": "Total pod CPU Requests usage", "unit": "cores", "family": "views_pods", "pick": 'pod', "scope": "namespace", "query": "sum(rate(container_cpu_usage_seconds_total{namespace=~\"$namespace\", pod=~\"$pod\", image!=\"\"}[5m])) / sum(kube_pod_container_resource_requests{namespace=~\"$namespace\", pod=~\"$pod\", resource=\"cpu\"} and on(namespace, pod) max by (namespace, pod) (kube_pod_status_phase{phase=\"Running\", namespace=~\"$namespace\", pod=~\"$pod\"} == 1))"},
    {"id": "vp_total_pod_cpu_limits_usage", "title": "Total pod CPU Limits usage", "unit": "cores", "family": "views_pods", "pick": 'pod', "scope": "namespace", "query": "sum(rate(container_cpu_usage_seconds_total{namespace=~\"$namespace\", pod=~\"$pod\", image!=\"\"}[5m])) / sum(kube_pod_container_resource_limits{namespace=~\"$namespace\", pod=~\"$pod\", resource=\"cpu\"} and on(namespace, pod) max by (namespace, pod) (kube_pod_status_phase{phase=\"Running\", namespace=~\"$namespace\", pod=~\"$pod\"} == 1))"},
    {"id": "vp_total_pod_ram_requests_usage", "title": "Total pod RAM Requests usage", "unit": "bytes", "family": "views_pods", "pick": 'pod', "scope": "namespace", "query": "sum(container_memory_working_set_bytes{namespace=~\"$namespace\", pod=~\"$pod\", image!=\"\"}) / sum(kube_pod_container_resource_requests{namespace=~\"$namespace\", pod=~\"$pod\", resource=\"memory\"} and on(namespace, pod) max by (namespace, pod) (kube_pod_status_phase{phase=\"Running\", namespace=~\"$namespace\", pod=~\"$pod\"} == 1))"},
    {"id": "vp_total_pod_ram_limits_usage", "title": "Total pod RAM Limits usage", "unit": "bytes", "family": "views_pods", "pick": 'pod', "scope": "namespace", "query": "sum(container_memory_working_set_bytes{namespace=~\"$namespace\", pod=~\"$pod\", image!=\"\"}) / sum(kube_pod_container_resource_limits{namespace=~\"$namespace\", pod=~\"$pod\", resource=\"memory\"} and on(namespace, pod) max by (namespace, pod) (kube_pod_status_phase{phase=\"Running\", namespace=~\"$namespace\", pod=~\"$pod\"} == 1))"},
    {"id": "vp_resources_by_container", "title": "Resources by container", "unit": "cores", "family": "views_pods", "pick": 'pod', "scope": "namespace", "queries": [{"legend": "A", "expr": "sum(kube_pod_container_resource_requests{namespace=~\"$namespace\", pod=~\"$pod\", resource=\"cpu\"} and on(namespace, pod) max by (namespace, pod) (kube_pod_status_phase{phase=\"Running\", namespace=~\"$namespace\", pod=~\"$pod\"} == 1)) by (container)"}, {"legend": "B", "expr": "sum(kube_pod_container_resource_limits{namespace=~\"$namespace\", pod=~\"$pod\", resource=\"cpu\"} and on(namespace, pod) max by (namespace, pod) (kube_pod_status_phase{phase=\"Running\", namespace=~\"$namespace\", pod=~\"$pod\"} == 1)) by (container)"}, {"legend": "C", "expr": "sum(kube_pod_container_resource_requests{namespace=~\"$namespace\", pod=~\"$pod\", resource=\"memory\"} and on(namespace, pod) max by (namespace, pod) (kube_pod_status_phase{phase=\"Running\", namespace=~\"$namespace\", pod=~\"$pod\"} == 1)) by (container)"}, {"legend": "D", "expr": "sum(kube_pod_container_resource_limits{namespace=~\"$namespace\", pod=~\"$pod\", resource=\"memory\"} and on(namespace, pod) max by (namespace, pod) (kube_pod_status_phase{phase=\"Running\", namespace=~\"$namespace\", pod=~\"$pod\"} == 1)) by (container)"}, {"legend": "__auto", "expr": "sum(rate(container_cpu_usage_seconds_total{namespace=~\"$namespace\", pod=~\"$pod\", image!=\"\", container!=\"\"}[5m])) by (container)"}, {"legend": "F", "expr": "sum(container_memory_working_set_bytes{namespace=~\"$namespace\", pod=~\"$pod\", image!=\"\", container!=\"\"}) by (container)"}]},
    {"id": "vp_cpu_usage_requests_limits_by_container", "title": "CPU Usage / Requests & Limits by container", "unit": "cores", "family": "views_pods", "pick": 'pod', "scope": "namespace", "queries": [{"legend": "{{ container }}  REQUESTS", "expr": "sum(rate(container_cpu_usage_seconds_total{namespace=~\"$namespace\", pod=~\"$pod\", image!=\"\"}[5m])) by (container) / sum(kube_pod_container_resource_requests{namespace=~\"$namespace\", pod=~\"$pod\", resource=\"cpu\"} and on(namespace, pod) max by (namespace, pod) (kube_pod_status_phase{phase=\"Running\", namespace=~\"$namespace\", pod=~\"$pod\"} == 1)) by (container)"}, {"legend": "{{ container }}  LIMITS", "expr": "sum(rate(container_cpu_usage_seconds_total{namespace=~\"$namespace\", pod=~\"$pod\", image!=\"\"}[5m])) by (container) / sum(kube_pod_container_resource_limits{namespace=~\"$namespace\", pod=~\"$pod\", resource=\"cpu\"} and on(namespace, pod) max by (namespace, pod) (kube_pod_status_phase{phase=\"Running\", namespace=~\"$namespace\", pod=~\"$pod\"} == 1)) by (container)"}]},
    {"id": "vp_memory_usage_requests_limits_by_container", "title": "Memory Usage / Requests & Limits by container", "unit": "bytes", "family": "views_pods", "pick": 'pod', "scope": "namespace", "queries": [{"legend": "{{ container }} REQUESTS", "expr": "sum(container_memory_working_set_bytes{namespace=~\"$namespace\", pod=~\"$pod\", image!=\"\"}) by (container) / sum(kube_pod_container_resource_requests{namespace=~\"$namespace\", pod=~\"$pod\", resource=\"memory\"} and on(namespace, pod) max by (namespace, pod) (kube_pod_status_phase{phase=\"Running\", namespace=~\"$namespace\", pod=~\"$pod\"} == 1)) by (container)"}, {"legend": "{{ container }} LIMITS", "expr": "sum(container_memory_working_set_bytes{namespace=~\"$namespace\", pod=~\"$pod\", image!=\"\"}) by (container) / sum(kube_pod_container_resource_limits{namespace=~\"$namespace\", pod=~\"$pod\", resource=\"memory\"} and on(namespace, pod) max by (namespace, pod) (kube_pod_status_phase{phase=\"Running\", namespace=~\"$namespace\", pod=~\"$pod\"} == 1)) by (container)"}]},
    {"id": "vp_cpu_usage_by_container", "title": "CPU Usage by container", "unit": "cores", "family": "views_pods", "pick": 'pod', "scope": "namespace", "query": "sum(rate(container_cpu_usage_seconds_total{namespace=~\"$namespace\", pod=~\"$pod\", image!=\"\", container!=\"\"}[5m])) by (container, id)"},
    {"id": "vp_memory_usage_by_container", "title": "Memory Usage by container", "unit": "bytes", "family": "views_pods", "pick": 'pod', "scope": "namespace", "query": "sum(max_over_time(container_memory_working_set_bytes{namespace=~\"$namespace\", pod=~\"$pod\", image!=\"\", container!=\"\"}[5m])) by (container, id)"},
    {"id": "vp_cpu_throttled_seconds_by_container", "title": "CPU Throttled seconds by container", "unit": "cores", "family": "views_pods", "pick": 'pod', "scope": "namespace", "query": "sum(rate(container_cpu_cfs_throttled_seconds_total{namespace=~\"$namespace\", pod=~\"$pod\", image!=\"\", container!=\"\"}[5m])) by (container)"},
    {"id": "vp_oom_events_by_container", "title": "OOM Events by container", "unit": "", "family": "views_pods", "pick": 'pod', "scope": "namespace", "query": "sum(increase(container_oom_events_total{namespace=~\"$namespace\", pod=~\"$pod\", container!=\"\"}[1h])) by (container) > 0"},
    {"id": "vp_container_restarts_by_container", "title": "Container Restarts by container", "unit": "", "family": "views_pods", "pick": 'pod', "scope": "namespace", "query": "sum(increase(kube_pod_container_status_restarts_total{namespace=~\"$namespace\", pod=~\"$pod\", container!=\"\"}[1h])) by (container) > 0"},
    {"id": "vp_pods_with_container_issues", "title": "Pods with Container Issues", "unit": "", "family": "views_pods", "pick": None, "query": "kube_pod_container_status_waiting_reason{reason=~\"ErrImagePull|ImagePullBackOff|CrashLoopBackOff\"} == 1"},
    {"id": "vp_unscheduled_pods", "title": "Unscheduled Pods", "unit": "", "family": "views_pods", "pick": None, "query": "kube_pod_status_scheduled{condition=\"false\"} == 1"},
    {"id": "vp_network_bandwidth", "title": "Network - Bandwidth", "unit": "B/s", "family": "views_pods", "pick": 'pod', "scope": "namespace", "queries": [{"legend": "Received", "expr": "sum(rate(container_network_receive_bytes_total{namespace=~\"$namespace\", pod=~\"$pod\"}[5m]))"}, {"legend": "Transmitted", "expr": "- sum(rate(container_network_transmit_bytes_total{namespace=~\"$namespace\", pod=~\"$pod\"}[5m]))"}]},
    {"id": "vp_network_packets_rate", "title": "Network - Packets Rate", "unit": "B/s", "family": "views_pods", "pick": 'pod', "scope": "namespace", "queries": [{"legend": "Received", "expr": "sum(rate(container_network_receive_packets_total{namespace=~\"$namespace\", pod=~\"$pod\"}[5m]))"}, {"legend": "Transmitted", "expr": "- sum(rate(container_network_transmit_packets_total{namespace=~\"$namespace\", pod=~\"$pod\"}[5m]))"}]},
    {"id": "vp_network_packets_dropped", "title": "Network - Packets Dropped", "unit": "B/s", "family": "views_pods", "pick": 'pod', "scope": "namespace", "queries": [{"legend": "Received", "expr": "sum(rate(container_network_receive_packets_dropped_total{namespace=~\"$namespace\", pod=~\"$pod\"}[5m]))"}, {"legend": "Transmitted", "expr": "- sum(rate(container_network_transmit_packets_dropped_total{namespace=~\"$namespace\", pod=~\"$pod\"}[5m]))"}]},
    {"id": "vp_network_errors", "title": "Network - Errors", "unit": "B/s", "family": "views_pods", "pick": 'pod', "scope": "namespace", "queries": [{"legend": "Received", "expr": "sum(rate(container_network_receive_errors_total{namespace=~\"$namespace\", pod=~\"$pod\"}[5m]))"}, {"legend": "Transmitted", "expr": "- sum(rate(container_network_transmit_errors_total{namespace=~\"$namespace\", pod=~\"$pod\"}[5m]))"}]},
]

_VIEW_FAMILY = {
    "global": "views_global",
    "namespaces": "views_ns",
    "nodes": "views_nodes",
    "pods": "views_pods",
}

# Info / inventory panelleri → tablo (zaman serisi + legend anlamsız)
_TABLE_PANEL_IDS = frozenset({
    "vd_list_of_pods_on_node_node",
    "vp_created_by",
    "vp_running_on",
    "vp_pod_ip",
    "vp_priority_class",
    "vp_pods_with_container_issues",
    "vp_unscheduled_pods",
    "vn_pods_with_unexpected_status",
})

_DEFAULT_HIGH_CARD_CAP = 10
_DEFAULT_TABLE_ROW_CAP = 200


def _annotate_views_catalog() -> None:
    """display=table / series_cap — yüksek kardinalite panellerini ehlileştir."""
    for c in VIEWS_CATALOG:
        cid = c.get("id") or ""
        exprs = []
        if c.get("query"):
            exprs.append(str(c["query"]))
        for q in c.get("queries") or []:
            if isinstance(q, dict) and q.get("expr"):
                exprs.append(str(q["expr"]))
        blob = " ".join(exprs)
        if cid in _TABLE_PANEL_IDS or cid.startswith("vp_") and "kube_pod_info{" in blob and "by (" not in blob:
            c.setdefault("display", "table")
        if c.get("display") == "table":
            c.setdefault("series_cap", _DEFAULT_TABLE_ROW_CAP)
            continue
        # by(pod) / by(pvc) / by(namespace) Top-N
        if (
            "by (pod)" in blob
            or "by_pod" in cid
            or "by (persistentvolumeclaim" in blob
            or "by (container)" in blob
        ):
            c.setdefault("series_cap", _DEFAULT_HIGH_CARD_CAP)
        elif "by (namespace)" in blob or "by_namespace" in cid:
            c.setdefault("series_cap", 15)
        elif "by (instance)" in blob or "by_instance" in cid:
            c.setdefault("series_cap", 12)
        elif "by (device)" in blob or "by (mountpoint)" in blob:
            c.setdefault("series_cap", 12)


_annotate_views_catalog()


def _effective_top_n(meta: Dict[str, Any], requested: int) -> int:
    cap = meta.get("series_cap")
    req = max(1, int(requested or 50))
    if cap is None:
        return req
    try:
        return max(1, min(req, int(cap)))
    except (TypeError, ValueError):
        return req


def _openshift_source(db=None, source_id: Optional[str] = None) -> Optional[MonitoringSource]:
    sources = load_sources_from_db(db) if db is not None else load_sources_runtime()
    if source_id:
        return resolve(sources, source_id=source_id)
    matched = list_by_binding(sources, "openshift")
    return matched[0] if matched else None


def _query_prom(src: MonitoringSource, query: str, timeout: float = 12.0) -> Dict[str, Any]:
    base = prom_base_url(src)
    headers = prom_headers(src)
    with httpx.Client(timeout=timeout, verify=prom_verify(src)) as client:
        resp = client.get(f"{base}/api/v1/query", params={"query": query}, headers=headers)
        resp.raise_for_status()
        return resp.json()


def _query_range(
    src: MonitoringSource,
    query: str,
    start: float,
    end: float,
    step: int = 30,
    timeout: float = 25.0,
) -> Dict[str, Any]:
    base = prom_base_url(src)
    headers = prom_headers(src)
    with httpx.Client(timeout=timeout, verify=prom_verify(src)) as client:
        resp = client.get(
            f"{base}/api/v1/query_range",
            params={"query": query, "start": start, "end": end, "step": step},
            headers=headers,
        )
        resp.raise_for_status()
        return resp.json()


def _label_values(src: MonitoringSource, name: str, timeout: float = 12.0) -> List[str]:
    base = prom_base_url(src)
    headers = prom_headers(src)
    with httpx.Client(timeout=timeout, verify=prom_verify(src)) as client:
        resp = client.get(f"{base}/api/v1/label/{name}/values", headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return list(data.get("data") or [])


def _safe_re(val: Optional[str], default: str = ".*") -> str:
    v = (val or "").strip()
    if not v or v in ("*", ".*"):
        return default
    # K8s adları (ns/node/pod) genelde güvenli; RE2'de re.escape(\\-) 400 verebiliyor.
    if re.fullmatch(r"[a-zA-Z0-9._:@/-]+", v):
        return v
    return re.sub(r"([.\\+*?[^\]$(){}|])", r"\\\1", v)


def _parse_multi(val: Optional[str]) -> List[str]:
    """CSV veya tek değer → temiz liste."""
    if not val:
        return []
    out = []
    for part in str(val).split(","):
        p = part.strip()
        if p and p not in out:
            out.append(p)
    return out


def _join_re(vals: List[str]) -> Optional[str]:
    """Çoklu seçim → PromQL regex. Boşsa None (seçim yok)."""
    cleaned = [_safe_re(v, "") for v in vals if v and v.strip()]
    cleaned = [c for c in cleaned if c and c != ".*"]
    if not cleaned:
        return None
    return "|".join(cleaned)


def _apply_vars(
    query: str,
    *,
    namespace: Optional[str] = None,
    node: Optional[str] = None,
    pod: Optional[str] = None,
    instance: Optional[str] = None,
) -> str:
    """Tek veya CSV değerleri $var yerine koyar; boşsa .* (yalnızca pick=None chart’lar)."""
    def _one(v: Optional[str]) -> str:
        parts = _parse_multi(v)
        joined = _join_re(parts)
        return joined if joined else ".*"

    q = query
    q = q.replace("$namespace", _one(namespace))
    q = q.replace("$node", _one(node))
    q = q.replace("$pod", _one(pod))
    q = q.replace("$instance", _one(instance))
    return q


def _selection_for_pick(
    pick: Optional[str],
    *,
    namespace: Optional[str],
    node: Optional[str],
    pod: Optional[str],
    instance: Optional[str],
) -> List[str]:
    if pick == "namespace":
        return _parse_multi(namespace)
    if pick == "node":
        return _parse_multi(node)
    if pick == "pod":
        return _parse_multi(pod)
    if pick == "instance":
        return _parse_multi(instance)
    return []


def _soft_label_ok(
    metric: Dict[str, Any],
    *,
    namespace: Optional[str] = None,
    node: Optional[str] = None,
    pod: Optional[str] = None,
    instance: Optional[str] = None,
) -> bool:
    """pick=None grafiklerde UI seçimi varsa label soft-filtre (Grafana All + isteğe bağlı daraltma)."""
    checks = (
        ("namespace", namespace),
        ("node", node),
        ("pod", pod),
        ("instance", instance),
    )
    for label, raw in checks:
        allow = _parse_multi(raw)
        if not allow:
            continue
        val = metric.get(label) or ""
        if not val:
            continue  # label yoksa (aggregate) kesme
        if val not in allow:
            return False
    return True


def templates() -> List[Dict[str, Any]]:
    return list(TEMPLATES)


def _chart_help(meta: Dict[str, Any]) -> str:
    """Katalog help veya başlıktan kısa açıklama."""
    if meta.get("help"):
        return str(meta["help"])
    title = (meta.get("title") or "").strip()
    t = title.lower()
    fam = meta.get("family") or ""
    if "cpu" in t and "throttl" in t:
        return "CPU throttle: konteyner CFS kotasına takıldığında geciken CPU süresi. Yüksek değer uygulama yavaşlaması demektir."
    if "cpu" in t:
        return "CPU kullanımı. Namespace/node/pod/instance kırılımı başlığa göre değişir."
    if "memory" in t or "ram" in t or "mem " in t:
        return "Bellek kullanımı (working set / available farkı). OOM riski ve kapasite planlaması için."
    if "network" in t or "packet" in t:
        return "Ağ trafiği veya paket kaybı. Bant genişliği ve saturation teşhisi için."
    if "oom" in t:
        return "Bellek yetersizliğinden (OOM) öldürülen konteyner olayları."
    if "restart" in t:
        return "Konteyner yeniden başlatma sayısı. CrashLoop / liveness sorunlarını işaret eder."
    if "qos" in t:
        return "Pod QoS sınıfları (Guaranteed / Burstable / BestEffort) dağılımı."
    if "disk" in t or "filesystem" in t or "fs " in t or "volume" in t or "inode" in t:
        return "Disk / dosya sistemi / PVC kullanımı veya I/O."
    if "load" in t:
        return "İşletim sistemi yük ortalaması (load average)."
    if "replica" in t or "deployment" in t:
        return "Deployment replica durumu (available / unavailable)."
    if fam.startswith("views"):
        return f"Kubernetes Views paneli: {title}."
    return title or "Metrik açıklaması yok."


def catalog(family: Optional[str] = None) -> List[Dict[str, Any]]:
    items = VIEWS_CATALOG + DCGM_CATALOG + KUBEVIRT_CATALOG
    if not family:
        out = items
    elif family in ("gpu", "dcgm"):
        out = list(DCGM_CATALOG)
    elif family in ("kubevirt", "vmi"):
        out = list(KUBEVIRT_CATALOG)
    elif family in ("views", "views_all"):
        out = list(VIEWS_CATALOG)
    elif family in _VIEW_FAMILY:
        fam = _VIEW_FAMILY[family]
        out = [c for c in VIEWS_CATALOG if c["family"] == fam]
    elif family.startswith("views_"):
        out = [c for c in VIEWS_CATALOG if c["family"] == family]
    else:
        out = items
    # help alanını her zaman doldur (FE tooltip)
    enriched = []
    for c in out:
        row = dict(c)
        row["help"] = _chart_help(c)
        enriched.append(row)
    return enriched


def _series_label(metric: Dict[str, str]) -> str:
    host = metric.get("Hostname") or metric.get("hostname") or metric.get("node") or metric.get("instance") or ""
    gpu = metric.get("gpu") or metric.get("UUID") or metric.get("device") or ""
    ns = metric.get("namespace") or ""
    pod = metric.get("pod") or ""
    container = metric.get("container") or ""
    mode = metric.get("mode") or ""
    deployment = metric.get("deployment") or ""
    qos = metric.get("qos_class") or ""
    parts = []
    if host:
        parts.append(str(host).split(".")[0][:40])
    if deployment:
        parts.append(deployment[:40])
    if ns:
        parts.append(ns[:40])
    if pod:
        parts.append(pod[:40])
    if container and container not in ("POD", ""):
        parts.append(container[:30])
    if mode:
        parts.append(mode)
    if qos:
        parts.append(qos)
    if gpu != "":
        parts.append(f"GPU {gpu}")
    return " · ".join(parts) if parts else str(metric.get("__name__", "series"))


def _instant_value(src: MonitoringSource, query: str) -> Optional[float]:
    try:
        r = _query_prom(src, query)
        res = (r.get("data") or {}).get("result") or []
        if res and res[0].get("value"):
            return float(res[0]["value"][1])
    except Exception as e:
        logger.debug("ocp prom instant %s: %s", query[:60], e)
    return None


def overview(db=None, source_id: Optional[str] = None) -> Dict[str, Any]:
    src = _openshift_source(db, source_id)
    if not src:
        return {
            "configured": False,
            "source": None,
            "gpu_count": 0,
            "avg_util": None,
            "avg_temp": None,
            "note": "OpenShift Prometheus kaynağı yapılandırılmamış",
        }
    nodes = _instant_value(src, "count(count by (node) (kube_node_info))")
    namespaces = _instant_value(src, "count(count by (namespace) (kube_pod_info))")
    running_pods = _instant_value(src, 'sum(kube_pod_status_phase{phase="Running"})')
    cpu_cores = _instant_value(
        src, 'sum(rate(node_cpu_seconds_total{mode!~"idle|iowait|steal",job="node-exporter"}[5m]))'
    )
    mem_used = _instant_value(
        src,
        "sum(node_memory_MemTotal_bytes{job=\"node-exporter\"} - node_memory_MemAvailable_bytes{job=\"node-exporter\"})",
    )
    vmi_count = _instant_value(src, "count(kubevirt_vmi_info)") or _instant_value(
        src, "count(kubevirt_vmi_memory_used_bytes)"
    )
    gpu_count = 0
    avg_util = None
    avg_temp = None
    try:
        r = _query_prom(src, "count(DCGM_FI_DEV_GPU_UTIL)")
        res = (r.get("data") or {}).get("result") or []
        if res and res[0].get("value"):
            gpu_count = int(float(res[0]["value"][1]))
    except Exception as e:
        logger.debug("ocp prom gpu_count: %s", e)
    try:
        r = _query_prom(src, "avg(DCGM_FI_DEV_GPU_UTIL)")
        res = (r.get("data") or {}).get("result") or []
        if res and res[0].get("value"):
            avg_util = round(float(res[0]["value"][1]), 1)
    except Exception:
        pass
    try:
        r = _query_prom(src, "avg(DCGM_FI_DEV_GPU_TEMP)")
        res = (r.get("data") or {}).get("result") or []
        if res and res[0].get("value"):
            avg_temp = round(float(res[0]["value"][1]), 1)
    except Exception:
        pass
    return {
        "configured": True,
        "source": src.public_dict(),
        "nodes": int(nodes) if nodes is not None else None,
        "namespaces": int(namespaces) if namespaces is not None else None,
        "running_pods": int(running_pods) if running_pods is not None else None,
        "cpu_cores_used": round(cpu_cores, 3) if cpu_cores is not None else None,
        "memory_used_bytes": int(mem_used) if mem_used is not None else None,
        "vmi_count": int(vmi_count) if vmi_count is not None else 0,
        "gpu_count": gpu_count,
        "avg_util": avg_util,
        "avg_temp": avg_temp,
        "templates": TEMPLATES,
        "note": "Kubernetes Views (default) · GPU/DCGM · KubeVirt VMI",
    }


def label_options(
    kind: str = "namespace",
    *,
    namespace: Optional[str] = None,
    source_id: Optional[str] = None,
    db=None,
) -> Dict[str, Any]:
    src = _openshift_source(db, source_id)
    if not src:
        return {"ok": False, "values": [], "error": "OpenShift Prometheus yok"}
    try:
        if kind == "namespace":
            vals = _label_values(src, "namespace")
        elif kind == "node":
            # prefer kube_node_info node label
            r = _query_prom(src, "count by (node) (kube_node_info)")
            vals = sorted({
                (x.get("metric") or {}).get("node")
                for x in ((r.get("data") or {}).get("result") or [])
                if (x.get("metric") or {}).get("node")
            })
        elif kind == "instance":
            vals = [
                v for v in _label_values(src, "instance")
                if v  # node-exporter instances
            ]
            # prefer those with node-exporter job via query
            r = _query_prom(src, "count by (instance) (node_uname_info)")
            from_q = sorted({
                (x.get("metric") or {}).get("instance")
                for x in ((r.get("data") or {}).get("result") or [])
                if (x.get("metric") or {}).get("instance")
            })
            if from_q:
                vals = from_q
        elif kind == "pod":
            ns = _safe_re(namespace, ".*")
            r = _query_prom(src, f'count by (pod) (kube_pod_info{{namespace=~"{ns}"}})')
            vals = sorted({
                (x.get("metric") or {}).get("pod")
                for x in ((r.get("data") or {}).get("result") or [])
                if (x.get("metric") or {}).get("pod")
            })
        else:
            vals = _label_values(src, kind)
        return {"ok": True, "values": vals[:500], "kind": kind}
    except Exception as e:
        logger.warning("ocp prom label_options: %s", e)
        return {"ok": False, "values": [], "error": str(e)}


def allocation_table(db=None, source_id: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
    """GPU allocation benzeri tablo — util + temp + power + labels."""
    src = _openshift_source(db, source_id)
    if not src:
        return {"ok": False, "rows": [], "error": "OpenShift Prometheus yok"}
    rows: List[Dict[str, Any]] = []
    try:
        util = _query_prom(src, "DCGM_FI_DEV_GPU_UTIL")
        temp = _query_prom(src, "DCGM_FI_DEV_GPU_TEMP")
        power = _query_prom(src, "DCGM_FI_DEV_POWER_USAGE")
        fb = _query_prom(src, "DCGM_FI_DEV_FB_USED")

        def _idx(data: Dict) -> Dict[str, float]:
            out = {}
            for r in (data.get("data") or {}).get("result") or []:
                m = r.get("metric") or {}
                key = f"{m.get('Hostname') or m.get('hostname')}|{m.get('gpu')}|{m.get('UUID')}"
                if r.get("value"):
                    out[key] = float(r["value"][1])
            return out

        temp_i = _idx(temp)
        power_i = _idx(power)
        fb_i = _idx(fb)

        for r in (util.get("data") or {}).get("result") or []:
            m = r.get("metric") or {}
            key = f"{m.get('Hostname') or m.get('hostname')}|{m.get('gpu')}|{m.get('UUID')}"
            val = float(r["value"][1]) if r.get("value") else None
            rows.append({
                "hostname": m.get("Hostname") or m.get("hostname"),
                "namespace": m.get("namespace"),
                "pod": m.get("pod"),
                "container": m.get("container"),
                "gpu": m.get("gpu"),
                "model": m.get("modelName") or m.get("gpu_model"),
                "util": val,
                "temp": temp_i.get(key),
                "power": power_i.get(key),
                "fb_used": fb_i.get(key),
            })
            if len(rows) >= limit:
                break
        rows.sort(key=lambda x: -(x.get("util") or 0))
        return {"ok": True, "rows": rows, "source": src.public_dict()}
    except Exception as e:
        logger.warning("ocp allocation_table: %s", e)
        return {"ok": False, "rows": [], "error": str(e)}


def series(
    metric_id: str,
    *,
    range_sec: int = 900,
    step: int = 30,
    source_id: Optional[str] = None,
    db=None,
    top_n: int = 50,
    namespace: Optional[str] = None,
    node: Optional[str] = None,
    pod: Optional[str] = None,
    instance: Optional[str] = None,
    relax_selection: bool = False,
) -> Dict[str, Any]:
    src = _openshift_source(db, source_id)
    if not src:
        return {"ok": False, "series": [], "error": "OpenShift Prometheus yok"}
    cat = {c["id"]: c for c in catalog()}
    meta = cat.get(metric_id)
    if not meta:
        # catalog() wraps help — raw id from VIEWS+DCGM+KV
        cat_raw = {c["id"]: c for c in (VIEWS_CATALOG + DCGM_CATALOG + KUBEVIRT_CATALOG)}
        meta = cat_raw.get(metric_id)
    if not meta:
        return {"ok": False, "series": [], "error": f"Bilinmeyen metrik: {metric_id}"}

    pick = meta.get("pick")
    scope = meta.get("scope")
    display = (meta.get("display") or "chart").strip().lower()
    eff_top = _effective_top_n(meta, top_n)

    # pick boyutu seçilmeden veri yok (Top-N otomatik yok) — chat'te relax_selection=True
    if pick and not relax_selection:
        selected = _selection_for_pick(
            pick, namespace=namespace, node=node, pod=pod, instance=instance,
        )
        if not selected:
            return {
                "ok": True,
                "kind": display if display in ("table", "chart") else "chart",
                "metric": {k: meta[k] for k in ("id", "title", "unit", "family", "help", "display") if k in meta},
                "series": [],
                "rows": [],
                "need_selection": pick,
                "hint": f"Grafikte göstermek için {pick} seçin",
                "range_sec": range_sec,
            }
    if scope == "namespace" and not _parse_multi(namespace) and not relax_selection:
        return {
            "ok": True,
            "kind": display if display in ("table", "chart") else "chart",
            "metric": {k: meta[k] for k in ("id", "title", "unit", "family", "help", "display") if k in meta},
            "series": [],
            "rows": [],
            "need_selection": "namespace",
            "hint": "Önce namespace seçin",
            "range_sec": range_sec,
        }

    query_specs = meta.get("queries") or (
        [{"expr": meta["query"], "legend": ""}] if meta.get("query") else []
    )
    if not query_specs:
        return {"ok": False, "series": [], "error": f"Sorgu yok: {metric_id}"}

    # —— Tablo panelleri (pod listesi / info) ——
    if display == "table":
        return _series_as_table(
            src, meta, query_specs,
            namespace=namespace, node=node, pod=pod, instance=instance,
            pick=pick, relax_selection=relax_selection, row_cap=eff_top,
        )

    end = time.time()
    start = end - max(60, range_sec)
    try:
        allow = set()
        if pick:
            allow = set(_selection_for_pick(
                pick, namespace=namespace, node=node, pod=pod, instance=instance,
            ))
        scored = []
        applied_queries = []
        for spec in query_specs:
            raw_q = spec.get("expr") if isinstance(spec, dict) else str(spec)
            legend = (spec.get("legend") if isinstance(spec, dict) else "") or ""
            query = _apply_vars(
                raw_q,
                namespace=namespace,
                node=node,
                pod=pod,
                instance=instance,
            )
            applied_queries.append(query)
            try:
                data = _query_range(src, query, start, end, step)
            except Exception as e:
                logger.warning("ocp prom series query failed (%s): %s", metric_id, e)
                continue
            results = (data.get("data") or {}).get("result") or []
            if pick and allow:
                filtered = []
                for r in results:
                    m = r.get("metric") or {}
                    key = m.get(pick) or m.get("nodename") or ""
                    if not key or key in allow:
                        filtered.append(r)
                results = filtered
            for r in results:
                m = r.get("metric") or {}
                if not _soft_label_ok(m, namespace=namespace, node=node, pod=pod, instance=instance):
                    continue
                vals = r.get("values") or []
                last = float(vals[-1][1]) if vals else 0.0
                scored.append((abs(last), r, legend))

        scored.sort(key=lambda x: -x[0])
        total = len(scored)
        sliced = scored[:eff_top]
        out_series = []
        for _, r, legend in sliced:
            m = r.get("metric") or {}
            points = [{"t": int(float(ts)), "v": float(v)} for ts, v in (r.get("values") or [])]
            label = _series_label(m)
            if legend and "{{" not in legend:
                name = legend if not label or label == "series" else f"{legend}: {label}"
            else:
                name = label
            out_series.append({
                "name": name,
                "labels": m,
                "points": points,
            })
        return {
            "ok": True,
            "kind": "chart",
            "metric": {k: meta[k] for k in ("id", "title", "unit", "family", "pick", "help", "display", "series_cap") if k in meta},
            "query": applied_queries[0] if len(applied_queries) == 1 else applied_queries,
            "series": out_series,
            "total_series": total,
            "truncated": total > len(out_series),
            "series_cap": eff_top,
            "source": src.public_dict(),
            "range_sec": range_sec,
        }
    except Exception as e:
        logger.warning("ocp prom series: %s", e)
        return {"ok": False, "series": [], "error": str(e)}


def _series_as_table(
    src: MonitoringSource,
    meta: Dict[str, Any],
    query_specs: List[Any],
    *,
    namespace: Optional[str],
    node: Optional[str],
    pod: Optional[str],
    instance: Optional[str],
    pick: Optional[str],
    relax_selection: bool,
    row_cap: int,
) -> Dict[str, Any]:
    """Instant query → satır tablosu (pod listesi / etiket özeti)."""
    allow = set()
    if pick:
        allow = set(_selection_for_pick(
            pick, namespace=namespace, node=node, pod=pod, instance=instance,
        ))
    rows: List[Dict[str, Any]] = []
    applied = []
    try:
        for spec in query_specs:
            raw_q = spec.get("expr") if isinstance(spec, dict) else str(spec)
            query = _apply_vars(
                raw_q,
                namespace=namespace,
                node=node,
                pod=pod,
                instance=instance,
            )
            applied.append(query)
            data = _query_prom(src, query, timeout=20.0)
            results = (data.get("data") or {}).get("result") or []
            for r in results:
                m = dict(r.get("metric") or {})
                if pick and allow:
                    key = m.get(pick) or m.get("nodename") or ""
                    if key and key not in allow:
                        continue
                if not _soft_label_ok(m, namespace=namespace, node=node, pod=pod, instance=instance):
                    continue
                val = r.get("value")
                value = float(val[1]) if val and len(val) >= 2 else None
                row = {
                    "namespace": m.get("namespace") or "",
                    "pod": m.get("pod") or "",
                    "node": m.get("node") or m.get("nodename") or "",
                    "instance": m.get("instance") or "",
                    "container": m.get("container") or "",
                    "reason": m.get("reason") or "",
                    "phase": m.get("phase") or "",
                    "created_by": (
                        f"{m.get('created_by_kind') or ''}/{m.get('created_by_name') or ''}".strip("/")
                        or ""
                    ),
                    "pod_ip": m.get("pod_ip") or m.get("host_ip") or "",
                    "priority_class": m.get("priority_class") or "",
                    "value": value,
                    "name": _series_label(m),
                    "labels": m,
                }
                rows.append(row)
        # Dedupe by namespace+pod+container+reason
        seen = set()
        uniq = []
        for row in rows:
            key = (
                row.get("namespace"), row.get("pod"), row.get("container"),
                row.get("reason"), row.get("name"),
            )
            if key in seen:
                continue
            seen.add(key)
            uniq.append(row)
        uniq.sort(key=lambda r: (
            str(r.get("namespace") or ""),
            str(r.get("pod") or ""),
            str(r.get("name") or ""),
        ))
        total = len(uniq)
        sliced = uniq[: max(1, row_cap)]
        columns = _table_columns_for(meta, sliced)
        return {
            "ok": True,
            "kind": "table",
            "metric": {k: meta[k] for k in ("id", "title", "unit", "family", "pick", "help", "display") if k in meta},
            "query": applied[0] if len(applied) == 1 else applied,
            "series": [],
            "rows": sliced,
            "columns": columns,
            "total_series": total,
            "truncated": total > len(sliced),
            "series_cap": row_cap,
            "source": src.public_dict(),
        }
    except Exception as e:
        logger.warning("ocp prom table: %s", e)
        return {"ok": False, "kind": "table", "series": [], "rows": [], "error": str(e)}


def _table_columns_for(meta: Dict[str, Any], rows: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Gösterilecek kolonlar — dolu alanlara göre."""
    cid = meta.get("id") or ""
    preferred = [
        ("namespace", "Namespace"),
        ("pod", "Pod"),
        ("node", "Node"),
        ("container", "Container"),
        ("reason", "Reason"),
        ("created_by", "Created by"),
        ("pod_ip", "IP"),
        ("priority_class", "Priority"),
        ("instance", "Instance"),
        ("value", "Value"),
    ]
    if "list_of_pods" in cid:
        keys = ["namespace", "pod", "node"]
    elif cid in ("vp_created_by",):
        keys = ["namespace", "pod", "created_by"]
    elif cid in ("vp_running_on",):
        keys = ["namespace", "pod", "node"]
    elif cid in ("vp_pod_ip",):
        keys = ["namespace", "pod", "pod_ip"]
    elif cid in ("vp_priority_class",):
        keys = ["namespace", "pod", "priority_class"]
    else:
        keys = []
        for k, _ in preferred:
            if any(str(r.get(k) or "") not in ("", "None") for r in rows):
                keys.append(k)
        if not keys:
            keys = ["name", "value"]
    label_map = dict(preferred)
    label_map["name"] = "Name"
    return [{"key": k, "label": label_map.get(k, k)} for k in keys]


def views_bundle(
    view: str = "global",
    *,
    range_sec: int = 900,
    step: int = 60,
    source_id: Optional[str] = None,
    db=None,
    top_n: int = 50,
    namespace: Optional[str] = None,
    node: Optional[str] = None,
    pod: Optional[str] = None,
    instance: Optional[str] = None,
    relax_selection: bool = False,
) -> Dict[str, Any]:
    """Bir Views sekmesi: tüm chart metriklerini döndür (seçime göre)."""
    view = (view or "global").strip().lower()
    if view not in _VIEW_FAMILY:
        return {"ok": False, "charts": [], "error": f"Geçersiz view: {view}"}
    src = _openshift_source(db, source_id)
    if not src:
        return {"ok": False, "charts": [], "error": "OpenShift Prometheus yok"}
    fam = _VIEW_FAMILY[view]
    metrics = [c for c in VIEWS_CATALOG if c["family"] == fam]
    charts = []
    for meta in metrics:
        # Chart: FE top_n + series_cap; tablo: satır tavanı (series_cap)
        if (meta.get("display") or "") == "table":
            panel_top = int(meta.get("series_cap") or _DEFAULT_TABLE_ROW_CAP)
        else:
            panel_top = _effective_top_n(meta, top_n)
        out = series(
            meta["id"],
            range_sec=range_sec,
            step=step,
            source_id=source_id,
            db=db,
            top_n=panel_top,
            namespace=namespace,
            node=node,
            pod=pod,
            instance=instance,
            relax_selection=relax_selection,
        )
        charts.append({
            "id": meta["id"],
            "title": meta["title"],
            "unit": meta["unit"],
            "pick": meta.get("pick"),
            "help": _chart_help(meta),
            "display": meta.get("display") or out.get("kind") or "chart",
            "kind": out.get("kind") or ("table" if meta.get("display") == "table" else "chart"),
            "ok": out.get("ok"),
            "error": out.get("error"),
            "hint": out.get("hint"),
            "need_selection": out.get("need_selection"),
            "series": out.get("series") or [],
            "rows": out.get("rows") or [],
            "columns": out.get("columns") or [],
            "total_series": out.get("total_series"),
            "truncated": out.get("truncated"),
            "series_cap": out.get("series_cap"),
        })
    return {
        "ok": True,
        "view": view,
        "charts": charts,
        "source": src.public_dict(),
        "range_sec": range_sec,
        "relax_selection": relax_selection,
        "selection": {
            "namespace": _parse_multi(namespace),
            "node": _parse_multi(node),
            "pod": _parse_multi(pod),
            "instance": _parse_multi(instance),
        },
    }


def _infer_ocp_prom_intent(
    question: Optional[str],
    *,
    mode: str,
    metric_id: Optional[str],
    family: Optional[str],
    view: Optional[str],
) -> Dict[str, Optional[str]]:
    """Doğal dil → mode/view/family/metric (chat yönlendirme)."""
    q = (question or "").strip().lower()
    out = {"mode": mode, "metric_id": metric_id, "family": family, "view": view}
    if not q:
        return out
    # Explicit catalog ids
    if not metric_id:
        for c in catalog():
            cid = (c.get("id") or "").lower()
            if cid and len(cid) > 5 and cid in q.replace(" ", "_"):
                out["metric_id"] = c["id"]
                out["mode"] = "series"
                fam = c.get("family") or ""
                if fam.startswith("views_"):
                    out["view"] = fam.replace("views_", "") or "global"
                elif fam in ("gpu", "kubevirt"):
                    out["family"] = fam
                return out

    if any(k in q for k in ("dcgm", "gpu util", "gpu temp", "nvidia gpu", "framebuffer", "tensor core", "gpu allocation", "gpu tablo")):
        out["family"] = "gpu"
        if mode in ("overview", "auto", ""):
            out["mode"] = "allocation" if any(k in q for k in ("alloc", "hangi", "tablo", "list")) else "catalog"
        return out

    if any(k in q for k in ("kubevirt", "vmi ", "vmi_", "sanal makine metrik", "ov vm")):
        out["family"] = "kubevirt"
        if "cpu" in q:
            out["metric_id"] = "vmi_cpu"; out["mode"] = "series"
        elif "mem" in q or "bellek" in q:
            out["metric_id"] = "vmi_memory"; out["mode"] = "series"
        elif "read" in q or "okuma" in q:
            out["metric_id"] = "vmi_storage_read"; out["mode"] = "series"
        elif "write" in q or "yazma" in q:
            out["metric_id"] = "vmi_storage_write"; out["mode"] = "series"
        elif "rx" in q or "receive" in q or "gelen" in q:
            out["metric_id"] = "vmi_net_rx"; out["mode"] = "series"
        elif "tx" in q or "transmit" in q or "giden" in q or "network" in q or "ağ" in q or "ag " in q:
            out["metric_id"] = "vmi_net_tx"; out["mode"] = "series"
        elif mode in ("overview", "auto", ""):
            out["mode"] = "catalog"
        return out

    # Views — geniş eşleşme (tekil "view" / "pods view:" dahil)
    wants_views = any(k in q for k in (
        "views", "view:", "pods view", "nodes view", "namespaces view", "global view",
        "thanos", "cadvisor", "node-exporter", "kubernetes resource",
        "promql", "prometheus", "by namespace", "by node", "by instance", "by pod",
        "pod cpu", "pod memory", "pod request", "container cpu", "container memory",
    ))
    wants_views = wants_views or any(k in q for k in (
        "oom", "throttl", "qos", "packet drop", "restart", "resource count",
        "filesystem", "disk io", "network received", "network transmit",
        "cluster cpu", "cluster memory", "cluster bellek",
        "namespace cpu", "namespace memory", "namespace bellek",
        "node cpu", "node memory", "cpu utilization", "memory utilization",
        "cpu usage", "ram usage", "memory usage", "requests vs usage",
    ))

    if wants_views and mode in ("overview", "auto", "views", ""):
        out["mode"] = "views"
        # Explicit view adı her zaman kazanır
        if any(k in q for k in ("pods view", "view=pods", "view: pods", "pods:")):
            out["view"] = "pods"
        elif any(k in q for k in ("nodes view", "view=nodes", "view: nodes", "nodes:")):
            out["view"] = "nodes"
        elif any(k in q for k in ("namespaces view", "view=namespaces", "view: namespaces", "namespaces:")):
            out["view"] = "namespaces"
        elif any(k in q for k in ("global view", "view=global", "view: global", "cluster geneli", "cluster genel")):
            out["view"] = "global"
        elif any(k in q for k in (
            "pod cpu", "pod memory", "pod request", "container cpu", "container memory",
            "by pod", "per pod", "pod için",
        )) and "node" not in q:
            # Pod-level paneller: namespace seçiliyse pods, değilse namespaces (Top-N)
            out["view"] = "pods" if ("namespace" in q or " ns" in q or "ns " in q) else "namespaces"
        elif any(k in q for k in ("node ", "instance", "filesystem", "disk", "load average", "master-")):
            out["view"] = "nodes"
        elif any(k in q for k in ("namespace", "ns ", "proje", "by namespace")):
            out["view"] = "namespaces"
        elif "pod" in q and "node" not in q:
            out["view"] = "namespaces"
        else:
            out["view"] = view or "global"
        return out

    if mode in ("auto",):
        out["mode"] = "overview"
    return out


def run_ocp_prom_query(
    *,
    mode: str = "overview",
    metric_id: Optional[str] = None,
    family: Optional[str] = None,
    range_sec: int = 900,
    source_id: Optional[str] = None,
    question: Optional[str] = None,
    view: Optional[str] = None,
    namespace: Optional[str] = None,
    node: Optional[str] = None,
    pod: Optional[str] = None,
    instance: Optional[str] = None,
    top_n: int = 40,
    relax_selection: bool = True,
    label_kind: Optional[str] = None,
) -> Dict[str, Any]:
    """Chat tool handler — Views / GPU / VMI."""
    inferred = _infer_ocp_prom_intent(
        question, mode=mode or "overview", metric_id=metric_id, family=family, view=view,
    )
    mode = inferred["mode"] or mode or "overview"
    metric_id = inferred["metric_id"] or metric_id
    family = inferred["family"] or family
    view = inferred["view"] or view

    if mode == "templates":
        return {"ok": True, "templates": templates(), "source": "ocp_prometheus"}
    if mode == "catalog":
        # family: gpu|kubevirt|global|namespaces|nodes|pods|views
        fam = family
        if fam in ("global", "namespaces", "nodes", "pods"):
            pass
        elif fam in ("views", "views_all"):
            fam = "views"
        return {"ok": True, "catalog": catalog(fam), "family": fam, "source": "ocp_prometheus"}
    if mode == "labels":
        out = label_options(label_kind or "namespace", namespace=namespace, source_id=source_id)
        out["source_kind"] = "ocp_prometheus"
        return out
    if mode == "allocation":
        out = allocation_table(source_id=source_id)
        out["source_kind"] = "ocp_prometheus"
        return out
    if mode == "views":
        out = views_bundle(
            view or "global",
            range_sec=range_sec,
            source_id=source_id,
            top_n=top_n,
            namespace=namespace,
            node=node,
            pod=pod,
            instance=instance,
            relax_selection=relax_selection,
        )
        out["source_kind"] = "ocp_prometheus"
        if question:
            out["question"] = question
        return out
    if mode == "series" and metric_id:
        out = series(
            metric_id,
            range_sec=range_sec,
            source_id=source_id,
            top_n=top_n,
            namespace=namespace,
            node=node,
            pod=pod,
            instance=instance,
            relax_selection=relax_selection,
        )
        out["source_kind"] = "ocp_prometheus"
        if question:
            out["question"] = question
        return out
    out = overview(source_id=source_id)
    out["source_kind"] = "ocp_prometheus"
    if question:
        out["question"] = question
        out["hint"] = (
            "İpucu: Kubernetes Views için mode=views (view=global|namespaces|nodes|pods); "
            "GPU için family=gpu / mode=allocation|catalog; VMI için family=kubevirt / metric=vmi_*."
        )
    return out
