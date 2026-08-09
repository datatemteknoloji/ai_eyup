# Dropt Ops Portal — Operasyon & Host Merge El Kitabı

**Sürüm:** handbook 1.0 · manifest 1.0 · capabilities 1.2
**Tarih:** 2026-08-06
**Kaynak:** `/dttadvance/app`

> Hedef ortamdaki Cursor: Bu belge + `dropt-host-merge-manifest.json` + `dropt-host-merge.mdc` + `capabilities.json` ile Dropt operasyonlarını eksiksiz göm. Eksik ops/ayar/API varsa tamamla.

---

## 1. Amaç ve birleştirme hedefleri

Embed Dropt operations under a host app menu. Host already has login and (optionally) security. Host has a vCenter-backed server list; double-click should open Dropt ops like ServerConsole today. Dropt-specific settings stay under a Dropt submenu chosen by the integrator.

### Omit (taşıma)

- `standalone_login_page`
- `settings_tab_general`
- `settings_tab_account`
- `dropt_native_servers_crud_ui_if_host_list_used`
- `portal_users_admin_ui_if_host_manages_users`
- `dashboard_optional`

### Dropt submenu altında tut

- `all_ops_wizards`
- `server_console_embedded_ops`
- `jobs`
- `job_detail`
- `audit`
- `settings_automation`
- `settings_mail`
- `settings_assistant`
- `settings_repos`
- `settings_centrify`
- `settings_backup`

### Host’ta yoksa üst Ayarlar’a taşı

- `security_sessions`
- `security_mfa`

### Host’ta varsa güvenlikten çıkar

- `security_auth_ad_sso`
- `security_tls`
- `security_policy_password`

### Host karşılığı ile değiştir

- `server_inventory_list_ui`
- `login_auth_ui`

## 2. Mimari

Dropt backend remains a FastAPI service (or sub-app). Host UI embeds Dropt React ops surfaces. Auth is bridged from host session to Dropt API token.

### Katmanlar

- **host_shell**: `login`, `main_nav`, `vcenter_server_list`, `top_level_settings`
- **dropt_ops_surface**: `ops_wizards`, `server_console`, `jobs`, `audit`, `dropt_settings_panels`
- **dropt_backend**: `ssh_jobs`, `target_server_records`, `centrify`, `hpsa_hooks`, `assistant_catalog`, `secrets`

### Kritik entegrasyon noktaları

#### `auth_bridge`

Dropt FE uses localStorage key dtt_access_token via frontend/src/session.ts. Host must set a valid Dropt JWT (or change FE to accept host Authorization header / cookie bridge). All /api/* calls require Bearer token.

#### `server_identity_mapping`

Ops APIs require Dropt TargetServer.id. Host vCenter rows must map to Dropt server records (upsert by IP/hostname/UUID). Double-click must resolve to dropt_server_id before opening console/ops.

#### `embedded_ops_pattern`

Preferred UX: host server double-click → ServerConsolePage (or equivalent) with OpsWizardContext { embedded:true, serverId, onAfterPreview }. Wizards use useAfterPreview() — embedded stays on console; standalone navigates to /app/jobs/:id.

#### `talep_id`

Most write ops require Talep ID + Preview → Apply job flow. Do not auto-apply.

### Tech stack (kaynak)

- Frontend: React + Vite + TypeScript + react-router-dom + Tailwind-like CSS vars — `frontend/`
- Backend: FastAPI + SQLModel + PostgreSQL + Redis + SSH — `backend/`
- Deploy: docker compose (api, frontend, db, redis)

## 3. Auth & oturum

- Login route: `/` → **omit**
- Token: `localStorage.dtt_access_token`
- Session dosyası: `frontend/src/session.ts`
- Host merge: login=`omit`, gate=`replace_with_host_gate_or_token_bridge`

If host SSO already authenticates users, implement token exchange endpoint or shared JWT validation so Dropt API accepts host identity with mapped role (admin/operator).

## 4. Navigasyon (kaynak → host)

| Path | Label key | Host merge |
|------|-----------|------------|
| `/app` | `nav_dashboard` | `omit_or_optional` |
| `/app/servers` | `nav_servers` | `replace_with_host_vcenter_list` |
| `/app/jobs` | `nav_jobs` | `keep_under_dropt_submenu` |
| `/app/audit` | `nav_audit` | `keep_under_dropt_submenu` |
| `/app/users` | `nav_portal_users` | `omit_if_host_manages_users` |
| `/app/system` | `nav_system` | `omit_or_dropt_admin_only` |
| `/app/settings` | `nav_settings` | `split_panels_see_settings` |

## 5. Sayfalar

### login

- **Route:** `/`
- **Component:** `frontend/src/pages/LoginPage.tsx`
- **Kind:** `shell`
- **Host merge:** `omit`
- **Not:** Host has login.

### dashboard

- **Route:** `/app`
- **Component:** `frontend/src/pages/DashboardPage.tsx`
- **Kind:** `shell`
- **Host merge:** `omit_or_optional`

### servers_list

- **Route:** `/app/servers`
- **Component:** `frontend/src/pages/ServersPage.tsx`
- **Kind:** `inventory`
- **Host merge:** `replace_with_host_vcenter_list`
- **API:** `/api/servers`
- **Not:** Reuse double-click → console pattern on host list. Ensure each host row maps to dropt TargetServer.id.
- **Detaylar:**
  - `double_click_row`: navigate(/app/servers/:id) → ServerConsolePage
  - `ops_context_menu`: ServerOpsMenu + buildOpsUrl(path, {ids, hostnames})
  - `admin_crud`: create/edit/delete/import/test connection — not needed if host owns inventory

### server_console

- **Route:** `/app/servers/:id`
- **Component:** `frontend/src/pages/ServerConsolePage.tsx`
- **Kind:** `ops_host`
- **Host merge:** `keep_adapt_paths`
- **CRITICAL:** yes
- **Detaylar:**
  - `opens_ops_via`: ServerOpsMenu → setWizardPath
  - `embedded_context`: OpsWizardContext { embedded:true, serverId, serverIds, onAfterPreview, draftJob }
  - `wizard_map_file_section`: WIZARD_BY_PATH + MODULE_TO_WIZARD in ServerConsolePage.tsx
  - `preview_apply`: preview dumps to xterm console; Apply via job WebSocket progress
  - `terminal_op`: special-case path /app/terminal
- **Bağımlılık:** `auth_bridge`, `server_identity_mapping`, `jobs_api`

### jobs

- **Route:** `/app/jobs`
- **Component:** `frontend/src/pages/JobsPage.tsx`
- **Kind:** `ops_admin`
- **Host merge:** `keep_under_dropt_submenu`
- **API:** `/api/jobs`

### job_detail

- **Route:** `/app/jobs/:id`
- **Component:** `frontend/src/pages/JobDetailPage.tsx`
- **Kind:** `ops_admin`
- **Host merge:** `keep_under_dropt_submenu`
- **Detaylar:**
  - `shows`: ['preview_summary', 'apply', 'after_state.checklist / checklist_en by locale', 'artifact download']

### audit

- **Route:** `/app/audit`
- **Component:** `frontend/src/pages/AuditPage.tsx`
- **Kind:** `ops_admin`
- **Host merge:** `keep_under_dropt_submenu`
- **API:** `/api/audit`

### portal_users

- **Route:** `/app/users`
- **Component:** `frontend/src/pages/PortalUsersPage.tsx`
- **Kind:** `admin`
- **Host merge:** `omit_if_host_manages_users`
- **API:** `/api/portal-users`, `/api/identity`
- **Not:** capabilities id portal_users route is /app/users (not portal-users).

### admin_system

- **Route:** `/app/system`
- **Component:** `frontend/src/pages/AdminSystemPage.tsx`
- **Kind:** `admin`
- **Host merge:** `omit_or_dropt_admin_only`
- **API:** `/api/admin`

### settings

- **Route:** `/app/settings`
- **Component:** `frontend/src/pages/SettingsPage.tsx`
- **Kind:** `settings_host`
- **Host merge:** `split_see_settings_panels`
- **Not:** Do not mount whole page as-is. Mount selected panels under Dropt submenu; relocate MFA/sessions only if host lacks them.

### terminal_page

- **Route:** `/app/terminal`
- **Component:** `frontend/src/pages/TerminalPage.tsx`
- **Kind:** `ops`
- **Host merge:** `keep_prefer_console_entry`
- **API:** `/api/terminal`
- **Not:** WebSocket terminal; escape hatch. Prefer opening from console ops menu.

## 6. Tüm operasyonlar (ServerOpsMenu)

- Kaynak: `frontend/src/components/ServerOpsMenu.tsx`
- Deep link single: `?serverId=<id>`
- Deep link multi: `?serverId=<primary>&serverIds=id1,id2`
- FS mode: `?mode=extend|create|organize`
- Network tab: `?tab=network|vlan|ipchange`
- ASM max nodes: 2

Multi-server’da gizlenenler:
- `ops_terminal`
- `ops_hostname`
- `ops_reboot`
- `ops_services`
- `ops_sudo`
- `ops_filesystem`
- `ops_path_perms`
- `ops_sysctl`
- `ops_network`

### Terminal aç (`ops_terminal`)

| Alan | Değer |
|------|-------|
| Menu key | `ops_terminal` |
| Path | `/app/terminal` |
| Component | `frontend/src/pages/TerminalPage.tsx` |
| Job module | `None` |
| Capability | `terminal` |
| Multi-server | `False` |
| Host merge | `keep` |
| Embedded console | `True` |

**Asistan katalog özeti:**

- Tarayıcıdan SSH benzeri konsol.
- Title EN: Open terminal
- Gerekli girdiler: sunucu
- Checklist:
  - Sunucu seçip terminali açın
- Kapsam dışı: Asistan komut çalıştırmaz; yalnızca yönlendirir.
- Keywords: terminal, ssh, konsol, shell, komut satırı, web terminal

### Yerel kullanıcılar (`ops_local_users`)

| Alan | Değer |
|------|-------|
| Menu key | `ops_local_users` |
| Path | `/app/local-users` |
| Component | `frontend/src/pages/LocalUsersPage.tsx` |
| Job module | `local_user` |
| Capability | `local_users` |
| Multi-server | `True` |
| Host merge | `keep` |
| Embedded console | `True` |

**Ek API:**

- `/api/local-users`

**Asistan katalog özeti:**

- Linux local user/group yönetimi.
- Title EN: Local users
- Gerekli girdiler: sunucu, kullanıcı adı
- Checklist:
  - Sunucu seçin
  - Kullanıcı işlemlerini uygulayın
- Kapsam dışı: AD/LDAP kullanıcı oluşturma Identity ayarlarından ayrıdır.
- Keywords: useradd, local user, kullanıcı ekle, grup, passwd, hesap

### Hostname değiştir (`ops_hostname`)

| Alan | Değer |
|------|-------|
| Menu key | `ops_hostname` |
| Path | `/app/hostname` |
| Component | `frontend/src/pages/HostnamePage.tsx` |
| Job module | `hostname` |
| Capability | `hostname` |
| Multi-server | `False` |
| Host merge | `keep` |
| Embedded console | `True` |
| Backend | `backend/app/modules/hostname.py` |

**Ek API:**

- `/api/hostname`

**Yan etkiler / kurallar:**

- Centrify adleave/adjoin if joined (Settings Centrify creds)
- HPSA bs_software + bs_hardware best-effort
- success checklist + checklist_en (DNS + monitoring mail)
- FQDN domain = text after first dot

**Asistan katalog özeti:**

- FQDN/hostname ve /etc/hosts güncelleme; Centrify leave/join + HPSA best-effort.
- Title EN: Change hostname
- Gerekli girdiler: sunucu, yeni FQDN
- Checklist:
  - Sunucu seçin
  - Yeni FQDN girin (domain = FQDN ilk '.' sonrası)
  - Önizleme → uygula
  - Centrify varsa leave→hostname→join (Settings Centrify creds; hata hostname success bozmaz)
  - HPSA bs_* best-effort
  - Başarı sonrası: DNS talebi + ekiplere mail (CC: Unix Linux Sistem Tasarım ve Planlama)
- Kapsam dışı: DNS kaydı portalda oluşturulmaz; talep/mail metni checklist’te üretilir. Centrify/HPSA hatası hostname job'unu fail etmez.
- Keywords: hostname, fqdn, makine adı, hosts, rename server, centrify, adleave, adjoin

### Yeniden başlat (`ops_reboot`)

| Alan | Değer |
|------|-------|
| Menu key | `ops_reboot` |
| Path | `/app/reboot` |
| Component | `frontend/src/pages/RebootPage.tsx` |
| Job module | `reboot` |
| Capability | `reboot` |
| Multi-server | `False` |
| Host merge | `keep` |
| Embedded console | `True` |

**Asistan katalog özeti:**

- Onaylı sunucu reboot.
- Title EN: Reboot
- Gerekli girdiler: sunucu, hostname onayı
- Checklist:
  - Sunucu seçin
  - Hostname onayını yazın
  - Önizleme → uygula
- Keywords: reboot, restart server, yeniden başlat, shutdown -r

### Servis yönetimi (`ops_services`)

| Alan | Değer |
|------|-------|
| Menu key | `ops_services` |
| Path | `/app/services` |
| Component | `frontend/src/pages/ServicesPage.tsx` |
| Job module | `services` |
| Capability | `services` |
| Multi-server | `False` |
| Host merge | `keep` |
| Embedded console | `True` |

**Ops API:**

- `/api/ops/servers/{id}/services`

**Asistan katalog özeti:**

- systemctl start/stop/enable/disable/restart.
- Title EN: Service control
- Gerekli girdiler: sunucu, unit adı, aksiyon
- Checklist:
  - Sunucu seçin
  - Unit ve aksiyon
  - Önizleme → uygula
- Keywords: systemctl, servis, service, start, stop, enable, restart, daemon

### Sudo yetkisi (`ops_sudo`)

| Alan | Değer |
|------|-------|
| Menu key | `ops_sudo` |
| Path | `/app/sudoers` |
| Component | `frontend/src/pages/SudoersPage.tsx` |
| Job module | `sudoers` |
| Capability | `sudoers` |
| Multi-server | `False` |
| Host merge | `keep` |
| Embedded console | `True` |

**Ops API:**

- `/api/ops/sudo-templates`
- `/api/ops/servers/{id}/sudo-rules`
- `/api/ops/sudo-lookup`
- `/api/ops/servers/{id}/sudo-which`

**Asistan katalog özeti:**

- Kullanıcı/gruba sudoers kuralı.
- Title EN: Sudo access
- Gerekli girdiler: sunucu, kullanıcı veya grup, kural şablonu
- Checklist:
  - Sunucu seçin
  - Hedef kullanıcı/grup ve şablon
  - Önizleme → uygula
- Keywords: sudo, sudoers, yetki, nopasswd, wheel, root yetkisi

### FileSystem Management (`ops_filesystem`)

| Alan | Değer |
|------|-------|
| Menu key | `ops_filesystem` |
| Path | `/app/filesystem` |
| Component | `frontend/src/pages/FilesystemPage.tsx` |
| Job module | `filesystem` |
| Capability | `filesystem` |
| Multi-server | `False` |
| Host merge | `keep` |
| Embedded console | `True` |

**Ops API:**

- `/api/ops/servers/{id}/filesystems`
- `/api/ops/servers/{id}/volume-groups`
- `/api/ops/servers/{id}/filesystem-inventory`

**Alt menü:**

- `fs_extend` → `/app/filesystem?mode=extend` (capability `filesystem_extend`, action `extend`)
- `fs_create` → `/app/filesystem?mode=create` (capability `filesystem_create`, action `create`)
- `fs_organize` → `/app/filesystem?mode=organize` (capability `filesystem_organize`, action `organize`)

**Embedded:** Uses embeddedGate when OpsWizardContext.embedded; URL mode ignored in console.

**Asistan katalog özeti:**

- FS menüsü: Extend, Create FS veya Disk organizer.
- Title EN: FileSystem Management
- Gerekli girdiler: sunucu
- Checklist:
  - Sunucu seçin
  - Extend / Create FS / Disk organizer seçin
- Kapsam dışı: Oracle ASM alanı FileSystem Management ekranından yönetilmez.
- Keywords: filesystem, filesystem management, dosya sistemi, lvm, vg, lv, disk, mount, alan yönetimi

#### Alt ops: Extend (büyüt) (`filesystem_extend`)

- Route: `/app/filesystem?mode=extend`
- Özet: Mevcut filesystem/LV alanını büyütme; gerekirse disk ekleyip vgextend.
  - Sunucuyu seçin
  - Extend seçin
  - FS seçip boyut / disk alanlarını doldurun
  - Önizleme → uygula
- Kapsam dışı: Root VG’de yalnızca izinli mount’lar (/home /var /tmp /var/tmp).

#### Alt ops: Create FS (`filesystem_create`)

- Route: `/app/filesystem?mode=create`
- Özet: Non-root VG üzerinde yeni LV + filesystem oluşturma.
  - Sunucuyu seçin
  - Create FS seçin
  - VG + mount + boyut doldurun
  - Önizleme → uygula
- Kapsam dışı: Root VG üzerinde yeni FS oluşturulmaz.

#### Alt ops: Disk organizer (`filesystem_organize`)

- Route: `/app/filesystem?mode=organize`
- Özet: Mevcut non-root FS alanını birden fazla mount noktasına bölme (destructive).
  - Sunucuyu seçin
  - Disk organizer seçin
  - Kaynak FS ve slice’ları tanımlayın
  - Önizleme → uygula
- Kapsam dışı: Destructive işlem; root VG FS’leri organize edilmez.

### Paket kur (`ops_packages`)

| Alan | Değer |
|------|-------|
| Menu key | `ops_packages` |
| Path | `/app/packages` |
| Component | `frontend/src/pages/PackagesPage.tsx` |
| Job module | `packages` |
| Capability | `packages` |
| Multi-server | `True` |
| Host merge | `keep` |
| Embedded console | `True` |

**Ops API:**

- `/api/ops/servers/{id}/package-context`
- `/api/ops/servers/{id}/dnf-search`
- `/api/ops/servers/{id}/package-versions`

**Asistan katalog özeti:**

- dnf/yum paket veya portal/NFS local RPM.
- Title EN: Install packages
- Gerekli girdiler: sunucu, paket adı veya keyword/RPM
- Checklist:
  - Sunucu seçin
  - Paket/keyword seçin
  - Önizleme → uygula
- Keywords: paket, rpm, dnf, yum, install, package, oracle preinstall, localinstall, repo, docker, kurulum, paket kur

### Path izinleri (`ops_path_perms`)

| Alan | Değer |
|------|-------|
| Menu key | `ops_path_perms` |
| Path | `/app/path-perms` |
| Component | `frontend/src/pages/PathPermsPage.tsx` |
| Job module | `path_perms` |
| Capability | `path_perms` |
| Multi-server | `False` |
| Host merge | `keep` |
| Embedded console | `True` |

**Ops API:**

- `/api/ops/path-whitelist`
- `/api/ops/path-modes`

**Asistan katalog özeti:**

- Dizin/dosya owner ve chmod.
- Title EN: Path permissions
- Gerekli girdiler: sunucu, path, owner/mode
- Checklist:
  - Sunucu ve path
  - Owner/mode
  - Önizleme → uygula
- Keywords: chmod, chown, izin, permission, owner, dizin yetkisi

### Log paketi (`ops_logs`)

| Alan | Değer |
|------|-------|
| Menu key | `ops_logs` |
| Path | `/app/logs` |
| Component | `frontend/src/pages/LogCollectPage.tsx` |
| Job module | `log_collect` |
| Capability | `log_collect` |
| Multi-server | `True` |
| Host merge | `keep` |
| Embedded console | `True` |

**Asistan katalog özeti:**

- Sunucudan log/sos benzeri toplama.
- Title EN: Log package
- Gerekli girdiler: sunucu
- Checklist:
  - Sunucu seçin
  - Toplama işlemini başlatın
- Keywords: log, sosreport, log topla, diagnostic, support log

### Security Limits (`ops_limits`)

| Alan | Değer |
|------|-------|
| Menu key | `ops_limits` |
| Path | `/app/limits` |
| Component | `frontend/src/pages/LimitsPage.tsx` |
| Job module | `limits` |
| Capability | `limits` |
| Multi-server | `True` |
| Host merge | `keep` |
| Embedded console | `True` |

**Ops API:**

- `/api/ops/limits-items`
- `/api/ops/limits-types`
- `/api/ops/servers/{id}/limits`

**Asistan katalog özeti:**

- limits.conf (nproc, nofile vb.).
- Title EN: Security Limits
- Gerekli girdiler: sunucu, domain, limit türü ve değer
- Checklist:
  - Sunucu seçin
  - Limit satırlarını girin
  - Önizleme → uygula
- Keywords: limits, nproc, nofile, ulimit, security limits, limits.conf

### HugePages / sysctl (`ops_sysctl`)

| Alan | Değer |
|------|-------|
| Menu key | `ops_sysctl` |
| Path | `/app/sysctl` |
| Component | `frontend/src/pages/SysctlPage.tsx` |
| Job module | `sysctl` |
| Capability | `sysctl` |
| Multi-server | `False` |
| Host merge | `keep` |
| Embedded console | `True` |

**Ops API:**

- `/api/ops/sysctl-templates`
- `/api/ops/sysctl-allowed`
- `/api/ops/servers/{id}/sysctl`

**Asistan katalog özeti:**

- sysctl parametreleri, shm, hugepages.
- Title EN: HugePages / sysctl
- Gerekli girdiler: sunucu, sysctl key=value satırları
- Checklist:
  - Sunucu seçin
  - Parametreleri yapıştırın
  - Önizleme → uygula
- Keywords: sysctl, hugepages, kernel, shmmax, shmall, vm.nr_hugepages, sem, kernel parametre

### Network Management (`ops_network`)

| Alan | Değer |
|------|-------|
| Menu key | `ops_network` |
| Path | `/app/network` |
| Component | `frontend/src/pages/NetworkPage.tsx` |
| Job module | `network` |
| Capability | `network_mgmt` |
| Multi-server | `False` |
| Host merge | `keep` |
| Embedded console | `True` |
| Backend | `backend/app/modules/network.py` |

**Ops API:**

- `/api/ops/vlan-pools`
- `/api/ops/servers/{id}/interfaces`
- `/api/ops/servers/{id}/network-interfaces`
- `/api/ops/servers/{id}/ip-change`

**Alt menü:**

- `network_add_network` → `/app/network?tab=network` (capability `network_add`, action `add_network`)
- `network_add_vlan` → `/app/network?tab=vlan` (capability `vlan_add`, action `add`)
- `network_ip_change` → `/app/network?tab=ipchange` (capability `network_ip_change`, action `change_ip`)

**Asistan katalog özeti:**

- Ağ işlemleri menüsü: Add Network, Add VLAN veya IP Değişikliği.
- Title EN: Network Management
- Gerekli girdiler: sunucu
- Checklist:
  - Sunucu seçin
  - Add Network / Add VLAN / IP Değişikliği seçin
- Kapsam dışı: Switch tarafı yapılandırma portal dışı.
- Keywords: network management, ağ yönetimi, network, nic, arayüz, network interface, ağ menü

#### Alt ops: Add Network (`network_add`)

- Route: `/app/network?tab=network`
- Özet: Ethernet veya bond ile IP/subnet/gateway; isteğe bağlı VLAN ID (access/trunk).
  - Sunucu seçin
  - Add Network seçin
  - ethernet veya bond seçin
  - IP/subnet/gateway (opsiyonel VLAN ID) doldurun
  - Önizleme → uygula
- Kapsam dışı: Yönetim / docker / ilo arayüzleri listelenmez. Switch tarafı portal dışı.

#### Alt ops: Add VLAN (`vlan_add`)

- Route: `/app/network?tab=vlan`
- Özet: Parent arayüz üzerinde VLAN + IP/gateway yapılandırması.
  - Sunucu seçin
  - Add VLAN seçin
  - Parent + VLAN + IP alanlarını doldurun
  - Önizleme → uygula
- Kapsam dışı: Switch tarafı VLAN trunk portal dışı.

#### Alt ops: IP Değişikliği (`network_ip_change`)

- Route: `/app/network?tab=ipchange`
- Özet: Mevcut IP taşıyan arayüzde IP/subnet/gateway (ana IP ise DNS) düzenleme; HPSA best-effort; birincil IP için DNS talep checklist.
  - Sunucu seçin
  - IP Değişikliği seçin
  - IP taşıyan interface seçin (DNS sonucu + birincil/ikincil bilgisi)
  - Alanları düzenleyin (birincil IP ise DNS zorunlu)
  - Önizleme → uygula
  - Apply aynı oturumda HPSA bs_software/bs_hardware (hata IP job'unu bozmaz)
  - Başarı sonrası: birincil IP ise DNS talebi; izleme bilgilendirme maili (TR/EN checklist)
- Kapsam dışı: DNS kaydı portalda oluşturulmaz; talep/mail metni checklist’te üretilir. İkincil IP’de DNS talebi gerekmez. docker/ilo/idrac listelenmez.

### ASM disk ekle (`ops_asm`)

| Alan | Değer |
|------|-------|
| Menu key | `ops_asm` |
| Path | `/app/asm` |
| Component | `frontend/src/pages/AsmPage.tsx` |
| Job module | `asm` |
| Capability | `asm_add_disk` |
| Multi-server | `max_2_cluster` |
| Host merge | `keep` |
| Embedded console | `True` |
| Backend | `backend/app/modules/asm.py` |

**Ops API:**

- `/api/ops/servers/{id}/asm-disks`
- `/api/ops/asm-seq-next`

**Partition kuralları:**

- Eşik: 2 TiB (2 * 1024^4)
- Altı: fdisk MBR single primary
- Üstü: parted GPT mkpart primary 0% 100%
- Başarı: partition block device node exists after partprobe/kpartx/multipath refresh — not fdisk exit code alone

**UI:**

- Mevcut ASM grupları chips from oracleasm listdisks; click fills alias prefix

**Asistan katalog özeti:**

- Oracle ASM için multipath veya sanal diske partition + oracleasm createdisk. <2TiB fdisk, ≥2TiB parted GPT. Cluster primary/peer.
- Title EN: Add ASM disk
- Gerekli girdiler: sunucu, alias öneki (örn. DATA), WWID listesi (fiziksel), talep id
- Checklist:
  - Sunucu(lar)ı seçin (cluster max 2, primary belirleyin)
  - Fiziksel: SCSI tara → WWID listesi kontrol
  - Mevcut ASM gruplarından chip ile alias öneki seçin veya elle girin
  - Partition: <2TiB fdisk, ≥2TiB parted (GPT, 0%–100%)
  - Diskleri sağa sürükleyip önizleme → uygula
- Kapsam dışı: ASM disk group oluşturma / rebalance portalda yok (DBA).
- Keywords: asm, oracleasm, createdisk, multipath, wwid, lun, disk ekle, asm disk, scandisks, mpath, storage disk, oracle disk, parted, fdisk, 2tb, 2tib, gpt, asm grup, disk group

### Mail Config (`ops_mail_config`)

| Alan | Değer |
|------|-------|
| Menu key | `ops_mail_config` |
| Path | `/app/mail-config` |
| Component | `frontend/src/pages/MailConfigPage.tsx` |
| Job module | `mail_config` |
| Capability | `mail_config` |
| Multi-server | `True` |
| Host merge | `keep` |
| Embedded console | `True` |

**Not:** Target server mail config — distinct from portal SMTP settings tab.

**Asistan katalog özeti:**

- Postfix kaldır, sendmail kur, DS smart host.
- Title EN: Mail Config
- Gerekli girdiler: sunucu, SMTP/DS host (Settings'teki mail ayarı)
- Checklist:
  - Settings'te SMTP host tanımlı olsun
  - Mail Config ekranında sunucu seçip çalıştırın
- Kapsam dışı: Kurumsal SMTP sunucu kurulumu portal dışı.
- Keywords: sendmail, postfix, smtp, mail, relay, smart host, DS, mail yapılandır, e-posta sunucu

## 7. Ayar panelleri

### general (tab=`general`)

- Host merge: `omit`
- Sebep: User stated host does not need Dropt general settings.

### automation (tab=`automation`)

- Host merge: `keep_under_dropt_submenu`
- API: `/api/settings`
- Not: SSH automation user / credential related portal settings.

### mail (tab=`mail`)

- Host merge: `keep_under_dropt_submenu`
- API: `/api/settings`
- Not: Portal SMTP — not target Mail Config op.

### assistant (tab=`assistant`)

- Host merge: `keep_under_dropt_submenu`
- API: `/api/settings`, `/api/assistant/*`
- Not: Enable assistant, Ollama gateway/direct, model. FAB depends on assistant_enabled event.

### repos (tab=`repos`)

- Host merge: `keep_under_dropt_submenu`
- API: `/api/package-repos`

### centrify (tab=`centrify`)

- Host merge: `keep_under_dropt_submenu`
- API: `/api/settings/centrify`
- Gerekli olduğu ops: hostname Centrify leave/join

### security (tab=`security`)

- Host merge: `split_subtabs`
  - Subtab `auth`: host_merge=`omit_if_host_has_ad_sso` — frontend/src/components/SecurityAuthSettings.tsx
    - `/api/identity`
  - Subtab `sessions`: host_merge=`relocate_to_host_top_settings_if_missing` — SecuritySessionsPanel in SecurityControlPanels.tsx
    - Tied to Dropt portal sessions. If host has its own session UI, omit; else relocate UI but keep API if Dropt tokens still used.
    - `/api/security/sessions`
    - `/api/security/sessions/mine`
    - `/api/security/sessions/{id}`
    - `/api/security/sessions/revoke-others`
  - Subtab `mfa`: host_merge=`relocate_to_host_top_settings_if_missing` — SecurityMfaPanel in SecurityControlPanels.tsx
    - `/api/security/mfa/users`
    - `/api/security/mfa/users/{user_id}/reset`
  - Subtab `tls`: host_merge=`omit_if_host_terminates_tls` — SecurityTlsPanel
    - `/api/security/tls`
    - `/api/security/tls/upload`
    - `/api/security/tls/self-signed`
  - Subtab `policy`: host_merge=`omit_if_host_has_password_policy` — SecurityPolicyPanel
    - `/api/security/policy`

### account (tab=`account`)

- Host merge: `omit`
- Sebep: User stated account section not needed.

### backup (tab=`backup`)

- Host merge: `keep_under_dropt_submenu`
- API: `settings backup download/import endpoints`
- Not: Dropt DB backup/restore — keep for ops data safety.

## 8. Backend API router’lar

| Module | Prefix | Host merge |
|--------|--------|------------|
| `backend/app/api/health.py` | `/` | `keep` |
| `backend/app/api/auth.py` | `/api` | `adapt_or_bridge` |
| `backend/app/api/settings.py` | `/api` | `keep_for_dropt_panels` |
| `backend/app/api/assistant.py` | `/api` | `keep` |
| `backend/app/api/package_repos.py` | `/api` | `keep` |
| `backend/app/api/centrify.py` | `/api` | `keep` |
| `backend/app/api/portal_users.py` | `/api` | `omit_if_host_users` |
| `backend/app/api/identity.py` | `/api` | `omit_if_host_ad_sso` |
| `backend/app/api/security.py` | `/api/security` | `keep_mfa_sessions_if_used` |
| `backend/app/api/servers.py` | `/api` | `keep_as_inventory_api_for_ops` |
| `backend/app/api/local_users.py` | `/api` | `keep` |
| `backend/app/api/hostname_api.py` | `/api` | `keep` |
| `backend/app/api/ops.py` | `/api/ops` | `keep_critical` |
| `backend/app/api/jobs.py` | `/api` | `keep_critical` |
| `backend/app/api/audit.py` | `/api` | `keep` |
| `backend/app/api/admin_system.py` | `/api` | `optional` |
| `backend/app/api/terminal.py` | `/api` | `keep` |

## 9. Job modülleri

- Registry: `backend/app/modules/registry.py`
- Contract: `ACTION_TITLES`, `job_summary`, `build_plans`, `apply_plan`
- Flow: createJob → previewJob → applyJob (SSE/WS progress on console)

Modüller:

- `local_user`
- `log_collect`
- `hostname`
- `reboot`
- `sudoers`
- `filesystem`
- `path_perms`
- `limits`
- `sysctl`
- `vlan`
- `network`
- `asm`
- `packages`
- `services`
- `mail_config`

## 10. Asistan

- Rol: operations_router_only_no_writes_on_targets
- Katalog: `backend/app/assistant/capabilities.json`
- Router: `backend/app/assistant/router.py`
- Analyze: `backend/app/assistant/analyze.py`

- **update_routes:** After embedding, rewrite capability route fields to host paths and keep titles matching menu labels.
- **keep_behavior:** Never auto job apply; deep link with serverId.

### Katalogda ek (sorgu / menü) capability’ler

#### `servers` — Sunucular

- Route: `/app/servers`
- Özet: Portal envanteri: listele, özet/dağılım (OS, status, key, virt, tag), IP/status/tag/OS filtrele; sunucu ekle.
  - Asistan readonly özet/liste üretir (uygulama yok)
  - Gerekirse Sunucular sayfasından inceleyin / düzenleyin

#### `jobs` — İşler

- Route: `/app/jobs`
- Özet: Job listesi / durum / hata özeti (readonly sorgu).
  - Sorgu sonucunu inceleyin
  - Ayrıntı için İşler sayfasını açın

#### `audit` — Denetim

- Route: `/app/audit`
- Özet: Portal audit kayıtları (kim / ne / ne zaman).
  - Sorgu sonucunu inceleyin
  - Denetim sayfasından detaya gidin

#### `portal_users` — Portal kullanıcıları

- Route: `/app/users`
- Özet: Portal kullanıcı listesi (Admin).
  - Admin yetkisi gerekir
  - Portal Kullanıcıları sayfasını açın

#### `package_repos` — Paket repo ayarları

- Route: `/app/settings`
- Özet: Local paket keyword/repo özeti (Admin).
  - Admin · Ayarlar / paket repo

#### `settings_info` — Portal ayarları

- Route: `/app/settings`
- Özet: App adı, SMTP host, Centrify tab özeti (readonly).
  - Readonly özet
  - Değişiklik Ayarlar sayfasında (Centrify sekmesi dahil)

#### `ops_catalog` — Ops katalog

- Route: `/app`
- Özet: İzinli sysctl / sudo şablon / VLAN pool / limits kalemleri.
  - Katalog özetini inceleyin

## 11. Cursor kuralları (kaynak metin)

### `.cursor/rules/dropt-assistant.mdc`

Topic: assistant red line, catalog, routing

```
# Dropt Ops Asistanı

## Kırmızı çizgi (zorunlu)

- **Ne Cursor agent ne Ops Asistan hedef sunucuda aksiyon alamaz.**
- SSH yazma, job create/apply, reboot, package install, ASM/FS uygulaması **yasak**.
- Asistan yönlendirir + **readonly** hedef probe + **portal DB sorgu** (IP filtre, job/audit listesi).
- Deep link hedef sunucuya gider; “X gibi” sunucu referanstır.
- Gerçek yazma: kullanıcının UI’da **Preview → Apply**.

## Katalog zorunluluğu

- Yeni operasyon / wizard / ops menü maddesi eklenince `backend/app/assistant/capabilities.json` **aynı PR’da** güncellenir.
- Katalog güncellenmeden “ops bitti” sayılmaz.
- `title_tr` / `title_en` = UI `ops_*` / child menü metni ile **birebir**.
- `route` = gerçek frontend path (`App.tsx`). Örn. portal kullanıcıları → `/app/users` (portal-users değil).
- `docs/assistant/capabilities.json` her zaman backend kopyası ile **senkron**.

## Ops envanteri (yönlendirme)

ServerOpsMenu / wizard’lar → katalog id:

| UI | capability id | route |
|----|---------------|-------|
| ASM disk ekle | `asm_add_disk` | `/app/asm` |
| FileSystem Management | `filesystem` (+ extend/create/organize) | `/app/filesystem` |
| Network Management | `network_mgmt` (+ add / vlan / ipchange) | `/app/network` |
| Hostname değiştir | `hostname` | `/app/hostname` |
| Sudo / Local users / Path / Limits / Sysctl | ilgili id | `/app/sudoers` … |
| Paket kur / Servisler / Mail / Reboot / Log / Terminal | ilgili id | … |
| Sunucular / İşler / Denetim | `servers` / `jobs` / `audit` | `/app/servers` … |
| Portal kullanıcıları | `portal_users` | **`/app/users`** |
| Ayarlar / paket repo / ops katalog | `settings_info` / `package_repos` / `ops_catalog` | `/app/settings` veya `/app` |

Ayrıntılı modül kalıbı: `dropt-ops-modules.mdc`. Hostname/IP yan etkileri: `dropt-ops-postchecks.mdc`. ASM partition: `dropt-ops-asm.mdc`.

## Yönlendirme davranışı

- Metinde hostname geçiyorsa envanterde çöz; deep link’e `serverId` / `serverIds` ekle (`buildOpsUrl` ile aynı).
- Short hostname tutuyorsa FQDN diye sorma.
- Gereksiz soru yok: “başarılı oldu mu?”, “şöyle mi böyle mi?”, “devam edeyim mi?”, “yardımcı oldu mu?”.
- Soru yalnız: ops belirsiz, sunucu yok / birden fazla **farklı** sunucu, zorunlu alan metinden çıkmıyor.
- Envanter / IP / job / audit sorularında sunucu sorma; `operation_id` = `servers` / `jobs` / `audit`.
- Uydurma operasyon adı yok; `summary_tr` içinde `title_tr` birebir.

## Readonly analiz (`analyze.py`)

- Yönlendirmeden sonra hedef sunucuya **readonly** probe (cache’li inventory) eklenebilir.
- Probe yok: `terminal`, `reboot`, `log_collect`, `mail_config`, `path_perms`.
- Probe var: FS / sysctl / limits / packages / services / network+vlan / ASM / hostname / sudoers / local_users.
- Portal DB Q&A yüksek güvenle eşleşince LLM atlanabilir (`router.py`).

## Hostname / IP sonrası (bilgi)

- Hostname: Centrify leave/join + HPSA best-effort; Settings Centrify creds; fail job’u bozmaz.
- IP change: apply sonunda HPSA (`|| true`); DNS/izleme checklist UI + `after_state` (TR + `checklist_en`).
- Domain = FQDN ilk `.` sonrası. Ayrıntı: `dropt-ops-postchecks.mdc`.

## Self-improve / oturum

- Feedback (thumbs down → doğru ops) telemetry/katalog keyword girdisidir; sunucuda işlem değildir.
- Chat geçmişi kısa TTL (~24h); hostname index / model listesi kısa TTL OK.
- Katalog/keyword değişince her iki `capabilities.json` senkron.
```

### `.cursor/rules/dropt-ops-modules.mdc`

Topic: new ops checklist

```
# Yeni operasyon ekleme kalıbı

Bu kural **kod iskeleti** içindir. Hedef sunucuya bağlanıp işlem yapmak **yasaktır**.

## Checklist

1. `backend/app/modules/<ad>.py` — `ACTION_TITLES`, `job_summary`, `build_plans`, `apply_plan` (mevcut asm/filesystem/mail_config kalıbı).
2. Job registry (`modules/registry.py`) + API wiring (`ops.py` veya ilgili router).
3. `frontend/src/pages/<Ad>Page.tsx` — Talep ID, preview/apply, `useServerQuery` / ServerPicker.
4. `ServerOpsMenu.tsx` — `path` + icon + i18n key; gerekirse `App.tsx` route.
5. `frontend/src/i18n/messages.ts` — `ops_*` ve `wizard_*` (TR + EN).
6. **`backend/app/assistant/capabilities.json`** — id, title (UI ile birebir), **doğru route**, keywords, checklist, out_of_scope → `docs/assistant/capabilities.json` kopyala.
7. Hostname/IP yan etkileri → `dropt-ops-postchecks.mdc`.
8. ASM partition / grup UI → `dropt-ops-asm.mdc`.
9. İsteğe bağlı `docs/<ad>.md` runbook.

## Kayıtlı job modülleri

`local_user`, `log_collect`, `hostname`, `reboot`, `sudoers`, `filesystem`, `path_perms`, `limits`, `sysctl`, `vlan`, `network`, `asm`, `packages`, `services`, `mail_config`

## Deep link

- Tek sunucu: `?serverId=<id>`
- Cluster (max 2, ASM): `?serverId=<primary>&serverIds=id1,id2`
- FS alt: `?mode=extend|create|organize`
- Network alt: `?tab=network|vlan|ipchange`
- Asistan FAB ve ops menü aynı URL şeklini kullanır.

## Yapma

- “Docker kur ekranı ekle” = portal kodu + katalog; sunucuda `dnf install` / SSH denemesi yok (`/app/docker` → packages).
- Asistan yanıtında uydurma operasyon adı yok.
```

### `.cursor/rules/dropt-ops-postchecks.mdc`

Topic: hostname/IP Centrify HPSA DNS checklists

```
# Hostname & IP — post-check ve yan etkiler

## FQDN / domain

- Domain = FQDN’de **ilk `.` sonrası** (`test.datatem.local` → `datatem.local`).
- Short = ilk label. `hostname.split_fqdn` / inventory aynı kural.

## Hostname apply sırası

1. Centrify varsa (`adinfo -a`): Zone + domain (`Current DC` ilk `.` sonrası).
2. Settings → Centrify’te domain eşleşen (user/pass) varsa: `adleave -f user` (şifresiz).
3. `hostnamectl` + `/etc/hosts` (asıl iş; fail = job fail).
4. `echo pass | adjoin -z ZONE -c "kfs.local/Centrify/Unix Servers/Redhat" -f -u user domain`.
5. HPSA: `bs_software` + `bs_hardware` (best-effort).
6. Centrify/HPSA hatası **hostname success’i bozmaz**; başarıysa `after_state.post_notes`.

## IP change apply

- nmcli up sonrası **aynı SSH script** içinde:
  `bs_software --debug || true; bs_hardware --debug || true`
  (bağlantı kopmadan; HPSA fail IP job’unu bozmaz).
- Birincil IP: default-route + Dropt `nslookup` teyidi (`network.py` inventory).

## Başarı sonrası checklist (UI + after_state)

- Frontend: `frontend/src/lib/opsPostchecks.ts` (locale tr|en).
- Backend: `checklist` (TR) + `checklist_en` (EN); JobDetail locale’e göre seçer.
- Ortak DNS madde 1: DNS Tanımı / DNS Kayıt Değiştirme talep metni (dinamik FQDN/IP).

Hostname madde 2 mail:
- To: Sanallaştırma…, Sistem İzleme…, Sistem İşletim…, **Altyapı İzleme**
- CC: **Unix Linux Sistem Tasarım ve Planlama**

IP madde 1 başı: yalnızca **birincil IP** (DNS sorgusu ile eşleşen) için DNS talebi; ikincil IP’de gerek yok.
IP UI: checklist üstünde DNS sorgu sonucu (hostname + IP); paneller `w-full`.
IP madde 2 mail:
- To: Sistem İzleme…, Sistem İşletim…, **Altyapı İzleme**
- CC: **Unix Linux Sistem Tasarım ve Planlama**
- Metin: `"fqdn" ("eski_ip") … "fqdn" ==> "yeni_ip"`

## Settings

- Centrify credentials: `/api/settings/centrify`, UI tab **Centrify** (domain unique, password Fernet).
```

### `.cursor/rules/dropt-ops-asm.mdc`

Topic: ASM fdisk/parted 2TiB groups UI

```
# ASM disk ekleme

## Partition aracı (zorunlu)

- Eşik: `TWO_TB = 2 * 1024**4` (2 TiB) — `asm.py`.
- **&lt; 2 TiB** → `fdisk` (MBR: `n` / primary / 1 / default / `w`).
- **≥ 2 TiB** → `parted`: `mklabel gpt` + `mkpart primary 0% 100%`.
- Preview/plan’da `partition_tool` alanı bu eşiğe göre set edilir.
- Başarı ölçütü: fdisk/parted exit kodu değil; beklenen **partition node** (`partprobe` / `kpartx` / multipath yenileme sonrası). Multipath’te fdisk re-read ioctl non-zero dönebilir — tablo yine yazılmış olabilir.

## Apply akışı (özet)

1. (Fiziksel) SCSI scan / multipath alias.
2. Partition oluştur (`_create_partition`).
3. `oracleasm createdisk <ASM_NAME> <partition_path>`.
4. Cluster: primary + peer (max 2).

## UI — mevcut ASM grupları

- `oracleasm listdisks` + normalize → renkli grup chip’leri (“Mevcut ASM grupları”).
- Chip tıklanınca alias prefix alanı dolar.
- Loglardaki “yeni atanmış diskler” yerine bu grup listesi kullanılır.

## Asistan

- Yönlendirme: `asm_add_disk` → `/app/asm`.
- Disk group create / rebalance portal dışı (DBA).
```

### `docs/host-merge/dropt-host-merge.mdc` (hedefe kopyala)

```
# Dropt → Host merge (hedef repo)

Bu repoda Dropt Ops özelliklerini **gömüyorsan** önce şu manifesti oku ve ona uy:

`docs/host-merge/dropt-host-merge-manifest.json`

(Manifest yolu farklıysa kullanıcı yolunu düzeltmiş olabilir — `dropt-host-merge-manifest.json` ara.)

## Zorunlu ilkeler

1. **Login / AppShell taşıma.** Host login ve ana menü kullanılır. Dropt `LoginPage` + tam `AppShell` gömülmez.
2. **Sunucu listesi host’tan.** vCenter listesi kalır. Çift tık → Dropt `ServerConsole` / ops menü kalıbı (`OpsWizardContext.embedded=true`).
3. **Dropt `TargetServer.id` şart.** Host satırı → Dropt inventory upsert/map olmadan ops API çalışmaz.
4. **Auth bridge.** Dropt API Bearer token ister (`dtt_access_token` veya eşdeğeri). Host oturumundan token exchange / shared JWT planla.
5. **Ayarlar split:**
   - OMIT: general, account
   - KEEP under Dropt submenu: automation, mail, assistant, repos, centrify, backup
   - Security: host’ta AD/SSO/TLS varsa OMIT; MFA/sessions host’ta yoksa host üst Ayarlar’a taşı (API modelini kontrol et)
6. **Jobs + Audit** Dropt submenu’de kalsın (ops izi).
7. **Asistan yazmaz.** Yönlendirir; job auto-apply yok. `capabilities.json` route’larını host path’lere güncelle.
8. **Hostname/IP/ASM yan etkileri** bozulmasın: Centrify, HPSA, DNS checklist, ASM &lt;2TiB fdisk / ≥2TiB parted.

## Çalışma sırası

Manifest `host_merge_playbook` adımlarını izle (auth → server map → console → jobs → settings → capabilities → verify).

## Yapma

- Manifest’teki `do_not` listesine uy.
- Uydurma ops adı / route önerme.
- Embedded preview/apply akışını standalone job sayfasına zorla kırma (console gömülüyse).
```

## 12. Host merge playbook

### Adım 1: Auth bridge

- Skip Dropt LoginPage
- Ensure Dropt API accepts host identity (token exchange or shared JWT)
- Set dtt_access_token or refactor api.ts auth header source

### Adım 2: Server identity

- Keep host vCenter server list UI
- On select/double-click: upsert/find Dropt TargetServer by IP/hostname/UUID
- Open console/ops with dropt numeric server id

### Adım 3: Embed ops console

- Port ServerConsolePage + ServerOpsMenu + OpsWizardContext
- Preserve embedded preview/apply behavior
- Mount under host menu e.g. Ops / Unix Ops

### Adım 4: Jobs and audit

- Expose Jobs + JobDetail + Audit under Dropt submenu
- Fix deep links from console to host job routes

### Adım 5: Settings split

- Omit general + account
- Keep automation, mail, assistant, repos, centrify, backup under Dropt submenu
- Inventory host security: if MFA/sessions missing, relocate those panels to host top Settings; omit AD/SSO/TLS if host already provides

### Adım 6: Assistant + capabilities

- Update capabilities.json routes to host paths
- Sync docs copy
- Point FAB to host router base

### Adım 7: Verify

- Double-click server → ops menu → each wizard preview
- Hostname Centrify path with settings creds
- IP change primary DNS checklist
- ASM disk <2TiB and ≥2TiB partition tools
- Terminal websocket
- Job apply from console

## 13. Yapma (do_not)

- Auto-apply jobs from assistant or host
- Drop Dropt TargetServer requirement without a mapping layer
- Mount full AppShell+Login into host
- Assume host MFA UI replaces Dropt MFA API without checking token model
- Forget Centrify settings when embedding hostname
- Break OpsWizardContext.embedded preview flow

## 14. Önce kopyalanacak dosyalar

- `frontend/src/pages/ServerConsolePage.tsx`
- `frontend/src/components/ServerOpsMenu.tsx`
- `frontend/src/hooks/useOpsWizard.ts`
- `frontend/src/pages/*Page.tsx (ops wizards)`
- `frontend/src/lib/opsPostchecks.ts`
- `frontend/src/api.ts (or split ops client)`
- `backend/app/modules/**`
- `backend/app/api/ops.py`
- `backend/app/api/jobs.py`
- `backend/app/assistant/**`
- `docs/host-merge/dropt-host-merge-manifest.json`
- `.cursor/rules/dropt-*.mdc`

## 15. Host ekibi dolduracak alanlar

- **host_menu_path:** `FILL_ME e.g. /ops/unix`
- **host_settings_dropt_submenu:** `FILL_ME e.g. Settings → Dropt Ops`
- **host_top_settings_for_mfa_sessions:** `FILL_ME if relocating`
- **host_server_id_field:** `FILL_ME vCenter moId / uuid`
- **host_auth_bridge_endpoint:** `FILL_ME`

## 16. Hedef Cursor’a örnek prompt

```
@DROPT-OPS-HANDBOOK.md
@dropt-host-merge-manifest.json
@dropt-host-merge.mdc
@capabilities.json

Dropt Ops Portal'ı bu uygulamaya gömüyoruz.
El kitabı + manifest + kurallara göre TÜM operasyonların eksiksiz olduğundan emin ol.
Eksik wizard, API wiring, settings paneli, Centrify/HPSA/ASM/DNS checklist veya
embedded console akışı varsa tamamla.
- Login yok (bizde var)
- Sunucu listesi vCenter; çift tık → Dropt ops console
- Ayarlar: general/account yok; automation/mail/assistant/repos/centrify/backup Dropt submenu
- MFA/oturumlar bizde yoksa üst Ayarlar'a taşı
Önce auth bridge + server identity mapping planı çıkar, sonra gap listesi üret ve uygula.
```

---

*Otomatik üretildi: `docs/host-merge/generate_ops_handbook.py`*
