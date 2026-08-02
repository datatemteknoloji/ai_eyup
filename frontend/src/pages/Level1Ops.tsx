/**
 * İşletim Level 1 — Runbook Sistemi
 * Her operasyon adım adım checklist. Parametreleri doldur → komutlar otomatik güncellenir
 * → adım adım uygula → tik at → tamamla.
 */
import { useState, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  HardDrive, Database, Layers, Settings, Users, Network, FileText, Wrench,
  Copy, Check, ChevronRight, ChevronDown, RotateCcw,
  ClipboardCheck, BookOpen, AlertTriangle, CheckCircle2, Circle,
} from 'lucide-react'

// ── Types ─────────────────────────────────────────────────────────────────────

interface RunbookParam {
  id: string
  label: string
  placeholder: string
  required?: boolean
  hint?: string
  options?: string[]
  default?: string
}

interface RunbookStep {
  title: string
  description?: string
  command?: string       // Komut şablonu — {param_id} ile değiştirilir
  commands?: string[]    // Birden fazla komut
  note?: string          // Dikkat uyarısı
  expectedOutput?: string
  optional?: boolean
}

interface Runbook {
  id: string
  name: string
  category: string
  description: string
  estimatedTime: string  // "~5 dk"
  difficulty: 'kolay' | 'orta' | 'ileri'
  params: RunbookParam[]
  steps: RunbookStep[]
}

// ── Runbook Kataloğu ──────────────────────────────────────────────────────────

const RUNBOOKS: Runbook[] = [

  // ── DISK ──────────────────────────────────────────────────────────────────

  {
    id: 'disk_add_linux',
    name: 'Linux\'e Yeni Disk Ekleme',
    category: 'disk',
    description: 'Fiziksel veya sanal disk eklendikten sonra OS tarafında tanıtma, bölümleme, formatlama ve mount işlemleri.',
    estimatedTime: '~15 dk',
    difficulty: 'orta',
    params: [
      { id: 'disk', label: 'Disk Cihazı', placeholder: '/dev/sdb', required: true,
        hint: 'Yeni eklenen disk. lsblk ile doğrulayın.' },
      { id: 'mount_point', label: 'Mount Dizini', placeholder: '/data', required: true,
        hint: 'Örn: /data, /oracle, /backup' },
      { id: 'fs_type', label: 'Dosya Sistemi', placeholder: 'xfs',
        options: ['xfs', 'ext4', 'ext3'], required: true, default: 'xfs' },
    ],
    steps: [
      {
        title: 'Önce mevcut disk listesini not alın',
        description: 'İşlem öncesi disk durumunu kaydedin; yeni diski karşılaştırarak bulacaksınız.',
        command: 'lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT',
      },
      {
        title: 'SCSI bus\'ı yeniden tara (sanal/SAN disk için)',
        description: 'Yeni eklenen disk OS tarafında henüz görünmüyorsa SCSI rescan yapın.',
        commands: [
          'for host in /sys/class/scsi_host/host*/scan; do echo "- - -" | sudo tee $host; done',
          'sleep 2 && lsblk | grep disk',
        ],
        note: 'Fiziksel sunucularda genellikle gerekmez. Sanal makine veya SAN disk için önemlidir.',
      },
      {
        title: 'Yeni diskin göründüğünü doğrulayın',
        description: 'Yukarıdaki çıktıda {disk} görünmeli, FSTYPE kolonu boş olmalıdır.',
        command: 'lsblk {disk} && sudo fdisk -l {disk}',
      },
      {
        title: 'Partition tablosu oluşturun (GPT)',
        description: 'Disk üzerinde GPT partition tablosu oluşturun.',
        command: 'sudo parted {disk} --script mklabel gpt',
        note: 'Bu adım diskteki mevcut veriyi siler. Doğru disk olduğundan emin olun.',
      },
      {
        title: 'Partition oluşturun',
        description: 'Diskin tamamını kapsayan tek bir partition oluşturun.',
        command: 'sudo parted {disk} --script mkpart primary 0% 100%',
      },
      {
        title: 'Kernel\'e partition tablosunu yeniletin',
        command: 'sudo partprobe {disk} && lsblk {disk}',
        description: 'Yeni partition (genellikle {disk}1) görünmeli.',
      },
      {
        title: 'Dosya sistemi oluşturun',
        description: '{fs_type} dosya sistemi oluşturulur.',
        command: 'sudo mkfs.{fs_type} {disk}1',
        expectedOutput: 'meta-data veya inode bilgisi çıkmalı, hata olmamalı.',
      },
      {
        title: 'Mount dizini oluşturun',
        command: 'sudo mkdir -p {mount_point}',
      },
      {
        title: 'UUID\'yi alın',
        description: 'fstab\'a UUID ile eklemek daha güvenlidir.',
        command: 'sudo blkid {disk}1 | grep -oP \'UUID="\\K[^"]+\'',
        note: 'Çıktıdaki UUID\'yi bir sonraki adım için kopyalayın.',
      },
      {
        title: '/etc/fstab\'a kalıcı mount ekleyin',
        description: 'UUID ile kalıcı mount. <UUID> kısmını bir önceki adımdaki değerle değiştirin.',
        command: 'echo "UUID=<UUID> {mount_point} {fs_type} defaults,nofail 0 0" | sudo tee -a /etc/fstab',
        note: 'fstab hatalı yazılırsa sistem açılmayabilir. Dikkatli olun.',
      },
      {
        title: 'Mount edin ve doğrulayın',
        command: 'sudo mount -a && df -h {mount_point}',
        expectedOutput: '{mount_point} için boyut ve kullanım bilgisi görünmeli.',
      },
      {
        title: 'Ownership ayarlayın (gerekirse)',
        description: 'Uygulama kullanıcısının dizine yazabilmesi için sahipliği ayarlayın.',
        command: 'sudo chown -R <kullanici>:<grup> {mount_point}',
        optional: true,
      },
    ],
  },

  {
    id: 'disk_extend_lvm',
    name: 'LVM Disk Genişletme',
    category: 'disk',
    description: 'Mevcut bir LVM Logical Volume\'ü yeni disk veya ek alan ekleyerek genişletme.',
    estimatedTime: '~10 dk',
    difficulty: 'orta',
    params: [
      { id: 'new_disk', label: 'Yeni Disk/Partition', placeholder: '/dev/sdc', required: true,
        hint: 'VG\'ye eklenecek yeni disk veya partition' },
      { id: 'vg_name', label: 'Volume Group Adı', placeholder: 'vg_data', required: true },
      { id: 'lv_path', label: 'Logical Volume Yolu', placeholder: '/dev/vg_data/lv_app', required: true,
        hint: 'Örn: /dev/mapper/vg_data-lv_app veya /dev/vg_data/lv_app' },
      { id: 'size', label: 'Eklenecek Boyut', placeholder: '+10G', required: true,
        hint: '+10G (mevcut + 10GB) veya 50G (toplam 50GB)' },
      { id: 'fs_type', label: 'Dosya Sistemi', placeholder: 'xfs',
        options: ['xfs', 'ext4'], required: true, default: 'xfs' },
    ],
    steps: [
      {
        title: 'Mevcut LVM yapısını görüntüleyin',
        commands: [
          'sudo pvs',
          'sudo vgs',
          'sudo lvs',
          'df -h',
        ],
      },
      {
        title: 'Yeni diski tarayın',
        command: 'lsblk {new_disk}',
        description: 'Diskin göründüğünü ve mount edilmediğini doğrulayın.',
      },
      {
        title: 'Physical Volume oluşturun',
        command: 'sudo pvcreate {new_disk}',
        expectedOutput: 'Successfully created physical volume',
      },
      {
        title: 'Volume Group\'a PV ekleyin',
        command: 'sudo vgextend {vg_name} {new_disk}',
        expectedOutput: 'Volume group "{vg_name}" successfully extended',
      },
      {
        title: 'VG\'de boş alan oluştuğunu doğrulayın',
        command: 'sudo vgs {vg_name}',
        description: 'VFree kolonunda eklenen disk boyutunun görünmesi gerekir.',
      },
      {
        title: 'Logical Volume\'ü genişletin',
        command: 'sudo lvextend -L {size} {lv_path}',
        expectedOutput: 'Size of logical volume ... changed',
        note: 'xfs için +X kullanın (shrink desteklenmez).',
      },
      {
        title: 'Dosya sistemini genişletin (XFS)',
        command: 'sudo xfs_growfs {lv_path}',
        description: 'XFS için xfs_growfs kullanılır. EXT4 için bir sonraki adıma bakın.',
        note: 'Bu adım SADECE xfs dosya sistemi içindir.',
      },
      {
        title: 'Dosya sistemini genişletin (EXT4)',
        command: 'sudo resize2fs {lv_path}',
        description: 'EXT4 dosya sistemi için resize2fs kullanılır.',
        note: 'Bu adım SADECE ext4 dosya sistemi içindir.',
        optional: true,
      },
      {
        title: 'Genişlemeyi doğrulayın',
        command: 'df -h && sudo lvs {lv_path}',
        expectedOutput: 'Mount noktasında yeni boyut görünmeli.',
      },
    ],
  },

  // ── ASM ───────────────────────────────────────────────────────────────────

  {
    id: 'asm_disk_label',
    name: 'Oracle ASM Disk Etiketleme',
    category: 'asm',
    description: 'Yeni eklenen fiziksel/sanal diski Oracle ASM için etiketleme (oracleasm createdisk).',
    estimatedTime: '~10 dk',
    difficulty: 'orta',
    params: [
      { id: 'disk_device', label: 'Disk Cihazı', placeholder: '/dev/sdc', required: true,
        hint: 'RAW disk olmalı, partition olmamalı. Örn: /dev/sdc' },
      { id: 'asm_name', label: 'ASM Disk Adı', placeholder: 'DATA03', required: true,
        hint: 'Büyük harf, sayı ve alt çizgi. Örn: DATA01, FRA02, REDO01' },
      { id: 'diskgroup', label: 'Disk Group (bilgi)', placeholder: 'DATA', required: false,
        hint: 'Hangi disk group\'a eklenecek (dokümantasyon amaçlı)' },
    ],
    steps: [
      {
        title: 'Mevcut ASM disklerini listeleyin',
        description: 'Mevcut durumu kaydedin.',
        commands: [
          'sudo oracleasm listdisks',
          'sudo oracleasm querydisk -p {disk_device} 2>/dev/null || echo "ASM disk değil"',
        ],
      },
      {
        title: 'Diski rescan edin (SAN/sanal için)',
        description: 'Disk henüz görünmüyorsa SCSI rescan yapın.',
        commands: [
          'for host in /sys/class/scsi_host/host*/scan; do echo "- - -" | sudo tee $host; done',
          'sleep 2 && lsblk | grep disk',
        ],
        optional: true,
      },
      {
        title: 'Diskin görüntüleniyor olduğunu doğrulayın',
        command: 'lsblk {disk_device} && sudo fdisk -l {disk_device}',
        description: 'Disk boyutu doğru ve partition yok (FSTYPE boş) olmalı.',
      },
      {
        title: 'Diskin başka bir yerde kullanılmadığını doğrulayın',
        command: 'sudo blkid {disk_device}',
        description: 'Çıktı boş olmalı — disk dolu veya formatlı olmamalıdır.',
        note: 'Çıktı varsa disk başka bir sistemde kullanılıyor olabilir. Devam etmeden önce doğrulayın.',
      },
      {
        title: 'oracleasm servisinin çalıştığını kontrol edin',
        command: 'sudo systemctl status oracleasm 2>/dev/null || sudo service oracleasm status',
        expectedOutput: 'active (running) veya Checking if ASM is loaded: yes',
      },
      {
        title: 'ASM disk etiketini oluşturun',
        command: 'sudo oracleasm createdisk {asm_name} {disk_device}',
        expectedOutput: 'Writing disk header: done\nInstantiating disk: done',
        note: 'Bu işlem geri alınamaz. Disk adının (ASM_NAME) benzersiz olduğundan emin olun.',
      },
      {
        title: 'Disk etiketini doğrulayın',
        commands: [
          'sudo oracleasm listdisks',
          'sudo oracleasm querydisk -p {asm_name}',
        ],
        expectedOutput: 'Listede {asm_name} görünmeli.',
      },
      {
        title: 'Diğer node\'larda da tara (RAC ortamı)',
        description: 'RAC ortamında tüm node\'larda diski ASM\'ye tanıtın.',
        command: 'sudo oracleasm scandisks',
        note: 'Standalone DB için bu adım gerekmez.',
        optional: true,
      },
      {
        title: 'ASM\'de Disk Group\'a ekleyin (SQL*Plus)',
        description: 'Oracle kullanıcısı ile ASM instance\'a bağlanıp disk group\'u genişletin.',
        commands: [
          'su - oracle',
          'sqlplus / as sysasm',
          "ALTER DISKGROUP {diskgroup} ADD DISK 'ORCL:{asm_name}';",
        ],
        note: 'sqlplus içinde çalıştırın. Disk Group adını (DATA, FRA vb.) doğrulayın.',
        optional: true,
      },
    ],
  },

  {
    id: 'asm_diskgroup_status',
    name: 'ASM Disk Group Durum Kontrolü',
    category: 'asm',
    description: 'Oracle ASM disk group\'larının doluluk ve sağlık durumunu kontrol etme.',
    estimatedTime: '~5 dk',
    difficulty: 'kolay',
    params: [
      { id: 'oracle_user', label: 'Oracle Kullanıcısı', placeholder: 'oracle', required: true, default: 'oracle' },
      { id: 'asm_sid', label: 'ASM SID', placeholder: '+ASM', required: true, default: '+ASM' },
    ],
    steps: [
      {
        title: 'oracleasm disk listesini kontrol edin',
        command: 'sudo oracleasm listdisks',
      },
      {
        title: 'ASM instance\'ının çalıştığını doğrulayın',
        command: "ps -ef | grep [p]mon | grep ASM",
        expectedOutput: 'asm_pmon_{asm_sid} süreci görünmeli.',
      },
      {
        title: 'ASMCMD ile disk group listesini alın',
        command: 'su - {oracle_user} -c "ORACLE_SID={asm_sid} asmcmd lsdg"',
        expectedOutput: 'MOUNTED durumdaki disk group\'lar ve kullanım yüzdeleri görünmeli.',
      },
      {
        title: 'Detaylı disk group bilgisi (SQL*Plus)',
        commands: [
          'su - {oracle_user}',
          'sqlplus / as sysasm',
          "SELECT name, state, type, total_mb, free_mb, ROUND((1-free_mb/total_mb)*100,1) \"USED%\" FROM v$asm_diskgroup ORDER BY name;",
        ],
        description: 'USED% 85\'i geçiyorsa kapasite planlaması yapılmalıdır.',
      },
    ],
  },

  // ── SERVİS ────────────────────────────────────────────────────────────────

  {
    id: 'service_restart_safe',
    name: 'Servis Güvenli Yeniden Başlatma',
    category: 'service',
    description: 'Bir servisi durumu doğrulayarak güvenli şekilde yeniden başlatma.',
    estimatedTime: '~5 dk',
    difficulty: 'kolay',
    params: [
      { id: 'service_name', label: 'Servis Adı', placeholder: 'nginx', required: true,
        hint: 'Örn: nginx, httpd, mysql, tomcat, oracle' },
    ],
    steps: [
      {
        title: 'Servis mevcut durumunu kaydedin',
        command: 'systemctl status {service_name} --no-pager -l',
      },
      {
        title: 'Servisin son log\'larını kontrol edin',
        command: 'journalctl -u {service_name} -n 50 --no-pager',
      },
      {
        title: 'Servisi yeniden başlatın',
        command: 'sudo systemctl restart {service_name}',
      },
      {
        title: 'Servis başladı mı doğrulayın',
        command: 'systemctl status {service_name} --no-pager',
        expectedOutput: 'active (running) görünmeli.',
      },
      {
        title: 'Hata kontrolü',
        command: 'journalctl -u {service_name} -n 20 --no-pager',
        description: 'Yeni hata mesajı olmamalı.',
      },
    ],
  },

  // ── KULLANICI ─────────────────────────────────────────────────────────────

  {
    id: 'user_create_linux',
    name: 'Linux Kullanıcı Oluşturma',
    category: 'user',
    description: 'Yeni sistem kullanıcısı oluşturma, ev dizini hazırlama ve gerekirse sudo yetkisi verme.',
    estimatedTime: '~5 dk',
    difficulty: 'kolay',
    params: [
      { id: 'username', label: 'Kullanıcı Adı', placeholder: 'jdoe', required: true },
      { id: 'full_name', label: 'Tam Ad', placeholder: 'John Doe', required: false },
      { id: 'shell', label: 'Shell', placeholder: '/bin/bash',
        options: ['/bin/bash', '/bin/sh', '/sbin/nologin'], required: true, default: '/bin/bash' },
    ],
    steps: [
      {
        title: 'Kullanıcının zaten var olup olmadığını kontrol edin',
        command: 'id {username} 2>&1',
        description: '"no such user" çıktısı devam edilebileceğini gösterir.',
      },
      {
        title: 'Kullanıcıyı oluşturun',
        command: 'sudo useradd -m -s {shell} -c "{full_name}" {username}',
        expectedOutput: 'Çıktı yok = başarılı.',
      },
      {
        title: 'Geçici şifre belirleyin',
        command: 'sudo passwd {username}',
        note: 'Güçlü geçici şifre kullanın. Kullanıcıdan ilk girişte değiştirmesini isteyin.',
      },
      {
        title: 'Şifre değiştirme zorunluluğu ekleyin (opsiyonel)',
        command: 'sudo chage -d 0 {username}',
        optional: true,
        description: 'Kullanıcı ilk girişte şifresini değiştirmek zorunda kalır.',
      },
      {
        title: 'Kullanıcıyı doğrulayın',
        command: 'id {username} && ls -la /home/{username}/',
      },
    ],
  },

  // ── AĞ ────────────────────────────────────────────────────────────────────

  {
    id: 'ip_change',
    name: 'IP Adresi Değiştirme',
    category: 'network',
    description: 'RHEL/OEL/Ubuntu sunucusunda ağ arayüzü IP adresini değiştirme.',
    estimatedTime: '~10 dk',
    difficulty: 'ileri',
    params: [
      { id: 'interface', label: 'Ağ Arayüzü', placeholder: 'ens192', required: true,
        hint: 'ip addr ile öğrenin. Örn: ens192, eth0, bond0' },
      { id: 'new_ip', label: 'Yeni IP/Prefix', placeholder: '10.0.1.50/24', required: true,
        hint: 'CIDR formatında. Örn: 10.0.1.50/24' },
      { id: 'gateway', label: 'Gateway', placeholder: '10.0.1.1', required: true },
      { id: 'dns', label: 'DNS Sunucu', placeholder: '8.8.8.8', required: false },
    ],
    steps: [
      {
        title: 'Mevcut ağ konfigürasyonunu kaydedin',
        commands: [
          'ip addr show {interface}',
          'ip route show',
          'cat /etc/resolv.conf',
        ],
        note: 'Mevcut konfigürasyonu not alın! Yanlış IP girerseniz sunucuya erişiminizi kaybedebilirsiniz.',
      },
      {
        title: 'Network Manager ile mi yoksa dosya ile mi yönetiliyor kontrol edin',
        command: 'nmcli -t -f NAME,DEVICE,STATE con show 2>/dev/null || echo "NetworkManager yok"',
      },
      {
        title: 'NetworkManager — connection dosyasını bulun',
        command: 'nmcli con show | grep {interface}',
        description: 'Bağlantı adını not alın.',
      },
      {
        title: 'NetworkManager — yeni IP\'yi ayarlayın',
        commands: [
          'sudo nmcli con mod "{interface}" ipv4.addresses {new_ip}',
          'sudo nmcli con mod "{interface}" ipv4.gateway {gateway}',
          'sudo nmcli con mod "{interface}" ipv4.method manual',
        ],
        note: 'Bu adımlar NetworkManager kullanan sistemler içindir (RHEL 7/8/9, OEL).',
      },
      {
        title: 'NetworkManager — bağlantıyı yeniden başlatın',
        command: 'sudo nmcli con down "{interface}" && sudo nmcli con up "{interface}"',
        note: 'Bu adımdan sonra SSH bağlantınız kesilebilir. Yeni IP ile bağlanın.',
      },
      {
        title: 'Bağlantıyı doğrulayın (yeni IP üzerinden)',
        commands: [
          'ip addr show {interface}',
          'ping -c 3 {gateway}',
        ],
      },
    ],
  },

  // ── NTP ──────────────────────────────────────────────────────────────────

  {
    id: 'ntp_sync',
    name: 'NTP Senkronizasyon Kontrolü',
    category: 'network',
    description: 'Sunucunun saat senkronizasyonunu kontrol etme ve gerekirse düzeltme.',
    estimatedTime: '~5 dk',
    difficulty: 'kolay',
    params: [
      { id: 'ntp_server', label: 'NTP Sunucu (opsiyonel)', placeholder: '10.0.0.1',
        required: false, hint: 'Kurumsal NTP sunucu adresi' },
    ],
    steps: [
      {
        title: 'Mevcut zaman senkronizasyonu durumunu kontrol edin',
        commands: [
          'timedatectl status',
          'chronyc tracking 2>/dev/null || ntpq -p 2>/dev/null || echo "chronyd/ntpd bulunamadı"',
        ],
      },
      {
        title: 'Sistem saatini görüntüleyin',
        command: 'date && hwclock --show 2>/dev/null || true',
      },
      {
        title: 'chronyd servisini yeniden başlatın',
        command: 'sudo systemctl restart chronyd 2>/dev/null || sudo systemctl restart ntpd',
        optional: true,
      },
      {
        title: 'Senkronizasyonu zorla',
        command: 'sudo chronyc makestep 2>/dev/null || sudo ntpdate -u {ntp_server} 2>/dev/null || true',
        optional: true,
        description: 'Büyük zaman farkı varsa manuel senkronizasyon gerekebilir.',
      },
      {
        title: 'Senkronizasyonu doğrulayın',
        command: 'timedatectl status && chronyc tracking 2>/dev/null || ntpq -p 2>/dev/null',
        expectedOutput: 'System clock synchronized: yes veya küçük offset değeri görünmeli.',
      },
    ],
  },

  // ── LOG ───────────────────────────────────────────────────────────────────

  {
    id: 'disk_usage_investigate',
    name: 'Disk Doluluk Analizi',
    category: 'log',
    description: 'Disk doluluk sorununu kaynağına kadar araştırma ve gereksiz dosyaları temizleme.',
    estimatedTime: '~10 dk',
    difficulty: 'kolay',
    params: [
      { id: 'mount_point', label: 'İncelenecek Dizin', placeholder: '/', required: true, default: '/' },
    ],
    steps: [
      {
        title: 'Genel disk kullanımını görüntüleyin',
        command: 'df -h',
      },
      {
        title: 'En çok yer kaplayan dizinleri bulun',
        command: 'sudo du -h --max-depth=2 {mount_point} 2>/dev/null | sort -rh | head -20',
      },
      {
        title: 'Log dosyalarını kontrol edin',
        commands: [
          'sudo du -h /var/log/ | sort -rh | head -15',
          'ls -lah /var/log/*.gz 2>/dev/null | head -10',
        ],
        optional: true,
      },
      {
        title: 'Silinen ama açık dosyaları bulun (lsof)',
        command: 'sudo lsof +L1 2>/dev/null | grep -v "^COMMAND" | awk \'{print $1, $7, $NF}\'',
        description: 'Silinen ama süreç tarafından hâlâ açık tutulan büyük dosyalar disk alanını boşaltmaz.',
        note: 'Bu dosyaları boşaltmak için ilgili süreci yeniden başlatın.',
      },
      {
        title: 'Eski logları temizleyin (journald)',
        command: 'sudo journalctl --vacuum-size=500M',
        optional: true,
      },
    ],
  },
]

// ── Category config ───────────────────────────────────────────────────────────

const CATEGORIES = [
  { id: 'disk',    name: 'Disk & Depolama',   icon: <HardDrive size={18} />, color: 'blue' },
  { id: 'asm',     name: 'Oracle ASM',         icon: <Database size={18} />,  color: 'orange' },
  { id: 'lvm',     name: 'LVM Yönetimi',       icon: <Layers size={18} />,    color: 'purple' },
  { id: 'service', name: 'Servis Yönetimi',    icon: <Settings size={18} />,  color: 'green' },
  { id: 'user',    name: 'Kullanıcı & Erişim', icon: <Users size={18} />,     color: 'teal' },
  { id: 'network', name: 'Ağ & Sistem',        icon: <Network size={18} />,   color: 'indigo' },
  { id: 'log',     name: 'Analiz & Temizlik',  icon: <FileText size={18} />,  color: 'slate' },
]

function catBadge(color: string) {
  const m: Record<string, string> = {
    blue:   'bg-blue-900/30 text-blue-300 border-blue-700',
    orange: 'bg-orange-900/30 text-orange-300 border-orange-700',
    purple: 'bg-sky-900/30 text-sky-300 border-sky-700',
    green:  'bg-green-900/30 text-green-300 border-green-700',
    teal:   'bg-teal-900/30 text-teal-300 border-teal-700',
    indigo: 'bg-indigo-900/30 text-indigo-300 border-indigo-700',
    slate:  'bg-slate-800/60 text-slate-300 border-slate-600',
  }
  return m[color] ?? m.slate
}

function difficultyBadge(d: Runbook['difficulty']) {
  if (d === 'kolay')  return 'bg-green-900/30 text-green-300 border border-green-700/50'
  if (d === 'orta')   return 'bg-amber-900/30 text-amber-300 border border-amber-700/50'
  return 'bg-red-900/30 text-red-300 border border-red-700/50'
}

// ── Param substitution ────────────────────────────────────────────────────────

function applyParams(text: string, params: Record<string, string>): string {
  return text.replace(/\{(\w+)\}/g, (_, k) => params[k] || `{${k}}`)
}

// ── Copy button ───────────────────────────────────────────────────────────────

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  const copy = () => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }
  return (
    <button onClick={copy}
      className="flex-none flex items-center gap-1 text-xs text-slate-400 hover:text-white px-2 py-1 rounded hover:bg-slate-700 transition-colors"
      title="Kopyala"
    >
      {copied ? <><Check size={12} className="text-green-400" /> Kopyalandı</> : <><Copy size={12} /> Kopyala</>}
    </button>
  )
}

// ── Main Component ────────────────────────────────────────────────────────────

export default function Level1Ops() {
  const { category: urlCat } = useParams<{ category?: string }>()
  const navigate = useNavigate()

  const [selectedCat, setSelectedCat] = useState(urlCat ?? 'disk')
  const [selectedRunbook, setSelectedRunbook] = useState<Runbook | null>(null)
  const [paramValues, setParamValues] = useState<Record<string, string>>({})
  const [checkedSteps, setCheckedSteps] = useState<Record<number, boolean>>({})
  const [expandedSteps, setExpandedSteps] = useState<Record<number, boolean>>({})

  // Filtered runbooks for current category
  const runbooks = useMemo(
    () => RUNBOOKS.filter(r => r.category === selectedCat),
    [selectedCat]
  )

  const catInfo = CATEGORIES.find(c => c.id === selectedCat)

  const selectCat = (id: string) => {
    setSelectedCat(id)
    setSelectedRunbook(null)
    setCheckedSteps({})
    setParamValues({})
    navigate(`/level1/${id}`, { replace: true })
  }

  const selectRunbook = (rb: Runbook) => {
    setSelectedRunbook(rb)
    setCheckedSteps({})
    setExpandedSteps({})
    // Pre-fill defaults
    const defaults: Record<string, string> = {}
    rb.params.forEach(p => { if (p.default) defaults[p.id] = p.default })
    setParamValues(defaults)
  }

  const toggleStep = (idx: number) =>
    setCheckedSteps(prev => ({ ...prev, [idx]: !prev[idx] }))

  const toggleExpand = (idx: number) =>
    setExpandedSteps(prev => ({ ...prev, [idx]: !prev[idx] }))

  const completedCount = selectedRunbook
    ? selectedRunbook.steps.filter((_, i) => checkedSteps[i]).length
    : 0
  const totalRequired = selectedRunbook
    ? selectedRunbook.steps.filter(s => !s.optional).length
    : 0
  const progress = totalRequired > 0 ? (completedCount / selectedRunbook!.steps.length) * 100 : 0

  const resetRunbook = () => {
    setCheckedSteps({})
    setExpandedSteps({})
  }

  return (
    <div className="flex h-full min-h-0 bg-slate-950">

      {/* ── Left: Categories ─────────────────────────────────────────────── */}
      <div className="w-56 flex-none border-r border-slate-800/60 flex flex-col py-4 px-3 gap-1 overflow-y-auto">
        <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider px-2 mb-2">
          Kategoriler
        </div>
        {CATEGORIES.map(cat => (
          <button
            key={cat.id}
            onClick={() => selectCat(cat.id)}
            className={`flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-sm font-medium transition-all
              ${selectedCat === cat.id
                ? `${catBadge(cat.color)} border`
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60 border border-transparent'}`}
          >
            {cat.icon}
            <span>{cat.name}</span>
            <span className="ml-auto text-xs text-slate-600">
              {RUNBOOKS.filter(r => r.category === cat.id).length}
            </span>
          </button>
        ))}
      </div>

      {/* ── Middle: Runbook list ──────────────────────────────────────────── */}
      <div className="w-64 flex-none border-r border-slate-800/60 flex flex-col overflow-hidden">
        <div className="flex-none px-4 py-4 border-b border-slate-800/60">
          <div className="flex items-center gap-2 text-white font-semibold text-sm">
            {catInfo?.icon}
            {catInfo?.name}
          </div>
          <div className="text-xs text-slate-500 mt-0.5">{runbooks.length} prosedür</div>
        </div>
        <div className="flex-1 overflow-y-auto px-3 py-3 space-y-2">
          {runbooks.length === 0 && (
            <div className="text-slate-500 text-sm text-center py-10">
              Bu kategoride henüz runbook yok.
            </div>
          )}
          {runbooks.map(rb => (
            <button
              key={rb.id}
              onClick={() => selectRunbook(rb)}
              className={`w-full text-left rounded-xl p-3 border transition-all
                ${selectedRunbook?.id === rb.id
                  ? 'bg-cyan-600/15 border-cyan-600/50'
                  : 'bg-slate-800/30 border-slate-700/50 hover:border-slate-600 hover:bg-slate-800/60'}`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="font-medium text-sm text-white leading-snug">{rb.name}</div>
                <ChevronRight size={14} className={`flex-none mt-0.5 transition-transform ${selectedRunbook?.id === rb.id ? 'rotate-90 text-cyan-400' : 'text-slate-600'}`} />
              </div>
              <div className="text-xs text-slate-500 mt-1 line-clamp-2">{rb.description}</div>
              <div className="flex items-center gap-2 mt-2">
                <span className={`text-[10px] px-1.5 py-0.5 rounded-full border font-medium ${difficultyBadge(rb.difficulty)}`}>
                  {rb.difficulty}
                </span>
                <span className="text-[10px] text-slate-500">{rb.estimatedTime}</span>
                <span className="text-[10px] text-slate-600">{rb.steps.length} adım</span>
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* ── Right: Runbook detail ─────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto">
        {!selectedRunbook ? (
          <EmptyState />
        ) : (
          <div className="max-w-3xl mx-auto px-8 py-6 space-y-6">

            {/* Header */}
            <div>
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h2 className="text-xl font-bold text-white flex items-center gap-2">
                    <BookOpen size={20} className="text-cyan-400 flex-none" />
                    {selectedRunbook.name}
                  </h2>
                  <p className="text-sm text-slate-400 mt-1">{selectedRunbook.description}</p>
                  <div className="flex items-center gap-3 mt-2">
                    <span className={`text-xs px-2 py-0.5 rounded-full border font-medium ${difficultyBadge(selectedRunbook.difficulty)}`}>
                      {selectedRunbook.difficulty}
                    </span>
                    <span className="text-xs text-slate-500">{selectedRunbook.estimatedTime}</span>
                  </div>
                </div>
                <button onClick={resetRunbook}
                  className="flex-none flex items-center gap-1.5 text-xs text-slate-400 hover:text-white px-3 py-2 rounded-lg hover:bg-slate-800 transition-colors border border-slate-700"
                >
                  <RotateCcw size={13} /> Sıfırla
                </button>
              </div>

              {/* Progress bar */}
              {selectedRunbook.steps.length > 0 && (
                <div className="mt-4">
                  <div className="flex items-center justify-between text-xs text-slate-500 mb-1.5">
                    <span>{completedCount} / {selectedRunbook.steps.length} adım tamamlandı</span>
                    {completedCount === selectedRunbook.steps.length && (
                      <span className="text-green-400 font-medium flex items-center gap-1">
                        <CheckCircle2 size={13} /> Tamamlandı!
                      </span>
                    )}
                  </div>
                  <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-cyan-500 rounded-full transition-all duration-300"
                      style={{ width: `${progress}%` }}
                    />
                  </div>
                </div>
              )}
            </div>

            {/* Params */}
            {selectedRunbook.params.length > 0 && (
              <div className="bg-slate-900/60 border border-slate-700/60 rounded-2xl p-5">
                <h3 className="text-sm font-semibold text-slate-300 flex items-center gap-2 mb-4">
                  <Settings size={14} className="text-slate-500" />
                  Parametreler
                  <span className="text-xs text-slate-500 font-normal">— komutlara otomatik eklenir</span>
                </h3>
                <div className="grid grid-cols-2 gap-4">
                  {selectedRunbook.params.map(p => (
                    <div key={p.id} className={p.id === 'full_name' || p.id === 'disk' ? 'col-span-2' : ''}>
                      <label className="text-xs font-medium text-slate-400 mb-1.5 block">
                        {p.label}
                        {p.required && <span className="text-red-400 ml-1">*</span>}
                      </label>
                      {p.options ? (
                        <select
                          value={paramValues[p.id] ?? p.default ?? ''}
                          onChange={e => setParamValues(v => ({ ...v, [p.id]: e.target.value }))}
                          className="w-full bg-slate-800 border border-slate-600 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-cyan-500/50"
                        >
                          {p.options.map(o => <option key={o} value={o}>{o}</option>)}
                        </select>
                      ) : (
                        <input
                          type="text"
                          placeholder={p.placeholder}
                          value={paramValues[p.id] ?? ''}
                          onChange={e => setParamValues(v => ({ ...v, [p.id]: e.target.value }))}
                          className="w-full bg-slate-800 border border-slate-600 text-white text-sm rounded-lg px-3 py-2 font-mono placeholder-slate-600 focus:outline-none focus:ring-2 focus:ring-cyan-500/50"
                        />
                      )}
                      {p.hint && <p className="text-xs text-slate-600 mt-1">{p.hint}</p>}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Steps */}
            <div className="space-y-3">
              <h3 className="text-sm font-semibold text-slate-400 flex items-center gap-2">
                <ClipboardCheck size={15} /> Adımlar
              </h3>
              {selectedRunbook.steps.map((step, idx) => {
                const done = !!checkedSteps[idx]
                const expanded = !!expandedSteps[idx]
                const allCmds = step.commands ?? (step.command ? [step.command] : [])
                const resolvedCmds = allCmds.map(c => applyParams(c, paramValues))

                return (
                  <div
                    key={idx}
                    className={`rounded-2xl border transition-all ${
                      done
                        ? 'bg-green-900/10 border-green-800/40'
                        : 'bg-slate-900/50 border-slate-700/50'
                    }`}
                  >
                    {/* Step header */}
                    <div className="flex items-start gap-3 p-4">
                      {/* Checkbox */}
                      <button
                        onClick={() => toggleStep(idx)}
                        className={`flex-none w-6 h-6 rounded-full border-2 flex items-center justify-center mt-0.5 transition-all ${
                          done
                            ? 'bg-green-500 border-green-500 text-white'
                            : 'border-slate-600 hover:border-cyan-500'
                        }`}
                      >
                        {done ? <Check size={13} strokeWidth={3} /> : <span className="text-xs text-slate-500">{idx + 1}</span>}
                      </button>

                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className={`text-sm font-medium ${done ? 'line-through text-slate-500' : 'text-white'}`}>
                            {step.title}
                          </span>
                          {step.optional && (
                            <span className="text-[10px] text-slate-500 border border-slate-700 px-1.5 py-0.5 rounded-full">opsiyonel</span>
                          )}
                        </div>

                        {step.description && (
                          <p className="text-xs text-slate-500 mt-0.5">{step.description}</p>
                        )}

                        {/* Commands */}
                        {resolvedCmds.length > 0 && (
                          <div className="mt-3 space-y-2">
                            {resolvedCmds.map((cmd, ci) => (
                              <div key={ci} className="flex items-start gap-2 bg-slate-950 border border-slate-800 rounded-xl overflow-hidden">
                                <div className="flex-1 px-3 py-2 font-mono text-xs text-green-300 overflow-x-auto">
                                  <span className="text-slate-600 select-none mr-2">$</span>
                                  {cmd}
                                </div>
                                <div className="flex-none px-2 py-2">
                                  <CopyButton text={cmd} />
                                </div>
                              </div>
                            ))}
                          </div>
                        )}

                        {/* Note warning */}
                        {step.note && (
                          <div className="mt-3 flex items-start gap-2 bg-amber-900/15 border border-amber-700/30 rounded-xl px-3 py-2.5">
                            <AlertTriangle size={13} className="flex-none text-amber-400 mt-0.5" />
                            <span className="text-xs text-amber-300">{step.note}</span>
                          </div>
                        )}

                        {/* Expected output (collapsible) */}
                        {step.expectedOutput && (
                          <button
                            onClick={() => toggleExpand(idx)}
                            className="mt-2 flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-300 transition-colors"
                          >
                            {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                            Beklenen çıktı
                          </button>
                        )}
                        {step.expectedOutput && expanded && (
                          <div className="mt-1.5 bg-slate-800/60 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-400 font-mono">
                            {step.expectedOutput}
                          </div>
                        )}
                      </div>

                      {/* Expand indicator for steps with content */}
                    </div>
                  </div>
                )
              })}
            </div>

            {/* Completion banner */}
            {completedCount === selectedRunbook.steps.length && selectedRunbook.steps.length > 0 && (
              <div className="flex items-center gap-3 bg-green-900/20 border border-green-700/40 rounded-2xl p-5">
                <CheckCircle2 size={24} className="text-green-400 flex-none" />
                <div>
                  <div className="text-green-300 font-semibold">Runbook tamamlandı!</div>
                  <div className="text-green-500 text-sm mt-0.5">Tüm adımlar başarıyla tamamlandı.</div>
                </div>
              </div>
            )}

          </div>
        )}
      </div>
    </div>
  )
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center h-full text-center py-20 px-8">
      <div className="w-16 h-16 rounded-2xl bg-cyan-600/10 border border-cyan-600/20 flex items-center justify-center text-cyan-500 mb-5">
        <Wrench size={28} />
      </div>
      <div className="text-white font-semibold text-lg mb-2">Runbook seçin</div>
      <p className="text-slate-400 text-sm max-w-xs">
        Soldan bir prosedür seçin. Parametreleri doldurun, komutlar otomatik güncellenir.
        Her adımı tamamladıkça işaretleyin.
      </p>
      <div className="mt-8 grid grid-cols-2 gap-3 text-xs text-slate-600">
        {['Disk Ekleme', 'LVM Genişletme', 'ASM Label', 'Servis Restart', 'Kullanıcı Oluşturma', 'IP Değiştirme'].map(t => (
          <div key={t} className="flex items-center gap-1.5">
            <Circle size={8} className="fill-slate-700 stroke-none" /> {t}
          </div>
        ))}
      </div>
    </div>
  )
}
