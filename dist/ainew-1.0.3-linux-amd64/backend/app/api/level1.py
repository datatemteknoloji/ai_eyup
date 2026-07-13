"""
Level 1 Operasyon API
Birinci seviye destek ekibine yönelik runbook tabanlı SSH operasyonları.
Her operasyon: kategori, açıklama, parametreler ve SSH komut dizisinden oluşur.
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.server import Server
from app.models.credential import GlobalCredential
from app.core.encryption import decrypt_secret
from app.services.ssh_connect import connect_ssh

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Operasyon Kataloğu ────────────────────────────────────────────────────────

CATEGORIES = [
    {"id": "disk",    "name": "Disk & Depolama",   "icon": "HardDrive",   "color": "blue"},
    {"id": "asm",     "name": "Oracle ASM",         "icon": "Database",    "color": "orange"},
    {"id": "lvm",     "name": "LVM Yönetimi",       "icon": "Layers",      "color": "purple"},
    {"id": "service", "name": "Servis Yönetimi",    "icon": "Settings",    "color": "green"},
    {"id": "user",    "name": "Kullanıcı & Erişim", "icon": "Users",       "color": "teal"},
    {"id": "network", "name": "Ağ & Mount",         "icon": "Network",     "color": "indigo"},
    {"id": "log",     "name": "Log & Analiz",       "icon": "FileText",    "color": "slate"},
]

OPERATIONS: Dict[str, Dict[str, Any]] = {

    # ── Disk & Depolama ───────────────────────────────────────────────────────
    "disk_list": {
        "id": "disk_list",
        "name": "Diskleri Listele",
        "category": "disk",
        "description": "Sunucudaki tüm disk, partition ve mount point'leri gösterir.",
        "params": [],
        "sudo": False,
        "commands": [
            "echo '━━━━━━━━ BLOCK DEVICES ━━━━━━━━'",
            "lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,MODEL 2>/dev/null || lsblk",
            "echo ''",
            "echo '━━━━━━━━ DISK USAGE ━━━━━━━━'",
            "df -h 2>/dev/null | column -t",
        ],
    },
    "disk_fdisk": {
        "id": "disk_fdisk",
        "name": "Disk Detayı (fdisk)",
        "category": "disk",
        "description": "Belirtilen diskin partition tablosunu ve sektör bilgisini gösterir.",
        "params": [
            {"id": "disk_path", "label": "Disk Yolu", "placeholder": "/dev/sdb", "required": True,
             "hint": "Örn: /dev/sdb — lsblk ile önce disk adını öğrenin"},
        ],
        "sudo": True,
        "commands": [
            "echo '━━━━━━━━ PARTITION TABLE ━━━━━━━━'",
            "sudo fdisk -l {disk_path}",
            "echo ''",
            "echo '━━━━━━━━ BLOCK INFO ━━━━━━━━'",
            "sudo blkid {disk_path}* 2>/dev/null || true",
        ],
    },
    "disk_partition_create": {
        "id": "disk_partition_create",
        "name": "Partition Oluştur (parted)",
        "category": "disk",
        "description": "Diskte yeni bir GPT partition oluşturur. Dikkat: mevcut veriler etkilenebilir.",
        "params": [
            {"id": "disk_path", "label": "Disk Yolu", "placeholder": "/dev/sdb", "required": True,
             "hint": "Örn: /dev/sdb"},
            {"id": "part_start", "label": "Başlangıç", "placeholder": "0%", "required": True,
             "hint": "Örn: 0% veya 1MiB"},
            {"id": "part_end", "label": "Bitiş", "placeholder": "100%", "required": True,
             "hint": "Örn: 100% veya 50GiB"},
        ],
        "sudo": True,
        "commands": [
            "sudo parted {disk_path} --script mklabel gpt",
            "sudo parted {disk_path} --script mkpart primary {part_start} {part_end}",
            "sudo parted {disk_path} --script print",
            "sudo partprobe {disk_path}",
            "echo 'Partition oluşturuldu. lsblk ile doğrulayın.'",
        ],
    },
    "disk_format": {
        "id": "disk_format",
        "name": "Dosya Sistemi Oluştur (mkfs)",
        "category": "disk",
        "description": "Partition veya disk üzerinde dosya sistemi oluşturur.",
        "params": [
            {"id": "partition", "label": "Partition/Disk", "placeholder": "/dev/sdb1", "required": True,
             "hint": "Örn: /dev/sdb1"},
            {"id": "fs_type", "label": "Dosya Sistemi", "placeholder": "xfs",
             "options": ["xfs", "ext4", "ext3"], "required": True},
            {"id": "label", "label": "Etiket (opsiyonel)", "placeholder": "data1", "required": False},
        ],
        "sudo": True,
        "commands": [
            "sudo mkfs.{fs_type} {label_flag} {partition}",
            "sudo blkid {partition}",
            "echo 'Dosya sistemi oluşturuldu.'",
        ],
        "command_builder": "disk_format",
    },
    "disk_mount_add": {
        "id": "disk_mount_add",
        "name": "Mount Point Ekle",
        "category": "disk",
        "description": "Dosya sistemini kalıcı olarak /etc/fstab'a ekler ve mount eder.",
        "params": [
            {"id": "device", "label": "Cihaz", "placeholder": "/dev/sdb1", "required": True,
             "hint": "Örn: /dev/sdb1 veya UUID=..."},
            {"id": "mount_point", "label": "Mount Dizin", "placeholder": "/data", "required": True,
             "hint": "Örn: /data — dizin yoksa otomatik oluşturulur"},
            {"id": "fs_type", "label": "Dosya Sistemi", "placeholder": "xfs",
             "options": ["xfs", "ext4", "ext3", "nfs", "cifs"], "required": True},
            {"id": "mount_opts", "label": "Mount Seçenekleri", "placeholder": "defaults,nofail",
             "required": False, "hint": "Örn: defaults,nofail,noatime"},
        ],
        "sudo": True,
        "commands": [
            "sudo mkdir -p {mount_point}",
            "echo '{device} {mount_point} {fs_type} {mount_opts_val} 0 0' | sudo tee -a /etc/fstab",
            "sudo mount -a",
            "df -h {mount_point}",
            "echo 'Mount eklendi ve aktif edildi.'",
        ],
        "command_builder": "disk_mount_add",
    },

    # ── Oracle ASM ────────────────────────────────────────────────────────────
    "asm_scan": {
        "id": "asm_scan",
        "name": "ASM Disk Tara",
        "category": "asm",
        "description": "Sistemdeki ASM disk adaylarını ve mevcut ASM disklerini listeler.",
        "params": [],
        "sudo": True,
        "commands": [
            "echo '━━━━━━━━ ORACLEASM DISKLER ━━━━━━━━'",
            "sudo oracleasm listdisks 2>/dev/null || echo 'oracleasm bulunamadı'",
            "echo ''",
            "echo '━━━━━━━━ BLKID (tüm diskler) ━━━━━━━━'",
            "sudo blkid 2>/dev/null",
            "echo ''",
            "echo '━━━━━━━━ LSBLK ━━━━━━━━'",
            "lsblk -o NAME,SIZE,TYPE,VENDOR,MODEL,FSTYPE",
        ],
    },
    "asm_label": {
        "id": "asm_label",
        "name": "ASM Disk Etiketle",
        "category": "asm",
        "description": "Belirtilen disk cihazını Oracle ASM disk olarak etiketler (oracleasm createdisk).",
        "params": [
            {"id": "asm_name", "label": "ASM Disk Adı", "placeholder": "DATA01", "required": True,
             "hint": "Büyük harf, örn: DATA01, FRA01, REDO01"},
            {"id": "device", "label": "Disk Cihazı", "placeholder": "/dev/sdc", "required": True,
             "hint": "Örn: /dev/sdc — partition değil RAW disk"},
        ],
        "sudo": True,
        "commands": [
            "echo 'Mevcut ASM diskler:'",
            "sudo oracleasm listdisks",
            "echo ''",
            "echo 'Etiketleniyor: {asm_name} → {device}'",
            "sudo oracleasm createdisk {asm_name} {device}",
            "echo ''",
            "echo 'Doğrulama:'",
            "sudo oracleasm listdisks",
            "sudo oracleasm querydisk {asm_name}",
        ],
    },
    "asm_delete_label": {
        "id": "asm_delete_label",
        "name": "ASM Disk Etiketi Kaldır",
        "category": "asm",
        "description": "ASM disk etiketini kaldırır (oracleasm deletedisk). Disk önce ASM'den çıkarılmış olmalıdır.",
        "params": [
            {"id": "asm_name", "label": "ASM Disk Adı", "placeholder": "DATA01", "required": True},
        ],
        "sudo": True,
        "commands": [
            "echo 'Mevcut diskler:'",
            "sudo oracleasm listdisks",
            "echo ''",
            "sudo oracleasm deletedisk {asm_name}",
            "echo 'Silindi. Kalan diskler:'",
            "sudo oracleasm listdisks",
        ],
    },
    "asm_diskgroup_check": {
        "id": "asm_diskgroup_check",
        "name": "ASM Disk Group Durumu",
        "category": "asm",
        "description": "Oracle ASM disk group kullanım ve durum bilgisini gösterir (oracle kullanıcısı ile).",
        "params": [
            {"id": "oracle_home", "label": "ORACLE_HOME", "placeholder": "/u01/app/grid/product/19c/grid",
             "required": True},
            {"id": "oracle_sid", "label": "ASM SID", "placeholder": "+ASM", "required": True},
        ],
        "sudo": False,
        "commands": [
            "export ORACLE_HOME={oracle_home}",
            "export ORACLE_SID={oracle_sid}",
            "export PATH=$ORACLE_HOME/bin:$PATH",
            "$ORACLE_HOME/bin/asmcmd lsdg 2>/dev/null || echo 'ASMCMD çalıştırılamadı — oracle user yetkisi kontrol edin'",
        ],
    },

    # ── LVM ───────────────────────────────────────────────────────────────────
    "lvm_status": {
        "id": "lvm_status",
        "name": "LVM Yapısını Göster",
        "category": "lvm",
        "description": "PV, VG ve LV bilgilerini listeler.",
        "params": [],
        "sudo": True,
        "commands": [
            "echo '━━━━━━━━ PHYSICAL VOLUMES ━━━━━━━━'",
            "sudo pvs 2>/dev/null || echo 'LVM kurulu değil'",
            "echo ''",
            "echo '━━━━━━━━ VOLUME GROUPS ━━━━━━━━'",
            "sudo vgs 2>/dev/null",
            "echo ''",
            "echo '━━━━━━━━ LOGICAL VOLUMES ━━━━━━━━'",
            "sudo lvs 2>/dev/null",
        ],
    },
    "lvm_pvcreate": {
        "id": "lvm_pvcreate",
        "name": "PV Oluştur (pvcreate)",
        "category": "lvm",
        "description": "Diskin/partition'ın LVM Physical Volume olarak işaretler.",
        "params": [
            {"id": "device", "label": "Disk/Partition", "placeholder": "/dev/sdb", "required": True,
             "hint": "Örn: /dev/sdb veya /dev/sdb1"},
        ],
        "sudo": True,
        "commands": [
            "sudo pvcreate {device}",
            "sudo pvs",
        ],
    },
    "lvm_vgextend": {
        "id": "lvm_vgextend",
        "name": "VG'ye Disk Ekle (vgextend)",
        "category": "lvm",
        "description": "Mevcut Volume Group'a yeni PV ekler.",
        "params": [
            {"id": "vg_name", "label": "Volume Group", "placeholder": "vg_data", "required": True},
            {"id": "device", "label": "Yeni Disk/PV", "placeholder": "/dev/sdb", "required": True},
        ],
        "sudo": True,
        "commands": [
            "sudo pvcreate {device} 2>/dev/null || true",
            "sudo vgextend {vg_name} {device}",
            "sudo vgs {vg_name}",
        ],
    },
    "lvm_lvextend": {
        "id": "lvm_lvextend",
        "name": "LV Genişlet (lvextend)",
        "category": "lvm",
        "description": "Logical Volume'u büyütür ve dosya sistemini genişletir.",
        "params": [
            {"id": "lv_path", "label": "LV Yolu", "placeholder": "/dev/vg_data/lv_app", "required": True,
             "hint": "Örn: /dev/vg_data/lv_app"},
            {"id": "size", "label": "Boyut", "placeholder": "+10G", "required": True,
             "hint": "Örn: +10G (ekle) veya 50G (tam boyut)"},
            {"id": "fs_type", "label": "Dosya Sistemi", "placeholder": "xfs",
             "options": ["xfs", "ext4", "ext3"], "required": True},
        ],
        "sudo": True,
        "commands": [
            "sudo lvextend -L {size} {lv_path}",
            "echo 'Dosya sistemi genişletiliyor...'",
            "sudo lvextend_fs_resize {lv_path} {fs_type}",
            "df -h {lv_path}",
        ],
        "command_builder": "lvm_lvextend",
    },

    # ── Servis Yönetimi ───────────────────────────────────────────────────────
    "service_list": {
        "id": "service_list",
        "name": "Servisleri Listele",
        "category": "service",
        "description": "Sistemdeki tüm aktif/başarısız servisleri listeler.",
        "params": [],
        "sudo": False,
        "commands": [
            "echo '━━━━━━━━ AKTİF SERVİSLER ━━━━━━━━'",
            "systemctl list-units --type=service --state=running --no-pager | head -40",
            "echo ''",
            "echo '━━━━━━━━ BAŞARISIZ SERVİSLER ━━━━━━━━'",
            "systemctl list-units --type=service --state=failed --no-pager",
        ],
    },
    "service_status": {
        "id": "service_status",
        "name": "Servis Durumu",
        "category": "service",
        "description": "Belirtilen servisin güncel durumunu gösterir.",
        "params": [
            {"id": "service_name", "label": "Servis Adı", "placeholder": "nginx",
             "required": True, "hint": "Örn: nginx, httpd, mysql, oracle, postgresql"},
        ],
        "sudo": False,
        "commands": [
            "systemctl status {service_name} --no-pager -l | head -50",
        ],
    },
    "service_manage": {
        "id": "service_manage",
        "name": "Servis Başlat / Durdur / Yeniden Başlat",
        "category": "service",
        "description": "Bir servis üzerinde start/stop/restart/enable/disable işlemi yapar.",
        "params": [
            {"id": "service_name", "label": "Servis Adı", "placeholder": "nginx", "required": True},
            {"id": "action", "label": "İşlem", "placeholder": "restart",
             "options": ["start", "stop", "restart", "reload", "enable", "disable"],
             "required": True},
        ],
        "sudo": True,
        "commands": [
            "sudo systemctl {action} {service_name}",
            "systemctl status {service_name} --no-pager | head -20",
        ],
    },

    # ── Kullanıcı & Erişim ────────────────────────────────────────────────────
    "user_list": {
        "id": "user_list",
        "name": "Kullanıcıları Listele",
        "category": "user",
        "description": "Sistemdeki kullanıcı hesaplarını ve grupları listeler.",
        "params": [],
        "sudo": False,
        "commands": [
            "echo '━━━━━━━━ NORMAL KULLANICLAR (UID≥1000) ━━━━━━━━'",
            "awk -F: '$3>=1000 && $3<65534 {print $1\": \"$5\" | UID=\"$3\" | Shell=\"$7}' /etc/passwd",
            "echo ''",
            "echo '━━━━━━━━ SUDOERS ━━━━━━━━'",
            "getent group sudo wheel 2>/dev/null || true",
        ],
    },
    "user_create": {
        "id": "user_create",
        "name": "Kullanıcı Oluştur",
        "category": "user",
        "description": "Yeni sistem kullanıcısı oluşturur ve ev dizinini hazırlar.",
        "params": [
            {"id": "username", "label": "Kullanıcı Adı", "placeholder": "jdoe", "required": True},
            {"id": "full_name", "label": "Tam Ad", "placeholder": "John Doe", "required": False},
            {"id": "shell", "label": "Shell", "placeholder": "/bin/bash",
             "options": ["/bin/bash", "/bin/sh", "/sbin/nologin"], "required": True},
            {"id": "groups", "label": "Ek Gruplar", "placeholder": "docker,wheel", "required": False,
             "hint": "Virgülle ayrılmış grup adları"},
        ],
        "sudo": True,
        "commands": [
            "sudo useradd -m -s {shell} -c '{full_name}' {username}",
            "echo 'Kullanıcı oluşturuldu.'",
            "id {username}",
        ],
        "command_builder": "user_create",
    },
    "user_sudo": {
        "id": "user_sudo",
        "name": "Sudo Yetki Ver / Kaldır",
        "category": "user",
        "description": "Kullanıcıya sudo yetkisi verir veya kaldırır.",
        "params": [
            {"id": "username", "label": "Kullanıcı Adı", "placeholder": "jdoe", "required": True},
            {"id": "action", "label": "İşlem", "placeholder": "ekle",
             "options": ["ekle", "kaldır"], "required": True},
        ],
        "sudo": True,
        "commands": [],
        "command_builder": "user_sudo",
    },

    # ── Ağ & Mount ────────────────────────────────────────────────────────────
    "net_info": {
        "id": "net_info",
        "name": "Ağ Arayüzleri",
        "category": "network",
        "description": "Ağ arayüzlerini, IP adreslerini ve routing tablosunu gösterir.",
        "params": [],
        "sudo": False,
        "commands": [
            "echo '━━━━━━━━ IP ADRESLERI ━━━━━━━━'",
            "ip addr show",
            "echo ''",
            "echo '━━━━━━━━ ROUTING TABLOSU ━━━━━━━━'",
            "ip route show",
        ],
    },
    "nfs_mount": {
        "id": "nfs_mount",
        "name": "NFS Share Mount",
        "category": "network",
        "description": "Uzak NFS share'i kalıcı olarak mount eder.",
        "params": [
            {"id": "nfs_server", "label": "NFS Sunucu", "placeholder": "192.168.1.10", "required": True},
            {"id": "nfs_path", "label": "NFS Yol", "placeholder": "/exports/data", "required": True},
            {"id": "local_path", "label": "Yerel Mount Dizin", "placeholder": "/mnt/nfsdata", "required": True},
            {"id": "mount_opts", "label": "Seçenekler", "placeholder": "defaults,nofail",
             "required": False},
        ],
        "sudo": True,
        "commands": [
            "sudo mkdir -p {local_path}",
            "echo '{nfs_server}:{nfs_path} {local_path} nfs {mount_opts_val} 0 0' | sudo tee -a /etc/fstab",
            "sudo mount -a",
            "df -h {local_path}",
        ],
        "command_builder": "nfs_mount",
    },

    # ── Log & Analiz ──────────────────────────────────────────────────────────
    "log_tail": {
        "id": "log_tail",
        "name": "Log Son Satırlar",
        "category": "log",
        "description": "Belirtilen log dosyasının son satırlarını getirir.",
        "params": [
            {"id": "log_path", "label": "Log Dosyası", "placeholder": "/var/log/messages",
             "required": True,
             "hint": "Örn: /var/log/messages, /var/log/syslog, /var/log/oracle/alert.log"},
            {"id": "lines", "label": "Satır Sayısı", "placeholder": "100",
             "required": False, "hint": "Varsayılan: 100"},
        ],
        "sudo": False,
        "commands": [
            "tail -n {lines_val} {log_path} 2>/dev/null || sudo tail -n {lines_val} {log_path}",
        ],
        "command_builder": "log_tail",
    },
    "log_search": {
        "id": "log_search",
        "name": "Log'da Ara",
        "category": "log",
        "description": "Log dosyasında belirtilen kalıbı arar.",
        "params": [
            {"id": "log_path", "label": "Log Dosyası", "placeholder": "/var/log/messages", "required": True},
            {"id": "pattern", "label": "Arama Kalıbı", "placeholder": "ORA-", "required": True,
             "hint": "Regex destekler. Örn: error|ERROR|FAIL"},
            {"id": "context", "label": "Bağlam Satırı", "placeholder": "3",
             "required": False, "hint": "Eşleşme öncesi/sonrası kaç satır"},
        ],
        "sudo": False,
        "commands": [
            "grep -n -E {context_flag} '{pattern}' {log_path} 2>/dev/null | tail -100 || sudo grep -n -E {context_flag} '{pattern}' {log_path} | tail -100",
        ],
        "command_builder": "log_search",
    },
    "sys_info": {
        "id": "sys_info",
        "name": "Sistem Bilgisi",
        "category": "log",
        "description": "CPU, RAM, uptime ve OS bilgisini özetler.",
        "params": [],
        "sudo": False,
        "commands": [
            "echo '━━━━━━━━ OS ━━━━━━━━'",
            "cat /etc/os-release 2>/dev/null | grep -E 'NAME|VERSION'",
            "uname -r",
            "echo ''",
            "echo '━━━━━━━━ UPTIME & LOAD ━━━━━━━━'",
            "uptime",
            "echo ''",
            "echo '━━━━━━━━ CPU ━━━━━━━━'",
            "lscpu 2>/dev/null | grep -E 'Architecture|CPU\\(s\\)|Model name|Thread'",
            "echo ''",
            "echo '━━━━━━━━ MEMORY ━━━━━━━━'",
            "free -h",
            "echo ''",
            "echo '━━━━━━━━ DISK ━━━━━━━━'",
            "df -h | grep -v tmpfs | column -t",
        ],
    },
}


def _get_operations_list() -> List[Dict]:
    """Return a cleaned list of operations (without command details for listing)."""
    result = []
    for op in OPERATIONS.values():
        result.append({
            "id": op["id"],
            "name": op["name"],
            "category": op["category"],
            "description": op["description"],
            "params": op.get("params", []),
        })
    return result


def _build_commands(op_id: str, params: Dict[str, str]) -> List[str]:
    """
    Build the final command list for a given operation with parameter substitution.
    Special command_builders handle multi-step logic.
    """
    op = OPERATIONS.get(op_id)
    if not op:
        raise ValueError(f"Bilinmeyen operasyon: {op_id}")

    builder = op.get("command_builder")
    cmds: List[str] = list(op.get("commands", []))

    # Special builders for operations with conditional logic
    if builder == "disk_format":
        label = params.get("label", "").strip()
        label_flag = f"-L {label}" if label else ""
        params = {**params, "label_flag": label_flag}

    elif builder == "disk_mount_add":
        opts = params.get("mount_opts", "").strip() or "defaults,nofail"
        params = {**params, "mount_opts_val": opts}

    elif builder == "lvm_lvextend":
        fs = params.get("fs_type", "xfs")
        lv = params.get("lv_path", "")
        resize_cmd = "sudo resize2fs" if fs in ("ext4", "ext3") else "sudo xfs_growfs"
        cmds = [
            f"sudo lvextend -L {params.get('size', '+1G')} {lv}",
            f"{resize_cmd} {lv}",
            f"df -h",
        ]

    elif builder == "user_create":
        groups = params.get("groups", "").strip()
        group_flag = f"-G {groups}" if groups else ""
        full_name = params.get("full_name", "").strip()
        # Inject group_flag into commands
        shell = params.get("shell", "/bin/bash")
        username = params.get("username", "")
        cmds = [
            f"sudo useradd -m -s {shell} -c '{full_name}' {group_flag} {username}",
            "echo 'Kullanıcı oluşturuldu.'",
            f"id {username}",
        ]

    elif builder == "user_sudo":
        username = params.get("username", "")
        action = params.get("action", "ekle")
        if action == "ekle":
            cmds = [
                f"sudo usermod -aG sudo {username} 2>/dev/null || sudo usermod -aG wheel {username}",
                f"id {username}",
                "echo 'Sudo yetkisi verildi.'",
            ]
        else:
            cmds = [
                f"sudo gpasswd -d {username} sudo 2>/dev/null || true",
                f"sudo gpasswd -d {username} wheel 2>/dev/null || true",
                f"id {username}",
                "echo 'Sudo yetkisi kaldırıldı.'",
            ]

    elif builder == "nfs_mount":
        opts = params.get("mount_opts", "").strip() or "defaults,nofail"
        params = {**params, "mount_opts_val": opts}

    elif builder == "log_tail":
        lines = params.get("lines", "").strip() or "100"
        params = {**params, "lines_val": lines}

    elif builder == "log_search":
        context = params.get("context", "").strip()
        context_flag = f"-C {context}" if context else ""
        params = {**params, "context_flag": context_flag}

    # Substitute all parameters into commands
    result = []
    for cmd in cmds:
        for k, v in params.items():
            cmd = cmd.replace("{" + k + "}", str(v))
        result.append(cmd)
    return result


def _get_ssh_creds(server: Server, db: Session):
    """Resolve SSH credentials for a server."""
    cfg = server.connection_config or {}
    gc = db.query(GlobalCredential).filter(GlobalCredential.is_default == True).first()

    username = cfg.get("username") or (gc.username if gc else None)
    raw_pw = cfg.get("password") or (gc.password if gc else None)
    raw_key = cfg.get("private_key") or (gc.private_key if gc else None)
    raw_sudo = cfg.get("sudo_password") or (gc.sudo_password if gc else None)
    port = int(cfg.get("port") or (gc.port if gc else 22) or 22)

    return {
        "host": server.ip_address or server.hostname,
        "port": port,
        "username": username,
        "password": decrypt_secret(raw_pw) if raw_pw else None,
        "private_key": decrypt_secret(raw_key) if raw_key else None,
        "sudo_password": decrypt_secret(raw_sudo) if raw_sudo else None,
    }


def _run_ssh(creds: dict, commands: List[str]) -> Dict[str, Any]:
    """Execute command list over SSH, return combined output."""
    import io
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    pkey = None
    if creds.get("private_key"):
        for cls in (paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey):
            try:
                pkey = cls.from_private_key(io.StringIO(creds["private_key"]))
                break
            except Exception:
                pass

    try:
        connect_ssh(
            client,
            hostname=creds["host"], username=creds["username"], port=creds["port"],
            password=creds.get("password"), pkey=pkey, timeout=15,
        )
    except Exception as e:
        return {"success": False, "output": f"SSH bağlantı hatası: {e}", "exit_code": -1}

    # Join all commands and run as a single shell session
    full_script = "\n".join(commands)
    combined_output = []
    exit_code = 0
    try:
        _, stdout, stderr = client.exec_command(full_script, timeout=120)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        exit_code = stdout.channel.recv_exit_status()
        if out:
            combined_output.append(out)
        if err:
            combined_output.append(f"\n[STDERR]\n{err}")
    except Exception as e:
        combined_output.append(f"Komut hatası: {e}")
        exit_code = -1
    finally:
        client.close()

    return {
        "success": exit_code == 0,
        "output": "\n".join(combined_output),
        "exit_code": exit_code,
    }


# ── Request Schemas ───────────────────────────────────────────────────────────

class RunOperationRequest(BaseModel):
    server_id: int
    operation_id: str
    params: Dict[str, str] = {}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/categories")
def get_categories():
    return {"categories": CATEGORIES}


@router.get("/operations")
def list_operations(category: Optional[str] = None):
    ops = _get_operations_list()
    if category:
        ops = [o for o in ops if o["category"] == category]
    return {"operations": ops}


@router.post("/run")
def run_operation(req: RunOperationRequest, db: Session = Depends(get_db)):
    """Execute a Level 1 operation on a server via SSH."""
    server = db.query(Server).filter(Server.id == req.server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Sunucu bulunamadı")

    op = OPERATIONS.get(req.operation_id)
    if not op:
        raise HTTPException(status_code=404, detail=f"Operasyon bulunamadı: {req.operation_id}")

    # Validate required params
    for p in op.get("params", []):
        if p.get("required") and not req.params.get(p["id"]):
            raise HTTPException(status_code=400, detail=f"Zorunlu parametre eksik: {p['label']}")

    creds = _get_ssh_creds(server, db)
    if not creds["host"]:
        raise HTTPException(status_code=400, detail="Sunucunun IP adresi veya hostname'i yok")
    if not creds["username"]:
        raise HTTPException(status_code=400, detail="SSH kimlik bilgisi bulunamadı (server veya global credential ayarlayın)")

    try:
        commands = _build_commands(req.operation_id, req.params)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    logger.info("Level1 op=%s server=%s(%s)", req.operation_id, server.name, creds["host"])
    result = _run_ssh(creds, commands)

    return {
        "server": server.name,
        "operation": op["name"],
        "commands_run": len(commands),
        **result,
    }


@router.get("/servers")
def list_eligible_servers(db: Session = Depends(get_db)):
    """List Linux servers available for Level 1 operations."""
    servers = db.query(Server).filter(
        Server.os_type.notin_(["windows"]) if hasattr(Server, "os_type") else True
    ).all()
    result = []
    for s in servers:
        cfg = s.connection_config or {}
        has_creds = bool(cfg.get("username") or cfg.get("password") or cfg.get("private_key"))
        result.append({
            "id": s.id,
            "name": s.name,
            "hostname": s.hostname,
            "ip_address": s.ip_address,
            "os_type": s.os_type,
            "has_creds": has_creds,
        })
    return {"servers": result}
