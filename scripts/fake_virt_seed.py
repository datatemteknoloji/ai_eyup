#!/usr/bin/env python3
"""Sahte sanallaştırma verisi üretici (yük/ölçek testi) — tek komutla eklenir, tek komutla silinir.

Kullanım (backend konteyneri içinde, repo kökünden):
    docker exec -i server_management_backend python - seed 1000 < scripts/fake_virt_seed.py
    docker exec -i server_management_backend python - cleanup   < scripts/fake_virt_seed.py
    docker exec -i server_management_backend python - seed-ocp 500 < scripts/fake_virt_seed.py   # OpenShift Virt (karışık OS)
    docker exec -i server_management_backend python - cleanup-ocp   < scripts/fake_virt_seed.py
    docker exec -i server_management_backend python - cleanup-all   < scripts/fake_virt_seed.py

Güvenlik:
- Her şey ayrı bir sahte hypervisor altında (`ZZ-FAKE-vCenter`, host `fake-vcenter.invalid`); gerçek kayıtlara dokunmaz.
- VM adları `zz-fake-vm-NNNN`, `hypervisor_vm_id` öneki `vm-fake-`. IP'ler yalnız 198.18.0.0/15 (RFC 2544, yönlendirilmez),
  gerçek bir hosta ulaşılmaz. `node_exporter_installed` / `windows_exporter_installed` = False → Prometheus hedefine girmez.
- OpenShift sahte kayıtları: hypervisor `ZZ-FAKE-OpenShift` (Sanallaştırma modülü) + cluster `ZZ-FAKE-OCP` (OpenShift
  modülü: node/proje/workload/ocp_resource_metrics), ikisi de `meta_data.fake_seed`. Host `fake-ocp.invalid` →
  gerçek API yok; periyodik/elle OCP sync, event, monitoring, bulgu ve host-metrik turları bu kayıtları atlar.
  Cluster overview ve KubeVirt VM listesi DB'den üretilir (`services/openshift/fake_cluster.py`).
- `cleanup` / `cleanup-ocp`: ilgili sahte hypervisor'ı (ve OCP için cluster'ı) ve ona bağlı her şeyi (servers dahil) siler.
"""
from __future__ import annotations

import random
import sys
from datetime import datetime, timedelta, timezone

from app.core.database import SessionLocal
from app.models.hypervisor import Hypervisor, HypervisorType
from app.models.server import Server
from app.models.virt_cluster import VirtCluster
from app.models.virt_datastore import VirtDatastore
from app.models.virt_metric import VirtVmMetric
from app.models.hypervisor_metric import HypervisorHostMetric
from app.models.hypervisor_inventory import HypervisorHostInventory
from app.models.openshift import OcpResourceMetric, OpenShiftCluster, OpenShiftNode, OpenShiftProject, OpenShiftWorkload

FAKE_NAME = "ZZ-FAKE-vCenter"
FAKE_HOST = "fake-vcenter.invalid"
N_CLUSTERS, HOSTS_PER_CLUSTER, N_DS = 5, 4, 10
HISTORY_HOURS = 48


OCP_NAME = "ZZ-FAKE-OpenShift"
OCP_HOST = "fake-ocp.invalid"
OCP_CLUSTER = "FAKE-OCP-Prod"
OCP_CLUSTER_NAME = "ZZ-FAKE-OCP"          # OpenShift modülündeki cluster kaydı (openshift_clusters)


def _fake_hv(db, host: str = FAKE_HOST):
    return db.query(Hypervisor).filter(Hypervisor.hostname == host).first()


def cleanup(host: str = FAKE_HOST) -> None:
    db = SessionLocal()
    try:
        hv = _fake_hv(db, host)
        if not hv:
            print("Sahte hypervisor yok; yapılacak bir şey yok.")
            return
        ids = [r[0] for r in db.query(Server.id).filter(Server.hypervisor_id == hv.id).all()]
        from app.services.hypervisor_cleanup import delete_servers_cascade
        n = delete_servers_cascade(db, ids) if ids else 0
        db.delete(hv)          # ON DELETE CASCADE: metrikler, cluster, datastore, host envanteri
        if host == OCP_HOST:   # OpenShift modülü kaydı: node/proje/workload/metrik FK CASCADE ile silinir
            for c in db.query(OpenShiftCluster).filter(OpenShiftCluster.name == OCP_CLUSTER_NAME).all():
                if (c.meta_data or {}).get("fake_seed"):
                    db.delete(c)
        db.commit()
        print(f"Silindi: {n} sahte VM + sahte hypervisor (id={hv.id}).")
    finally:
        db.close()


def seed(n_vms: int) -> None:
    rnd = random.Random(42)
    db = SessionLocal()
    try:
        if _fake_hv(db):
            print("Sahte hypervisor zaten var; önce `cleanup` çalıştırın.")
            return
        now = datetime.now(timezone.utc)
        hv = Hypervisor(
            name=FAKE_NAME, hypervisor_type=HypervisorType.VMWARE, hostname=FAKE_HOST, ip_address="198.18.0.1",
            port=443, username="fake", password=None, connection_config={}, status="fake",
            meta_data={"fake_seed": True, "created": now.isoformat()},
        )
        db.add(hv)
        db.flush()

        # ── cluster / host / datastore ──
        hosts = []  # (name, ref, cluster)
        for ci in range(N_CLUSTERS):
            cname = f"FAKE-Cluster-{ci + 1}"
            db.add(VirtCluster(
                hypervisor_id=hv.id, cluster_ref=f"domain-cfake{ci}", name=cname, hosts=HOSTS_PER_CLUSTER,
                effective_hosts=HOSTS_PER_CLUSTER, cpu_cores=HOSTS_PER_CLUSTER * 64,
                memory_gb=HOSTS_PER_CLUSTER * 768.0, memory_effective_gb=HOSTS_PER_CLUSTER * 768.0 * 0.75,
                ha_enabled=True, admission_control_enabled=True, policy_type="ClusterFailoverLevelAdmissionControlPolicy",
                failover_level=1, drs_enabled=True, overall_status="green", as_of=now,
            ))
            for hi in range(HOSTS_PER_CLUSTER):
                hosts.append((f"fake-esx-{ci + 1}{hi + 1:02d}.invalid", f"host-fake{ci}{hi}", cname))
        for name, ref, cname in hosts:
            db.add(HypervisorHostInventory(
                hypervisor_id=hv.id, host_ref=ref, host_name=name, vendor="Fake Inc.", model="FakeServer 9000",
                product_version="8.0.2", cluster_name=cname, cluster_ref="domain-" + ref[-3:-1], overall_status="green",
                vswitches=[], portgroups=[], pnics=[], vnics=[], dns={}, config_issues=[],
            ))
        datastores = [f"FAKE-DS-{i + 1:02d}" for i in range(N_DS)]
        for i, dsn in enumerate(datastores):
            cap = 20000.0
            used = rnd.uniform(0.35, 0.8) * cap
            db.add(VirtDatastore(
                hypervisor_id=hv.id, ds_ref=f"datastore-fake{i}", name=dsn, ds_type="VMFS", capacity_gb=cap,
                free_gb=cap - used, used_gb=used, usage_pct=round(100 * used / cap, 1), accessible=True,
                host_count=len(hosts), as_of=now,
            ))
        db.flush()

        # ── VM'ler ──
        vm_rows = []
        for i in range(1, n_vms + 1):
            host_name, host_ref, cluster = hosts[(i - 1) % len(hosts)]
            ds = datastores[(i - 1) % N_DS]
            is_win = rnd.random() < 0.35
            cpu = rnd.choice([1, 2, 2, 4, 4, 8, 16])
            mem_gb = rnd.choice([2, 4, 8, 8, 16, 32, 64])
            powered_on = rnd.random() > 0.15
            # IP planı: çoğu benzersiz; 9 VM aynı IP'yi paylaşır; 5 link-local; 20 IP'siz
            if i <= 9:
                ip = "198.18.250.1"
            elif i <= 14:
                ip = "169.254.77.77"
            elif i <= 34:
                ip = ""
            else:
                ip = f"198.18.{(i // 250) % 200}.{(i % 250) + 1}"
            vm_ref = f"vm-fake-{i:04d}"
            srv = Server(
                name=f"zz-fake-vm-{i:04d}", hostname=f"zz-fake-vm-{i:04d}", ip_address=ip or None, status="ONLINE" if powered_on else "OFFLINE",
                os_type="windows" if is_win else "rhel", os_version="Windows Server 2022" if is_win else "Red Hat Enterprise Linux 9.4",
                server_type="VIRTUAL", cpu_cores=cpu, memory_gb=mem_gb, tier=rnd.choice(["production", "staging", "development"]),
                hypervisor_id=hv.id, hypervisor_vm_id=vm_ref, vm_name=f"zz-fake-vm-{i:04d}", vm_cpu_count=cpu,
                vm_memory_mb=mem_gb * 1024, vm_disk_gb=rnd.choice([40, 80, 120, 250, 500]),
                vm_power_state="poweredOn" if powered_on else "poweredOff", vm_tools_status="guestToolsRunning",
                vm_tools_version_status="guestToolsCurrent", vm_cluster=cluster, vm_datastore=ds, vm_hardware_version="vmx-19",
                vm_last_sync=now, vm_host_name=host_name if powered_on else None, vm_host_ref=host_ref if powered_on else None,
                vm_guest_os_full="Fake Guest OS", vm_stats_as_of=now,
                node_exporter_installed=False, windows_exporter_installed=False, ai_ready=False,
            )
            db.add(srv)
            vm_rows.append((srv, vm_ref, host_name, cluster, ds, cpu, mem_gb, powered_on))
        db.flush()

        # ── VM metrikleri (saatlik, son 48 saat) ──
        batch = []
        for srv, vm_ref, host_name, cluster, ds, cpu, mem_gb, on in vm_rows:
            base_cpu = rnd.uniform(3, 70)
            base_mem = rnd.uniform(20, 85)
            for h in range(HISTORY_HOURS):
                ts = now - timedelta(hours=HISTORY_HOURS - h)
                batch.append(dict(
                    timestamp=ts, hypervisor_id=hv.id, vm_ref=vm_ref, vm_name=srv.name, server_id=srv.id,
                    host_name=host_name, cluster_name=cluster, datastore=ds,
                    power_state="poweredOn" if on else "poweredOff", num_cpu=cpu, mem_total_mb=mem_gb * 1024.0,
                    cpu_usage_pct=max(0.0, min(100.0, base_cpu + rnd.uniform(-8, 8))) if on else 0.0,
                    mem_usage_pct=max(0.0, min(100.0, base_mem + rnd.uniform(-4, 4))) if on else 0.0,
                    cpu_ready_pct=rnd.uniform(0, 3), disk_latency_ms=rnd.uniform(1, 12),
                ))
            if len(batch) >= 20000:
                db.bulk_insert_mappings(VirtVmMetric, batch)
                batch = []
        if batch:
            db.bulk_insert_mappings(VirtVmMetric, batch)

        # ── host metrikleri (saatlik) ──
        per_host_vms = {}
        for _, _, host_name, *_r in vm_rows:
            per_host_vms[host_name] = per_host_vms.get(host_name, 0) + 1
        hm = []
        for name, ref, cluster in hosts:
            vms = per_host_vms.get(name, 0)
            mem_total = 768 * 1024.0
            for h in range(HISTORY_HOURS):
                ts = now - timedelta(hours=HISTORY_HOURS - h)
                used = min(mem_total * 0.95, vms * 9000.0 * rnd.uniform(0.9, 1.1))
                hm.append(dict(
                    timestamp=ts, hypervisor_id=hv.id, host_name=name, host_ref=ref, cluster_name=cluster,
                    cpu_cores=64, cpu_threads=128, cpu_total_mhz=64 * 2600.0,
                    cpu_usage_pct=rnd.uniform(15, 60), cpu_usage_mhz=64 * 2600.0 * 0.4,
                    mem_total_mb=mem_total, mem_used_mb=used, mem_usage_pct=round(100 * used / mem_total, 1),
                    ds_total_gb=N_DS * 20000.0, ds_used_gb=N_DS * 20000.0 * 0.55, ds_usage_pct=55.0,
                    vms_total=vms, vms_running=int(vms * 0.85), connection_state="connected",
                    power_state="poweredOn", maintenance_mode=0, overall_status="green",
                ))
        db.bulk_insert_mappings(HypervisorHostMetric, hm)
        db.commit()
        print(f"Eklendi: hypervisor id={hv.id}, {len(hosts)} host, {N_CLUSTERS} cluster, {N_DS} datastore, "
              f"{n_vms} VM, {len(hm)} host metriği, {n_vms * HISTORY_HOURS} VM metriği.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ── OpenShift Virtualization (KubeVirt) ────────────────────────────────────────
# (ağırlık, guest-agent prettyName, os_release_id, os_version_id, ad öneki, windows mu)
_OCP_OS = [
    (7,  "Microsoft Windows Server 2022 Standard", "", "", "win2022", True),
    (6,  "Microsoft Windows Server 2019 Datacenter", "", "", "win2019", True),
    (3,  "Microsoft Windows Server 2016 Standard", "", "", "win2016", True),
    (6,  "Microsoft Windows 11 Pro", "", "", "win11", True),
    (3,  "Microsoft Windows 10 Enterprise", "", "", "win10", True),
    (9,  "Ubuntu 22.04.4 LTS", "ubuntu", "22.04", "ubuntu2204", False),
    (6,  "Ubuntu 24.04 LTS", "ubuntu", "24.04", "ubuntu2404", False),
    (4,  "Ubuntu 20.04.6 LTS", "ubuntu", "20.04", "ubuntu2004", False),
    (9,  "Red Hat Enterprise Linux 9.4 (Plow)", "rhel", "9.4", "rhel9", False),
    (7,  "Red Hat Enterprise Linux 8.10 (Ootpa)", "rhel", "8.10", "rhel8", False),
    (4,  "Red Hat Enterprise Linux Server 7.9 (Maipo)", "rhel", "7.9", "rhel7", False),
    (5,  "CentOS Linux 7 (Core)", "centos", "7", "centos7", False),
    (4,  "CentOS Stream 9", "centos", "9", "centos9", False),
    (2,  "CentOS Stream 8", "centos", "8", "centos8", False),
    (4,  "Rocky Linux 9.3 (Blue Onyx)", "rocky", "9.3", "rocky9", False),
    (2,  "Rocky Linux 8.9 (Green Obsidian)", "rocky", "8.9", "rocky8", False),
    (3,  "AlmaLinux 9.3 (Shamrock Pampas Cat)", "almalinux", "9.3", "alma9", False),
    (3,  "Oracle Linux Server 8.9", "ol", "8.9", "ol8", False),
    (2,  "Oracle Linux Server 9.2", "ol", "9.2", "ol9", False),
    (3,  "Debian GNU/Linux 12 (bookworm)", "debian", "12", "debian12", False),
    (2,  "Debian GNU/Linux 11 (bullseye)", "debian", "11", "debian11", False),
    (3,  "SUSE Linux Enterprise Server 15 SP5", "sles", "15.5", "sles15", False),
    (1,  "Fedora Linux 39 (Server Edition)", "fedora", "39", "fedora39", False),
    (1,  "Fedora Linux 40 (Cloud Edition)", "fedora", "40", "fedora40", False),
    (2,  "", "", "", "noagent", False),   # guest-agent yok → OS bilinmiyor
]
_OCP_NAMESPACES = ["fake-prod-web", "fake-prod-db", "fake-staging", "fake-dev", "fake-ci",
                   "fake-monitoring", "fake-legacy", "fake-vdi", "fake-erp", "fake-data"]
_OCP_MASTERS, _OCP_WORKERS = 3, 12


def seed_ocp(n_vms: int) -> None:
    rnd = random.Random(500)
    db = SessionLocal()
    try:
        if _fake_hv(db, OCP_HOST):
            print("Sahte OpenShift hypervisor zaten var; önce `cleanup-ocp` çalıştırın.")
            return
        now = datetime.now(timezone.utc)
        if db.query(OpenShiftCluster).filter(OpenShiftCluster.name == OCP_CLUSTER_NAME).first():
            print("Sahte OpenShift cluster kaydı zaten var; önce `cleanup-ocp` çalıştırın.")
            return
        ocp_cluster = OpenShiftCluster(
            name=OCP_CLUSTER_NAME, api_url=f"https://{OCP_HOST}:6443", connection_config={"verify_ssl": False},
            status="ONLINE", version="v1.29.5+fake", last_sync=now,
            meta_data={"fake_seed": True, "created": now.isoformat()},
        )
        db.add(ocp_cluster)
        db.flush()
        hv = Hypervisor(
            name=OCP_NAME, hypervisor_type=HypervisorType.OPENSHIFT_VIRT, hostname=OCP_HOST, ip_address="198.18.1.1",
            port=6443, username="fake", password=None, connection_config={}, status="fake",
            meta_data={"fake_seed": True, "created": now.isoformat(), "openshift_cluster_id": ocp_cluster.id},
        )
        db.add(hv)
        db.flush()

        # ── node'lar (master: VM taşımaz; worker: 96 çekirdek / 768 GB) ──
        nodes = [(f"fake-master-{i + 1}.ocp.invalid", "master", 16, 64) for i in range(_OCP_MASTERS)]
        nodes += [(f"fake-worker-{i + 1:02d}.ocp.invalid", "worker", 96, 768) for i in range(_OCP_WORKERS)]
        for ni, (name, role, cores, mem_gb) in enumerate(nodes):
            db.add(HypervisorHostInventory(
                hypervisor_id=hv.id, host_ref=f"ocp-node/{name}", host_name=name, product_full_name="OpenShift node",
                product_version="v1.29.5+fake", cluster_name=OCP_CLUSTER, overall_status="green",
                vnics=[{"device": "mgmt", "portgroup": "management", "ip_address": f"198.18.1.{10 + ni}"}],
                dns={"host_name": name, "address": None, "roles": role}, last_synced_at=now,
            ))
        workers = [n for n in nodes if n[1] == "worker"]

        # ── VM'ler (ağırlıklı karışık OS) ──
        weights = [w for w, *_ in _OCP_OS]
        vm_rows = []
        for i in range(1, n_vms + 1):
            _, pretty, rel_id, ver_id, slug, is_win = rnd.choices(_OCP_OS, weights=weights, k=1)[0]
            ns = rnd.choice(_OCP_NAMESPACES)
            name = f"zz-fake-ocp-{slug}-{i:04d}"
            node = workers[(i - 1) % len(workers)][0]
            if is_win:
                cpu, mem_gb = rnd.choice([2, 4, 4, 8, 8, 16]), rnd.choice([8, 16, 16, 32, 64])
                disk = rnd.choice([60, 100, 150, 250, 500])
            else:
                cpu, mem_gb = rnd.choice([1, 2, 2, 4, 4, 8]), rnd.choice([2, 4, 4, 8, 16, 32])
                disk = rnd.choice([20, 40, 80, 120, 250])
            running = rnd.random() > 0.12
            # IP planı: yalnız 198.19.0.0/16 (RFC 2544); 6 VM aynı IP'yi paylaşır (IP çakışması testi); durmuşların çoğu IP'siz
            if i <= 6:
                ip = "198.19.250.1"
            elif not running and rnd.random() < 0.7:
                ip = ""
            else:
                ip = f"198.19.{(i // 250) % 250}.{(i % 250) + 1}"
            mac = "02:fa:%02x:%02x:%02x:%02x" % (i >> 24 & 255, i >> 16 & 255, i >> 8 & 255, i & 255)
            netinfo = [{"name": "default", "mac": mac, "ip_address": ip or None, "binding": "pod", "model": "eth0",
                        "ips": [{"address": ip, "version": "v4"}] if ip else []}]
            srv = Server(
                name=name, hostname=name, ip_address=ip or None, status="ONLINE" if running else "OFFLINE",
                os_type=pretty or None, os_version=pretty or None,
                os_release_id=(rel_id if (rel_id and rnd.random() < 0.6) else None),
                os_version_id=(ver_id if (rel_id and rnd.random() < 0.6) else None),
                server_type="VIRTUAL", cpu_cores=cpu, memory_gb=mem_gb,
                tier=rnd.choice(["production", "staging", "development", "unknown"]),
                hypervisor_id=hv.id, hypervisor_vm_id=f"{ns}/{name}", vm_name=name, vm_guest_hostname=name,
                vm_guest_ip=ip or None, vm_cpu_count=cpu, vm_memory_mb=mem_gb * 1024, vm_disk_gb=disk,
                vm_power_state="Running" if running else "Stopped",
                vm_tools_status=("guest-agent" if pretty else "not-installed"), vm_network_info=netinfo,
                vm_cluster=OCP_CLUSTER, vm_last_sync=now, vm_host_name=node if running else None,
                vm_host_ref=f"ocp-node/{node}" if running else None, vm_guest_os_full=None, vm_stats_as_of=now,
                node_exporter_installed=False, windows_exporter_installed=False, ai_ready=False,
            )
            db.add(srv)
            vm_rows.append((srv, node, cpu, mem_gb, running))
        db.flush()

        # ── node metrikleri (saatlik, son 48 saat; gerçek OCP sync'iyle aynı sütunlar) ──
        placed = {}
        for _srv, node, _cpu, mem_gb, running in vm_rows:
            if running:
                placed[node] = placed.get(node, 0) + mem_gb
        # Node BAŞINA VM sayısı (envanterle aynı kural: yalnız çalışan VM node'a yerleşir).
        # Eskiden cluster toplamı her node'a yazılıyordu ve dashboard hostları toplayınca
        # N kat şişiyordu (500 VM × 15 node = 7500).
        per_node: dict = {}
        for _srv, node, _cpu, _mem, running in vm_rows:
            if not running:
                continue
            tot, on = per_node.get(node, (0, 0))
            per_node[node] = (tot + 1, on + 1)
        hm = []
        for name, role, cores, mem_gb in nodes:
            mem_total = mem_gb * 1024.0
            base_mem_pct = (min(0.92, placed.get(name, 0) * 0.6 / mem_gb) * 100) if role == "worker" else rnd.uniform(35, 55)
            for h in range(HISTORY_HOURS):
                ts = now - timedelta(hours=HISTORY_HOURS - h)
                mem_pct = max(1.0, min(99.0, base_mem_pct + rnd.uniform(-4, 4)))
                hm.append(dict(
                    timestamp=ts, hypervisor_id=hv.id, host_name=name, host_ref=f"ocp-node/{name}",
                    cpu_usage_pct=round(rnd.uniform(15, 65) if role == "worker" else rnd.uniform(10, 35), 1),
                    cpu_cores=cores, mem_used_mb=round(mem_total * mem_pct / 100, 1), mem_total_mb=mem_total,
                    mem_usage_pct=round(mem_pct, 1), ds_used_gb=60000.0, ds_total_gb=120000.0, ds_usage_pct=50.0,
                    vms_running=per_node.get(name, (0, 0))[1], vms_total=per_node.get(name, (0, 0))[0],
                    connection_state="connected", power_state="poweredOn",
                    maintenance_mode=0, cluster_name=OCP_CLUSTER, overall_status="green",
                ))
        db.bulk_insert_mappings(HypervisorHostMetric, hm)

        # ── OpenShift modülü: node / proje / workload / metrik (openshift_* + ocp_resource_metrics) ──
        node_pods: dict = {}
        node_vm_cpu: dict = {}
        node_vm_mem: dict = {}
        for srv, node, cpu, mem_gb, running in vm_rows:
            if running:
                node_pods[node] = node_pods.get(node, 0) + 1
                node_vm_cpu[node] = node_vm_cpu.get(node, 0) + cpu
                node_vm_mem[node] = node_vm_mem.get(node, 0) + mem_gb
        for ni, (name, role, cores, mem_gb) in enumerate(nodes):
            cpu_req = node_vm_cpu.get(name, 0) + (6 if role == "worker" else 3)
            mem_req = node_vm_mem.get(name, 0) + (24 if role == "worker" else 12)
            db.add(OpenShiftNode(
                cluster_id=ocp_cluster.id, name=name, role=role, status="Ready", cpu_cores=float(cores),
                memory_gb=float(mem_gb), cpu_usage_pct=round(min(95.0, 100.0 * cpu_req / cores), 1),
                memory_usage_pct=round(min(95.0, 100.0 * mem_req / mem_gb), 1), kubelet_version="v1.29.5+fake",
                os_image="Red Hat Enterprise Linux CoreOS 416.fake", pod_count=node_pods.get(name, 0) + 12,
                meta_data={"cpu_allocatable": cores - 1, "memory_allocatable_gb": mem_gb - 4, "cpu_requested": cpu_req,
                           "memory_requested_gb": mem_req, "internal_ip": f"198.18.1.{10 + ni}", "external_ip": "",
                           "hostname": name, "ip_address": f"198.18.1.{10 + ni}"},
            ))
        sys_ns = ["openshift-cnv", "openshift-storage", "openshift-monitoring"]
        ns_vms: dict = {}
        for srv, node, cpu, mem_gb, running in vm_rows:
            ns = srv.hypervisor_vm_id.split("/", 1)[0]
            ns_vms[ns] = ns_vms.get(ns, 0) + 1
        for ns in _OCP_NAMESPACES + sys_ns:
            is_sys = ns in sys_ns
            db.add(OpenShiftProject(
                cluster_id=ocp_cluster.id, name=ns, status="Active", pod_count=ns_vms.get(ns, 0) + (8 if is_sys else 4),
                deployment_count=(5 if is_sys else 2), route_count=(0 if is_sys else 1), display_name=ns,
                requester="fake-admin", meta_data={"is_system": is_sys},
            ))
        wl = []
        for srv, node, cpu, mem_gb, running in vm_rows:
            ns, vname = srv.hypervisor_vm_id.split("/", 1)
            wl.append(dict(
                cluster_id=ocp_cluster.id, project=ns, kind="pod", name=f"virt-launcher-{vname}-x{srv.id % 100000:05d}"[:250],
                status="Running" if running else "Succeeded", node_name=node if running else None,
                restart_count=0, ready="2/2" if running else "0/2", host=None,
                meta_data={"phase": "Running" if running else "Succeeded", "owner_kind": "VirtualMachineInstance",
                           "owner_name": vname, "cpu_request": cpu, "memory_request_gb": mem_gb},
            ))
        for ns in _OCP_NAMESPACES + sys_ns:
            for di in range(2):
                wl.append(dict(cluster_id=ocp_cluster.id, project=ns, kind="deployment", name=f"fake-app-{di + 1}",
                               status="Available", node_name=None, restart_count=0, ready="1/1", host=None,
                               meta_data={"phase": "Available"}))
        db.bulk_insert_mappings(OpenShiftWorkload, wl)

        # ocp_resource_metrics: node + vm (saatlik, 48 saat)
        rm = []
        for h in range(HISTORY_HOURS):
            ts = now - timedelta(hours=HISTORY_HOURS - h)
            for ni, (name, role, cores, mem_gb) in enumerate(nodes):
                cpu_pct = rnd.uniform(15, 65) if role == "worker" else rnd.uniform(10, 35)
                mem_pct = max(5.0, min(95.0, (placed.get(name, 0) * 0.6 / mem_gb * 100 if role == "worker" else 45) + rnd.uniform(-4, 4)))
                rm.append(dict(
                    timestamp=ts, cluster_id=ocp_cluster.id, kind="node", object_key=name, name=name, namespace=None,
                    role=role, status="Ready", node_name=name, cpu_used_cores=round(cores * cpu_pct / 100, 2),
                    memory_used_gb=round(mem_gb * mem_pct / 100, 1), cpu_allocatable=float(cores - 1),
                    memory_allocatable_gb=float(mem_gb - 4), cpu_pct=round(cpu_pct, 1), memory_pct=round(mem_pct, 1),
                    restarts=None))
            for srv, node, cpu, mem_gb, running in vm_rows:
                if not running:
                    continue
                ns, vname = srv.hypervisor_vm_id.split("/", 1)
                cpu_pct = rnd.uniform(3, 70)
                mem_pct = rnd.uniform(20, 85)
                rm.append(dict(
                    timestamp=ts, cluster_id=ocp_cluster.id, kind="vm", object_key=srv.hypervisor_vm_id, name=vname,
                    namespace=ns, role=None, status="Running", node_name=node, cpu_used_cores=round(cpu * cpu_pct / 100, 3),
                    memory_used_gb=round(mem_gb * mem_pct / 100, 2), cpu_allocatable=float(cpu),
                    memory_allocatable_gb=float(mem_gb), cpu_pct=round(cpu_pct, 1), memory_pct=round(mem_pct, 1), restarts=0))
            if len(rm) >= 20000:
                db.bulk_insert_mappings(OcpResourceMetric, rm)
                rm = []
        if rm:
            db.bulk_insert_mappings(OcpResourceMetric, rm)
        db.commit()
        from collections import Counter
        mix = Counter(("windows" if "Windows" in (r[0].os_type or "") else (r[0].os_type or "bilinmiyor").split()[0])
                      for r in vm_rows)
        print(f"Eklendi: hypervisor id={hv.id}, {len(nodes)} node ({_OCP_WORKERS} worker), {n_vms} VM "
              f"({vms_running} çalışıyor), {len(hm)} node metriği; OpenShift modülü cluster id={ocp_cluster.id} "
              f"({OCP_CLUSTER_NAME}).")
        print("OS dağılımı:", dict(mix.most_common()))
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "seed":
        seed(int(sys.argv[2]) if len(sys.argv) > 2 else 1000)
    elif cmd == "cleanup":
        cleanup()
    elif cmd == "seed-ocp":
        seed_ocp(int(sys.argv[2]) if len(sys.argv) > 2 else 500)
    elif cmd == "cleanup-ocp":
        cleanup(OCP_HOST)
    elif cmd == "cleanup-all":
        cleanup()
        cleanup(OCP_HOST)
    else:
        print(__doc__)
