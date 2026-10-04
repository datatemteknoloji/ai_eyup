# Delinea Server Suite — Zone Yönetim Modülü Tasarım Dokümanı

> **Durum:** Tasarım · **Sürüm:** 0.3 · **Tarih:** 2026-10-04

---

## 1. Amaç ve Kapsam

ainew platformuna, Delinea (eski adıyla Centrify) Server Suite **zone modeli** yönetim arayüzü ekliyoruz.
Hedef: Access Manager konsolundaki işlevlerin (zone, computer, UNIX data, rol, komut/right,
computer role, role assignment) ainew UI'dan yönetilmesi. Birebir kopya değil; ainew'in mevcut
UX kalıplarıyla uyumlu, kullanıcı dostu bir arayüz.

### Mevcut durum

- ainew Linux sunucuda çalışıyor; backend Python 3.11 + FastAPI, frontend React 18 + Tailwind.
- Tüm Linux sunucularda Centrify agent kurulu. Zone modeli AD içinde duruyor.
- Ortam 5+ yıldır üretimde — sıfırdan kurulum değil, **mevcut veriyi içeri alma** gerekiyor.
- Level 1 modülü (Dropt sidecar) hostname değişikliğinde zaten `adleave`/`adjoin` kullanıyor.
  Dropt tarafında basit bir `CentrifyCredential` store'u var — **dokunulmaz, ayrı kalır**.
- Centrify yönetimi bir **Windows sunucu** üzerinden yapılıyor. Access Manager bu sunucuda kurulu.
  Operatörler RDP ile `service_centrify` hesabıyla bağlanıp işlem yapıyor.

### Kapsam

| Desteklenen | Kapsam dışı |
|-------------|-------------|
| Rol oluşturma / silme / düzenleme | Linux sunuculara doğrudan müdahale (SSH, adflush) |
| Rol kopyalama (komutlarıyla, zone'lar arası) | Audit Manager / DirectAudit |
| Rol overwrite (diff önizlemeli) | PAS / Delinea Platform (SaaS) |
| Komut/right tanımlama / düzenleme / silme | Session okuma/arama (Audit Store) |
| Komut → role ekleme / çıkarma | Zone/Role tanımlarının uygulama dışında otomatik değiştirilmesi |
| Kullanıcıya/gruba role assignment | |
| Kullanıcıyı AD grubuna ekleme / çıkarma | |
| Computer role oluşturma / düzenleme / silme | |
| Kullanıcıya sudo/dzdo yetkisi (role assignment ile) | |
| UNIX profil görüntüleme | |

---

## 2. Mimari

### 2.1 Windows Gateway (WinRM)

Centrify yönetimi **Access Manager'ın çalıştığı Windows sunucu** üzerinden yapılır.
ainew bu sunucuya WinRM ile bağlanır. ainew'den doğrudan AD'ye LDAP/Kerberos bağlantısı **yoktur**.

```
┌──────────────────────────────────────────────────────────┐
│  ainew (Linux, network_mode: host)                       │
│                                                          │
│  Frontend (/level1/centrify)                             │
│     │                                                    │
│  Backend API (/api/v1/centrify-mgmt/*)                   │
│     │                                                    │
│  Celery Worker (-Q centrify)                             │
│     │                                                    │
│  WinRMCentrifyAdapter ──► pywinrm (mevcut WinRMClient)   │
│     │                                                    │
│  Centrify DB (:5434)    Redis (lock + circuit breaker)   │
└──────┬───────────────────────────────────────────────────┘
       │ WinRM (5985/5986 NTLM)
       │ service_centrify + şifre
       ▼
┌──────────────────────────────────┐
│  Windows Sunucu                  │
│  (Access Manager kurulu)         │
│  domain-joined                   │
│                                  │
│  ADEdit + PowerShell cmdlet'leri │
│     │                            │
│     ▼                            │
│  Active Directory                │
│  └── Zone nesneleri              │
└──────────────────────────────────┘
```

**Bu mimari ile gerekli olmayanlar:**
- ainew'e ADEdit / centrifydc kurulumu
- ainew'den AD'ye LDAP/Kerberos bağlantısı
- Keytab dosyası (opsiyonel, ileride; şu an şifre ile)
- Zone Base DN (Windows sunucu zaten biliyor)
- AD host/port yapılandırması (ainew'deki IdentityConfig'ten ayrı)

### 2.2 Modül konumu: ainew ana backend (Dropt değil)

Dropt, basit sunucu SSH operasyonları için tasarlanmış bir sidecar'dır. Zone yönetimi bu kapsama
sığmaz — Tier 0'a yakın, kendi RBAC'si, audit'i, durum makinesi gerektiren bir modül.

```
ainew ana backend (backend/app/)
├── api/centrify_mgmt.py          ← REST endpoint'leri
├── api/centrify_chat.py          ← AI asistan endpoint
├── services/centrify/
│   ├── winrm_adapter.py           ← WinRM üzerinden ADEdit/PowerShell
│   ├── winrm_adapter_fake.py      ← Test fake'i
│   ├── sync_service.py            ← Windows → DB senkronizasyon
│   ├── provisioning_service.py    ← Yazma işleri orkestrasyon
│   ├── state_machine.py           ← Durum makinesi
│   ├── drift_detector.py          ← Drift tespiti
│   ├── circuit_breaker.py         ← Auth fail lockout koruması
│   └── ps_scripts/                ← PowerShell scriptleri (.ps1)
│       ├── list_zones.ps1
│       ├── list_roles.ps1
│       ├── create_role.ps1
│       ├── clone_role.ps1
│       ├── overwrite_role.ps1
│       ├── create_command.ps1
│       ├── create_role_assignment.ps1
│       └── ...
├── models/centrify_zone.py        ← SQLAlchemy ORM (Centrify DB'de)
└── rag_seed/centrify/             ← Delinea resmi dokümanları (AI RAG)
```

Frontend rotası `/level1/centrify` altında; API çağrıları doğrudan ainew backend'ine
(`/api/v1/centrify-mgmt/…`), Dropt köprüsünden **geçmez**.

### 2.3 Katmanlı mimari

```
┌──────────────────────────────────────────────────────────────┐
│  API katmanı  (centrify_mgmt.py)                             │
│  HTTP, Pydantic doğrulama, JWT auth, RBAC kontrol            │
│  İş mantığı İÇERMEZ                                         │
├──────────────────────────────────────────────────────────────┤
│  Servis (domain) katmanı  (provisioning_service.py)          │
│  "Role assignment oluştur", "rolü kopyala" gibi kavramlar    │
│  Bağlantı yöntemini bilmez — port/adaptör arayüzü kullanır  │
├──────────────────────────────────────────────────────────────┤
│  Adaptör katmanı  (winrm_adapter.py / winrm_adapter_fake.py)│
│  WinRM ile Windows sunucuya PowerShell scripti gönderir      │
│  Yarın başka bir yola geçilirse YALNIZCA burası değişir      │
├──────────────────────────────────────────────────────────────┤
│  Kalıcılık katmanı  (models/, Centrify DB)                   │
│  SQLAlchemy ORM, ayrı Postgres container                     │
├──────────────────────────────────────────────────────────────┤
│  Arka plan işçileri  (Celery -Q centrify)                    │
│  Senkron + provisioning — API sürecinden ayrı                │
└──────────────────────────────────────────────────────────────┘
```

### 2.4 Okuma ve yazma ayrımı

| İşlem | Kaynak | Araç | Neden |
|-------|--------|------|-------|
| Ağaç, liste, detay görüntüleme | Centrify DB | SQLAlchemy | Request path'te WinRM yok — hızlı |
| Zone nesne senkronizasyonu | Windows sunucu → AD | WinRM + PowerShell | Periyodik; DB'ye yazar |
| Zone nesne yazma | AD (Windows sunucu üzerinden) | WinRM + ADEdit/PowerShell | Kuyruktan |
| Grup üyeliği okuma/yazma | AD (Windows sunucu üzerinden) | WinRM + PowerShell | AD cmdlet'leri |
| Doğrulama (yazma sonrası) | AD (Windows sunucu üzerinden) | WinRM + PowerShell | Geri oku + hash |

**Kural:** UI listeleri ve ağaç her zaman DB'den gelir. WinRM asla request path'te çağrılmaz.

### 2.5 Ayrı veritabanı (Dropt modeli)

Centrify zone verileri **ainew Timescale DB'de değil, ayrı bir Postgres container'da** tutulur.

Gerekçeler:
- **İzolasyon:** Centrify DB çökse/dolsa ainew etkilenmez.
- **Bağımsız yedek/restore:** Zone verileri ayrı dump/restore edilebilir.
- **Bağımsız migration:** ainew tablolarıyla çakışmaz.
- **Güvenlik:** Centrify DB kullanıcısı ainew tablolarına erişemez.
- **Kanıtlanmış pattern:** Dropt sidecar zaten ayrı DB ile sorunsuz çalışıyor.

```yaml
# docker-compose.centrify.yml (ana compose'a include edilir)
services:
  centrify-db:
    image: postgres:16-alpine
    container_name: centrify_db
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${CENTRIFY_DB_USER:-centrify}
      POSTGRES_PASSWORD: ${CENTRIFY_DB_PASSWORD:?gerekli}
      POSTGRES_DB: ${CENTRIFY_DB_NAME:-centrify_zone_mgmt}
    ports:
      - "127.0.0.1:5434:5432"
    volumes:
      - ${DATA_DIR:-./data}/centrify/postgres:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U centrify"]
      interval: 5s
      timeout: 5s
      retries: 10
```

Backend bağlantısı:
```python
# backend/app/core/config.py'ye eklenir
CENTRIFY_DATABASE_URL = os.getenv("CENTRIFY_DATABASE_URL", "")
# docker-compose.yml environment'a eklenir
```

ainew `servers` tablosuna soft reference (`ainew_server_id INTEGER`, FK yok).

### 2.6 Kuyruk ve kilit altyapısı

Mevcut **Celery + Redis** altyapısını kullanır (`backend/app/worker.py`).
Centrify task'ları **ayrı queue** (`-Q centrify`) ile çalışır — ana queue'yu bloklamaz.

Zone kilidi için mevcut `fleet_mutex.py` Redis SET NX pattern'i genişletilir:
```python
_LOCKS["centrify_zone"] = threading.Lock()
# Kullanım: fleet_lock(f"centrify_zone:{zone_id}", ttl_sec=300)
```

### 2.7 Auth ve RBAC

ainew'in mevcut JWT auth + modül RBAC sistemi kullanılır.

**Modül tanımı** (`DEFAULT_MODULES` listesine):
```python
{"id": "centrify", "name": "Centrify / Delinea",
 "description": "Delinea Server Suite zone, role, right, assignment yönetimi",
 "icon": "KeyRound", "color": "purple", "sort_order": 13},
```

**Granüler yetkiler:**

| Yetki | Açıklama |
|-------|----------|
| `centrify.read` | Ağaç, liste, detay okuma |
| `centrify.group_membership` | AD grup üyeliği yönetimi |
| `centrify.role_assignment` | Role assignment oluştur/sil |
| `centrify.role_define` | Rol tanımla/düzenle/kopyala/overwrite |
| `centrify.command_define` | Komut/right tanımla (en riskli) |
| `centrify.approve` | Onaylama yetkisi |

Kapsam bazlı kısıtlama: hangi zone, hangi rol öneki.
Kendi isteğini kendi onaylama **yasak** (dört göz).

---

## 3. WinRM Adaptörü (En Kritik Bileşen)

### 3.1 Yapısı

Mevcut `WinRMClient` (`backend/app/services/windows/winrm_client.py`) üzerine inşa edilir.

```python
# backend/app/services/centrify/winrm_adapter.py

from backend.app.services.windows.winrm_client import WinRMClient

class WinRMCentrifyAdapter:
    """Access Manager Windows sunucusuna WinRM ile bağlanır.
    PowerShell scriptleri göndererek zone yönetimi yapar."""

    def __init__(self, host: str, username: str, password: str,
                 port: int = 5985, use_https: bool = False, timeout: int = 60):
        self.client = WinRMClient(host, username, password,
                                   port=port, use_https=use_https, timeout=timeout)

    # ── Okuma ──────────────────────────────────────────

    def list_zones(self) -> list[ZoneData]: ...
    def list_roles(self, zone_dn: str) -> list[RoleData]: ...
    def list_commands(self, zone_dn: str) -> list[CommandData]: ...
    def list_role_assignments(self, zone_dn: str) -> list[AssignmentData]: ...
    def list_computer_roles(self, zone_dn: str) -> list[ComputerRoleData]: ...
    def list_computers(self, zone_dn: str) -> list[ComputerData]: ...
    def list_unix_profiles(self, zone_dn: str) -> list[UnixProfileData]: ...
    def get_role_detail(self, zone_dn: str, role_name: str) -> RoleDetail: ...

    # ── Yazma ──────────────────────────────────────────

    def create_role(self, zone_dn, name, description) -> OpResult: ...
    def update_role(self, zone_dn, name, new_desc) -> OpResult: ...
    def delete_role(self, zone_dn, name) -> OpResult: ...
    def clone_role(self, src_zone, src_role, dst_zone, dst_name) -> OpResult: ...
    def overwrite_role_commands(self, zone_dn, target_role, source_commands) -> OpResult: ...

    def create_command(self, zone_dn, name, path, run_as, auth_type, match) -> OpResult: ...
    def update_command(self, zone_dn, name, **fields) -> OpResult: ...
    def delete_command(self, zone_dn, name) -> OpResult: ...
    def add_command_to_role(self, zone_dn, role, command) -> OpResult: ...
    def remove_command_from_role(self, zone_dn, role, command) -> OpResult: ...

    def create_role_assignment(self, zone_dn, role, assignee_dn, scope) -> OpResult: ...
    def delete_role_assignment(self, zone_dn, assignment_id) -> OpResult: ...

    def add_user_to_group(self, group_dn, user_dn) -> OpResult: ...
    def remove_user_from_group(self, group_dn, user_dn) -> OpResult: ...

    def create_computer_role(self, zone_dn, name) -> OpResult: ...
    def delete_computer_role(self, zone_dn, name) -> OpResult: ...

    # ── Bağlantı testi ─────────────────────────────────

    def test_connection(self) -> ConnectionTestResult: ...
```

### 3.2 PowerShell scriptleri

`backend/app/services/centrify/ps_scripts/` altında `.ps1` dosyaları olarak versiyonlanır.
Kullanıcı girdisi PowerShell'e string interpolasyon **yapılmaz** — parametre olarak geçirilir.

```powershell
# ps_scripts/list_roles.ps1
# Parametre: $ZoneDN
param([string]$ZoneDN)

# ADEdit ile
$adedit = @"
bind_to_dc
select_zone "$ZoneDN"
set roles [list_roles]
foreach r $roles {
    select_role $r
    set desc [get_role_field description]
    set guid [get_role_field objectGUID]
    puts "ROLE_JSON:{\"name\":\"$r\",\"description\":\"$desc\",\"guid\":\"$guid\"}"
}
"@
$result = echo $adedit | adedit
$lines = $result | Where-Object { $_ -match "^ROLE_JSON:" }
$roles = $lines | ForEach-Object { ($_ -replace "^ROLE_JSON:","") | ConvertFrom-Json }
$roles | ConvertTo-Json -Depth 5
```

**Çıktı sözleşmesi:** Her script JSON çıktı üretir. Parse tek yerde yapılır,
şema doğrulamasından geçer. Beklenmeyen çıktı = hata.

### 3.3 Hata sınıflandırması

```python
class CentrifyErrorClass(Enum):
    TRANSIENT  = "transient"    # WinRM ağ hatası, timeout → sınırlı retry (max 2)
    PERMANENT  = "permanent"    # auth fail, nesne yok, yetki yok → durdur, retry YASAK
    AMBIGUOUS  = "ambiguous"    # WinRM timeout ama komut çalışmış olabilir → AD'den oku
```

### 3.4 Lockout koruması (circuit breaker)

```python
# backend/app/services/centrify/circuit_breaker.py

CENTRIFY_AUTH_FAIL_KEY = "centrify:auth_fail_count"
CENTRIFY_CIRCUIT_KEY   = "centrify:circuit_open"
MAX_AUTH_FAILS         = 2       # 2 fail → circuit aç (AD lockout threshold'undan düşük)
CIRCUIT_RESET_TTL      = 3600   # 1 saat sonra otomatik kapanır, veya admin reset
```

- Şifre ainew DB'de `CredentialManager` ile şifreli saklanır (mevcut Dropt pattern'i).
- Her WinRM işleminde auth **bir kez** denenir. Başarısızsa hemen durulur, retry **yapılmaz**.
- Auth hatası `PERMANENT` sınıfı — otomatik retry yasak.
- 2 art arda auth fail → circuit açılır → **tüm yazma ve okuma işlemleri durur**.
- Circuit açıkken UI'da kırmızı banner gösterilir. Admin müdahalesiyle reset.
- Bağlantı testi (yapılandırma sırasında) tek seferlik deneme; retry kullanıcının kararı.

### 3.5 İdempotency

Her işlem "zaten var mı" kontrolüyle başlar. Aynı işin iki kez çalışması hata değil, no-op.

### 3.6 Güvenlik

- Kullanıcı girdisi PowerShell'e interpolasyon **yapılmaz** — parametre olarak geçilir.
- PowerShell scriptleri dosya olarak versiyonlanır → değişiklik diff'te görülür.
- WinRM çıktısında hassas veri maskelenir (şifre, keytab).
- API katmanında Pydantic v2 ile doğrulama.

---

## 4. Veri Modeli (Centrify DB — :5434)

### 4.1 Ana tablolar

```sql
-- Zone ağacı
CREATE TABLE centrify_zones (
    id              SERIAL PRIMARY KEY,
    ad_guid         UUID NOT NULL UNIQUE,
    ad_dn           TEXT NOT NULL,
    name            TEXT NOT NULL,
    zone_type       TEXT NOT NULL,               -- 'hierarchical' | 'classic'
    parent_zone_id  INTEGER REFERENCES centrify_zones(id),
    description     TEXT,
    management_state TEXT NOT NULL DEFAULT 'imported_readonly',
    source_hash     TEXT,
    last_synced_at  TIMESTAMPTZ,
    last_seen_in_ad TIMESTAMPTZ,
    deleted_in_ad   BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Computer (zone üyesi sunucular)
CREATE TABLE centrify_computers (
    id              SERIAL PRIMARY KEY,
    zone_id         INTEGER NOT NULL REFERENCES centrify_zones(id),
    ad_guid         UUID NOT NULL UNIQUE,
    ad_dn           TEXT NOT NULL,
    name            TEXT NOT NULL,
    fqdn            TEXT,
    os_type         TEXT,
    agent_version   TEXT,
    ainew_server_id INTEGER,                     -- soft ref (FK yok; ainew DB'de)
    management_state TEXT NOT NULL DEFAULT 'imported_readonly',
    source_hash     TEXT,
    last_synced_at  TIMESTAMPTZ,
    last_seen_in_ad TIMESTAMPTZ,
    deleted_in_ad   BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Role tanımları
CREATE TABLE centrify_roles (
    id              SERIAL PRIMARY KEY,
    zone_id         INTEGER NOT NULL REFERENCES centrify_zones(id),
    ad_guid         UUID NOT NULL UNIQUE,
    ad_dn           TEXT NOT NULL,
    name            TEXT NOT NULL,
    description     TEXT,
    is_system_role  BOOLEAN DEFAULT FALSE,
    management_state TEXT NOT NULL DEFAULT 'imported_readonly',
    source_hash     TEXT,
    last_synced_at  TIMESTAMPTZ,
    last_seen_in_ad TIMESTAMPTZ,
    deleted_in_ad   BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Command/Right tanımları
CREATE TABLE centrify_commands (
    id              SERIAL PRIMARY KEY,
    zone_id         INTEGER NOT NULL REFERENCES centrify_zones(id),
    ad_guid         UUID NOT NULL UNIQUE,
    ad_dn           TEXT NOT NULL,
    name            TEXT NOT NULL,
    command_path    TEXT,
    match_type      TEXT,                         -- 'exact' | 'glob' | 'regex'
    run_as_user     TEXT DEFAULT 'root',
    run_as_group    TEXT,
    auth_type       TEXT DEFAULT 'password',      -- 'password' | 'none' | 'mfa'
    description     TEXT,
    management_state TEXT NOT NULL DEFAULT 'imported_readonly',
    source_hash     TEXT,
    last_synced_at  TIMESTAMPTZ,
    last_seen_in_ad TIMESTAMPTZ,
    deleted_in_ad   BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Role <-> Command ilişkisi
CREATE TABLE centrify_role_commands (
    id              SERIAL PRIMARY KEY,
    role_id         INTEGER NOT NULL REFERENCES centrify_roles(id),
    command_id      INTEGER NOT NULL REFERENCES centrify_commands(id),
    UNIQUE(role_id, command_id)
);

-- Computer Role
CREATE TABLE centrify_computer_roles (
    id              SERIAL PRIMARY KEY,
    zone_id         INTEGER NOT NULL REFERENCES centrify_zones(id),
    ad_guid         UUID NOT NULL UNIQUE,
    ad_dn           TEXT NOT NULL,
    name            TEXT NOT NULL,
    description     TEXT,
    management_state TEXT NOT NULL DEFAULT 'imported_readonly',
    source_hash     TEXT,
    last_synced_at  TIMESTAMPTZ,
    last_seen_in_ad TIMESTAMPTZ,
    deleted_in_ad   BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Computer <-> Computer Role
CREATE TABLE centrify_computer_role_members (
    id              SERIAL PRIMARY KEY,
    computer_id     INTEGER NOT NULL REFERENCES centrify_computers(id),
    computer_role_id INTEGER NOT NULL REFERENCES centrify_computer_roles(id),
    UNIQUE(computer_id, computer_role_id)
);

-- Role Assignment
CREATE TABLE centrify_role_assignments (
    id              SERIAL PRIMARY KEY,
    zone_id         INTEGER NOT NULL REFERENCES centrify_zones(id),
    ad_guid         UUID,
    ad_dn           TEXT,
    role_id         INTEGER NOT NULL REFERENCES centrify_roles(id),
    assignee_type   TEXT NOT NULL,                -- 'user' | 'group' | 'computer_role'
    assignee_dn     TEXT NOT NULL,
    assignee_name   TEXT NOT NULL,
    scope_type      TEXT NOT NULL DEFAULT 'zone',
    scope_dn        TEXT,
    start_time      TIMESTAMPTZ,
    end_time        TIMESTAMPTZ,
    management_state TEXT NOT NULL DEFAULT 'imported_readonly',
    source_hash     TEXT,
    last_synced_at  TIMESTAMPTZ,
    last_seen_in_ad TIMESTAMPTZ,
    deleted_in_ad   BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- UNIX Profilleri
CREATE TABLE centrify_unix_profiles (
    id              SERIAL PRIMARY KEY,
    zone_id         INTEGER NOT NULL REFERENCES centrify_zones(id),
    user_dn         TEXT NOT NULL,
    user_name       TEXT NOT NULL,
    uid             INTEGER,
    gid             INTEGER,
    home_dir        TEXT,
    shell           TEXT,
    gecos           TEXT,
    enabled         BOOLEAN DEFAULT TRUE,
    source_hash     TEXT,
    last_synced_at  TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
```

### 4.2 Operasyonel tablolar

```sql
-- Yazma istekleri kuyruğu (outbox + saga)
CREATE TABLE centrify_operations (
    id              SERIAL PRIMARY KEY,
    correlation_id  UUID NOT NULL DEFAULT gen_random_uuid(),
    zone_id         INTEGER REFERENCES centrify_zones(id),
    operation_type  TEXT NOT NULL,
    desired_state   JSONB NOT NULL,
    observed_state  JSONB,
    status          TEXT NOT NULL DEFAULT 'requested',
    status_history  JSONB DEFAULT '[]',
    saga_id         UUID,
    saga_step       INTEGER DEFAULT 0,
    saga_total      INTEGER DEFAULT 1,
    requested_by    INTEGER NOT NULL,             -- ainew user id (soft ref)
    requested_by_name TEXT NOT NULL,
    approved_by     INTEGER,
    approved_by_name TEXT,
    reason          TEXT NOT NULL,
    error_message   TEXT,
    retry_count     INTEGER DEFAULT 0,
    max_retries     INTEGER DEFAULT 3,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Append-only audit log (UPDATE/DELETE yasak)
CREATE TABLE centrify_audit_log (
    id              SERIAL PRIMARY KEY,
    correlation_id  UUID NOT NULL,
    operation_id    INTEGER REFERENCES centrify_operations(id),
    actor_user_id   INTEGER NOT NULL,
    actor_username  TEXT NOT NULL,
    target_type     TEXT NOT NULL,
    target_ad_guid  UUID,
    target_name     TEXT,
    action          TEXT NOT NULL,
    reason          TEXT NOT NULL,
    details         JSONB,
    approved_by_id  INTEGER,
    approved_by_name TEXT,
    result          TEXT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Drift kayıtları
CREATE TABLE centrify_drift_events (
    id              SERIAL PRIMARY KEY,
    zone_id         INTEGER NOT NULL REFERENCES centrify_zones(id),
    object_type     TEXT NOT NULL,
    object_ad_guid  UUID NOT NULL,
    object_name     TEXT NOT NULL,
    expected_hash   TEXT,
    actual_hash     TEXT,
    drift_details   JSONB,
    resolved        BOOLEAN DEFAULT FALSE,
    resolved_by     INTEGER,
    detected_at     TIMESTAMPTZ DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ
);

-- Entegrasyon ayarları
CREATE TABLE centrify_integration_config (
    id              SERIAL PRIMARY KEY,
    label           TEXT NOT NULL DEFAULT 'Varsayılan',
    -- Windows sunucu (Access Manager)
    winrm_host      TEXT NOT NULL,
    winrm_port      INTEGER DEFAULT 5985,
    winrm_https     BOOLEAN DEFAULT FALSE,
    -- Kimlik
    service_account TEXT NOT NULL,               -- sAMAccountName (service_centrify)
    password_enc    TEXT NOT NULL,               -- CredentialManager ile şifreli
    -- Senkronizasyon
    sync_interval_minutes INTEGER DEFAULT 30,
    sync_enabled    BOOLEAN DEFAULT TRUE,
    enabled         BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
```

### 4.3 management_state

| Değer | Anlam | Uygulama davranışı |
|-------|-------|-------------------|
| `imported_readonly` | İlk sync'te import edildi | Sadece okuma; yazma/silme yasak |
| `managed` | Yönetime alındı | Okuma + yazma + drift tespiti aktif |

İlk import'ta tüm nesneler `imported_readonly`. Yetkili kullanıcı seçerek `managed`'e çevirir.
Uygulama, `managed` olmayan hiçbir nesneyi **değiştirmez veya silmez**.

---

## 5. Senkronizasyon

### 5.1 Okuma yolu: WinRM + PowerShell

Senkronizasyon, Windows sunucuya WinRM ile bağlanıp PowerShell/ADEdit ile zone verilerini
JSON olarak alır ve Centrify DB'ye yazar.

### 5.2 Senkronizasyon stratejisi

| Tip | Tetik | Kapsam |
|-----|-------|--------|
| Tam tarama | Periyodik (varsayılan 30 dk) | Tüm zone'lar |
| Hedefli yenileme | Yazma sonrası | Etkilenen nesne + bağımlıları |
| Manuel tetik | UI butonu veya API | Seçili zone veya tümü |

Değişiklik tespiti: `source_hash = sha256(canonical_attributes)`.
Senkron işi idempotent ve sayfalı çalışır.

### 5.3 Drift tespiti

`managed` nesnelerde AD'deki gerçek durum ile istenen durum karşılaştırılır.
Fark varsa alarm + UI'da gösterim. Otomatik düzeltme varsayılan olarak kapalı.

---

## 6. Durum Makinesi

Her yazma isteği tek durum makinesinden geçer:

```
requested → pending_approval → approved → provisioning
  → written_to_ad → verified → completed

Hata dalları: failed | ambiguous | cancelled | rolled_back
```

Geçiş kuralları `state_machine.py`'de tek modülde tanımlı. Geçersiz geçişler reddedilir.

AD replikasyonu ve agent önbelleği yüzünden etkinleşme dakikalar sürebilir —
UI "verildi" yerine gerçek durumu gösterir.

Süreli atamalarda `start_time`/`end_time` AD'deki alanlarla eşlenir;
Celery beat bitişi izler ve temizlik işi çalıştırır.

---

## 7. API Tasarımı

Prefix: `/api/v1/centrify-mgmt`

### 7.1 Salt okunur

```
GET  /zones                           → zone ağacı (lazy: depth=1)
GET  /zones/{id}                      → zone detay
GET  /zones/{id}/children             → alt zone'lar
GET  /zones/{id}/computers            → computer listesi (sayfalı)
GET  /zones/{id}/roles                → rol listesi
GET  /zones/{id}/commands             → komut/right listesi
GET  /zones/{id}/computer-roles       → computer role listesi
GET  /zones/{id}/role-assignments     → role assignment listesi
GET  /zones/{id}/unix-profiles        → UNIX profil listesi
GET  /zones/{id}/drift                → drift event'leri
GET  /computers/{id}                  → computer detay + UNIX data
GET  /roles/{id}                      → rol detay + bağlı komutlar
GET  /roles/{id}/diff/{other_id}      → iki rol arasındaki fark (kopyala/overwrite için)
GET  /sync/status                     → son sync durumu
POST /sync/trigger                    → manuel sync tetikle
```

### 7.2 Yazma

```
POST   /operations                    → yeni işlem isteği
GET    /operations                    → işlem listesi (filtre, sayfa)
GET    /operations/{id}               → işlem detay + durum geçmişi
POST   /operations/{id}/approve       → onayla
POST   /operations/{id}/reject        → reddet
POST   /operations/{id}/retry         → yeniden dene (failed/ambiguous)
POST   /operations/{id}/cancel        → iptal et

POST   /roles/clone                   → rol kopyala (komutlarıyla)
POST   /roles/overwrite               → rol üzerine yaz (diff önizlemeli)
```

### 7.3 Yönetim

```
GET    /config                        → entegrasyon ayarları
PUT    /config                        → ayar güncelle
POST   /config/test-connection        → WinRM bağlantı testi
POST   /config/reset-circuit          → circuit breaker reset (admin)
GET    /audit                         → audit log (filtre, sayfa)
GET    /circuit-status                → circuit breaker durumu
```

### 7.4 AI Asistan

```
POST   /centrify-chat/stream          → SSE stream (Centrify asistanı)
GET    /centrify-chat/history         → sohbet geçmişi
```

---

## 8. Frontend — Kullanıcı Dostu Arayüz

### 8.1 Navigasyon

`Layout.tsx` → Level 1 grubu altına link eklenir.
`App.tsx` → `/level1/centrify/*` rotası `RequireModule moduleId="centrify"` ile.

### 8.2 Ana sayfa yapısı

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Centrify Zone Yönetimi                        [↻ Sync] [⚙ Ayarlar]   │
├────────────────┬────────────────────────────────────────────────────────┤
│                │                                                        │
│  ZONE AĞACI    │  Zone-Prod › Roles                                     │
│  (sol panel)   │                                                        │
│                │  ┌──────────┐ ┌──────────┐ ┌────────────────┐         │
│  ▼ Zone-Prod   │  │ + Yeni   │ │ Kopyala  │ │ Filtrele...    │         │
│    ├ Roles     │  └──────────┘ └──────────┘ └────────────────┘         │
│    ├ Commands  │                                                        │
│    ├ Comp.Roles│  ┌─────────────────────────────────────────────────┐   │
│    ├ Assign.   │  │  ☐  sysadmin              5 komut      │ ⋮ │   │   │
│    └ UNIX Data │  │  ☐  dba-oracle             8 komut      │ ⋮ │   │   │
│  ▶ Zone-Test   │  │  ☐  app-deploy              3 komut      │ ⋮ │   │   │
│  ▶ Zone-Dev    │  │  ☐  readonly                0 komut      │ ⋮ │   │   │
│                │  └─────────────────────────────────────────────────┘   │
│  ── Durum ──   │                                                        │
│  ● Bağlı       │  Seçili: 0 rol                                        │
│  Son sync:     │                                                        │
│  2 dk önce     │                                                        │
│  Drift: 0      │                                                        │
├────────────────┴────────────────────────────────────────────────────────┤
│  İşlemler (daraltılabilir)                                         [▼] │
│  #124 create_role "backup-admin" │ ⏳ onay bekliyor │ ahmet │ 3dk önce │
└─────────────────────────────────────────────────────────────────────────┘
```

### 8.3 Sağ tık / ⋮ menüsü (rol satırı)

| Aksiyon | Açıklama |
|---------|----------|
| Düzenle | Rol adı, açıklama, komutları değiştir |
| Kopyala | Tüm komutlarıyla klonla; hedef zone + yeni ad seçimi |
| Komutları Al | Başka rolün komutlarını bu role import et (merge) |
| Komutları Ver | Bu rolün komutlarını seçili role export et |
| Overwrite | Başka rolün komutlarıyla üzerine yaz — diff önizlemesi + etkilenen kullanıcı uyarısı |
| Atamaları Gör | Bu role atanmış kullanıcı/gruplar |
| Sil | Onay diyaloğu + bağımlılık uyarısı |

### 8.4 Rol düzenleme paneli

Sağ panelde veya modal olarak açılır:

- Rol adı + açıklama formu
- Komut listesi (tablo: path, çalıştıran, auth, düzenle/sil butonları)
- "Başka rolden kopyala" dropdown'u
- Atama listesi (kullanıcı/grup/computer role + kapsam + düzenle/sil)
- **Değişiklik önizleme** (diff): eklenen/silinen/değişen komutlar + etkilenen kullanıcı sayısı
- Zorunlu gerekçe alanı
- Kaydet + Onayla butonu

### 8.5 Kopyalama diyaloğu

- Kaynak rol + komut sayısı
- Yeni ad (text input)
- Hedef zone (dropdown)
- Komutları kopyala (checkbox, varsayılan açık)
- Atamaları da kopyala (checkbox, varsayılan kapalı)

### 8.6 Overwrite diyaloğu

- Kaynak rol → hedef rol
- Diff listesi (eklenen/silinen/aynı kalan komutlar, renkli)
- Etkilenen kullanıcı/grup uyarısı
- Zorunlu gerekçe alanı
- "Üzerine Yaz" butonu (onay gerektirir)

### 8.7 AI Asistan paneli

Sayfanın sağ alt köşesinde FAB (Floating Action Button) veya ayrı bir panel.
Yalnızca Centrify sayfasında görünür.

Örnek sorgular:
- "oracle kullanıcısına /usr/sbin/reboot için dzdo yetkisi nasıl verilir?"
- "sysadmin rolüne benzer bir rol var mı?"
- "bu komut zaten tanımlı mı?"

Asistan cevap verirken Centrify DB'den mevcut rol/komut/atama bilgilerini context olarak kullanır.

### 8.8 Teknoloji seçimleri

| Bileşen | Seçim | Gerekçe |
|---------|-------|---------|
| UI framework | Tailwind + custom (mevcut) | Tutarlılık |
| Ağaç bileşeni | `@tanstack/react-virtual` + headless tree | Lazy load |
| Tablo | Sunucu tarafı sayfalama + filtreleme | Mevcut pattern |
| Form | React Hook Form + Zod | Şema doğrulama |
| Sunucu durumu | TanStack Query | Mevcut |
| Ağaç durumu | `localStorage` (`ainew.centrify-tree-state`) | Convention |

### 8.9 i18n

- UI fiillerini çevir: "Oluştur", "Sil", "Onayla", "Kopyala", "Üzerine Yaz"
- Teknik adları çevirme: Zone, Role, Right, Command, Computer Role, Assignment, UNIX Profile

---

## 9. Centrify AI Asistanı

### 9.1 Amaç

Kullanıcının Centrify ile ilgili sorularına cevap veren, mevcut verilere dayanarak
önerilerde bulunan, sayfaya özel bir asistan.

### 9.2 RAG kaynakları

- Delinea resmi dokümanları (ADEdit komut referansı, zone kavramları, best practice)
- Server Suite zone model açıklamaları
- Komut/right/role tanımlama kılavuzları
- pgvector'e ingest edilir

### 9.3 Context (her soruda DB'den)

- Mevcut zone listesi
- Seçili zone'daki roller ve komutlar
- Mevcut role assignment'lar
- Kullanıcının yetkili olduğu zone'lar

### 9.4 Tool'lar (READ-ONLY)

| Tool | Açıklama |
|------|----------|
| `search_roles` | Rol adı/açıklama ile arama |
| `search_commands` | Komut path/ad ile arama |
| `search_assignments` | Kullanıcı/grup bazlı atama arama |
| `check_user_permissions` | Kullanıcının mevcut yetkilerini kontrol et |
| `compare_roles` | İki rolün komut farkını göster |

### 9.5 Altyapı

ainew mevcut AI altyapısı (`REMOTE_LLM` veya Ollama). Ayrı model gerekmez.
Endpoint: `/api/v1/centrify-chat/stream` (SSE).

---

## 10. Güvenlik (Tier 0'a Yakın)

### 10.1 Kimlik doğrulama

ainew mevcut JWT auth. Ayrı SSO kurulmaz.

### 10.2 WinRM güvenliği

- `service_centrify` + şifre ile NTLM auth.
- Şifre `CredentialManager` ile şifreli saklanır.
- Circuit breaker: 2 auth fail → tüm işlemler durur.
- Auth hatalarında retry **yasak**.

### 10.3 Komut/right tanımlama güvenliği (en riskli)

- Şablon + beyaz liste
- Joker karakter kısıtları
- `run_as` kullanıcı sınırı
- Zorunlu ikinci onaylayıcı (dört göz)
- Diff önizlemesi

### 10.4 İzolasyon

| Katman | Mekanizma |
|--------|-----------|
| DB | Ayrı Postgres container (:5434) |
| Celery | Ayrı queue (`-Q centrify`) |
| Redis | `centrify:` prefix |
| Exception | Kendi exception hierarchy'si |
| API | Router yüklenemezse ainew çalışmaya devam eder |
| Circuit | Auth fail → Centrify devre dışı; ainew çalışır |

### 10.5 Ağ

ainew'den → Windows sunucu: WinRM (5985 veya 5986)
ainew'den doğrudan DC'lere bağlantı **yoktur**.

### 10.6 Sırlar

- Şifre `CredentialManager` (AES/Fernet) ile şifreli.
- WinRM çıktısında şifre maskelenir.
- Kod, imaj ve loglarda sır olmasın.

---

## 11. Gözlemlenebilirlik

### 11.1 Prometheus metrikleri (Pushgateway'e)

| Metrik | Tip |
|--------|-----|
| `centrify_sync_duration_seconds` | histogram |
| `centrify_sync_last_success_timestamp` | gauge |
| `centrify_operations_total` | counter (status label) |
| `centrify_queue_depth` | gauge |
| `centrify_drift_active` | gauge |
| `centrify_winrm_errors_total` | counter (class label) |
| `centrify_circuit_open` | gauge (0/1) |

### 11.2 Alarmlar

- Sync 2 × interval boyunca çalışmadıysa → uyarı
- Drift > 0 → uyarı
- Circuit açık → kritik alarm
- Kuyruk derinliği sürekli artıyorsa → uyarı

---

## 12. Entegrasyonlar Sayfası

`integrations.py` → `sources` listesine:
```python
{"id": "centrify", "name": "Delinea Server Suite",
 "description": "Centrify zone, role, right, assignment yönetimi",
 "count": active_zone_count, "enabled": config_exists_and_enabled,
 "path": "/level1/centrify"}
```

**Yapılandırma formu (4 alan):**
- Windows sunucu IP/hostname (Access Manager)
- WinRM portu (varsayılan 5985)
- Kullanıcı adı (`service_centrify`)
- Şifre

"Test" butonu: WinRM bağlantısı + ADEdit varlık kontrolü + zone listesi okuma.
Başarılıysa Level 1 menüsünde "Centrify" linki görünür.

---

## 13. Aşamalı Teslim Planı

| Faz | İçerik | Değer |
|-----|--------|-------|
| 0 | Spike: WinRM + ADEdit/PowerShell doğrulama | Teknik fizibilite |
| 1 | Salt okunur: DB + sync + ağaç + listeler + drift | Görünürlük |
| 2 | Yazma: Durum makinesi + kuyruk + audit + onay + assignment | Temel operasyon |
| 3 | Rol yönetimi: CRUD + kopyala + overwrite + diff | Verimlilik |
| 4 | Komut/right: Şablon + beyaz liste + zorunlu onay | Tam yetki yönetimi |
| 5 | AI asistanı: RAG + chat endpoint | Kullanıcı desteği |
| 6 | Sertleştirme: Yük testi, alarm, runbook | Üretime hazırlık |

---

## 14. Mevcut Altyapıyla İlişki Haritası

| ainew bileşeni | Kullanımı |
|----------------|-----------|
| `backend/app/services/windows/winrm_client.py` | WinRM bağlantısı (doğrudan kullanılır) |
| `backend/app/worker.py` (Celery) | Sync + provisioning task'ları |
| `backend/app/services/fleet_mutex.py` | Zone bazlı Redis kilit |
| `backend/app/api/integrations.py` | Sources listesine ekleme |
| `backend/app/models/module.py` | Yeni modül tanımı |
| `backend/app/core/encryption.py` | Şifre şifreleme (CredentialManager) |
| `dropt/.../centrify_store.py` | hostname join/leave — **ayrı kalır, dokunulmaz** |
| `frontend/src/components/Layout.tsx` | Navigasyon linki |
| `frontend/src/i18n/messages.ts` | Çeviri anahtarları |
| Pushgateway `:9091` | Metrik gönderimi |
