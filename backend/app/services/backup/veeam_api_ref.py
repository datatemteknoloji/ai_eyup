"""Veeam Backup & Replication REST API — kullanılan endpoint'lerin tek kaynağı.

KURAL (Dilim D API disiplini): Endpoint, alan, auth akışı ve header bilgisi YALNIZ
Veeam Help Center "Veeam Backup & Replication REST API Reference"tan alınır.
Forum/blog/ezber yok. PowerShell yok — yalnız REST.

Referans (VBR 13): https://helpcenter.veeam.com/references/vbr/13/rest/1.3-rev1/tag/<Tag>/index.html
Genel bakış (auth, header, versiyon, sayfalama):
  https://helpcenter.veeam.com/references/vbr/13/rest/1.3-rev1/tag/SectionOverview/index.html

Doğrulama durumu (bu dosya geliştirme zamanında dokümandan okundu: 2026-10-12):
  * Doküman: 1.3-rev1 (VBR 13.0.1.180). Desteklenen revizyonlar: 1.3-rev0/1/2.
    1.1-rev0..2 ve 1.2-rev0/1 "Deprecated"; 1.0-rev* "Unsupported" (aynı sayfa).
  * 12.x (1.1/1.2) için bu endpoint'lerin yanıt alanları AYRI doğrulanmadı.
  * Gerçek bir VBR'den alınmış maskelenmiş yanıt YOK (test ortamında Veeam yok);
    contract testleri DOKÜMAN ÖRNEĞİ fixture'ı kullanır:
    app/tests/fixtures/veeam/vbr_1_3_rev1_doc_examples.json

Belirsiz / kodlanmadı (kullanıcıya sorulacak):
  1. ``backupObjects[].objectId``: doküman örneğinde bir yerde UUID, başka yerde
     VMware moref ("vm-2067"). Moref eşleşmesi yalnız "vm-<sayı>" biçiminde ise
     denenir ve "doğrulanmadı" olarak işaretlenir.
  2. ``restorePoints[]`` yanıtında nesne kimliği alanı yok (yalnız ``name``,
     ``backupId``, ``platformName``). Restore point → VM eşleşmesi ``name`` ile
     yapılır; ``name``'in daima VM adı olduğu dokümanda açık yazmıyor.
  3. ``repositories/states``: ``usedSpaceGB`` + ``freeGB`` > ``capacityGB``
     olabilir (doküman örneği). Doluluk yalnız ``1 - freeGB/capacityGB`` ile
     hesaplanır; ``usedSpaceGB`` kullanılmaz. GB'nin GiB/GB olduğu belirtilmemiş —
     yüzde birimden bağımsız olduğu için sorun değil, bayt değerleri 1024^3 ile
     yaklaşık çevrilir.
  4. Immutability (hardened repository / object lock): F.1'de ``GET
     /backupInfrastructure/repositories`` yanıt şeması okundu: ``type`` enum'unda
     ``LinuxHardened`` ve nesne depolama türleri var, ama immutability
     **açık mı / süre kaç gün** alanı örneklerde YOK → durum daima
     ``not_measurable`` (``BkRepository.immutable`` kullanılmaz; yanıltıcı
     varsayılanı False'tur). ``type`` yalnız bilgi olarak gösterilir.
  5. ``sessions`` (liste) yanıtında işlenen/aktarılan bayt yok;
     ``jobs/states.sessionProgress`` ve ``taskSessions[].progress``
     ``processedSize/readSize/transferredSize`` alanlarının BİRİMİ dokümanda
     yazmıyor (F.1'de yeniden okundu; örnek değerler 21474836480 = 20 GiB gibi
     bayt çağrışımlı ama doğrulanmadı) → ``BkSession.processed_bytes /
     transferred_bytes`` DOLDURULMAZ, change_rate daima ``not_measurable``.
  6. ``serverInfo`` yalnız "Veeam Backup Administrator" rolüne açık
     (Backup Viewer 403 alır): sürüm tespiti Viewer ile yapılamaz; kullanıcı
     ``api_revision`` seçer. Revizyon uyumsuzluğunda VBR'nin hangi HTTP kodunu
     döndüğü dokümanda yazmıyor → otomatik revizyon müzakeresi KODLANMADI.
  7. Naive (saat dilimi yok) zaman damgaları (ör. SureBackup örnekleri) için
     saat dilimi belirtilmemiş; UTC varsayılır.
  8. (F.1) ``jobs[].virtualMachines.includes[]`` ve ``backupObjects[].path``:
     ``hostName`` (vCenter) + ``objectId`` ("vm-45006" biçimi) doküman
     örneğiyle uyumlu; GERÇEK VBR'de hostName'in vCenter FQDN'i mi IP mi
     döndüğü doğrulanmadı → eşleşme anahtarı ``normalize_host(hostName) +
     moref``, "doküman örneğiyle uyumlu, sahada doğrulanmadı" bayrağıyla.
  9. (F.1) ``backupInfrastructure/proxies/states[].hostName`` örnekte "This
     server" (anlamı: backup sunucusunun kendisi) — ham değer gösterilir,
     yorumlanmaz.
 10. (F.1) ``jobs[]`` yanıtında CBT ``vSphere.changedBlockTracking.isEnabled``
     yalnız VMware işlerinde vardır; şifreleme ``storage.storageData.encryption
     .isEnabled``. Alan yoksa/None ise ``not_measurable`` (False sayılmaz).
 11. (F.1) ``backupObjects/{id}/restorePoints``: ``orderColumn`` /
     ``createdAfterFilter`` desteği Backup-Objects sayfasından alındı; sürüm
     1.3-rev1 dışında doğrulanmadı.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

REFERENCE_BASE = "https://helpcenter.veeam.com/references/vbr/13/rest/1.3-rev1/tag/"
DOC_VERIFIED_REVISION = "1.3-rev1"   # dokümanın okunduğu revizyon (VBR 13.0.1.180)
DEFAULT_PORT = 9419                    # SectionOverview → Resource URLs
DEFAULT_REVISION = "1.3-rev1"

# SectionOverview → "REST API Revisions" tablosu (destek durumu)
REVISIONS: Dict[str, Tuple[str, str]] = {
    "1.3-rev2": ("supported", "13.1.0.TBD"),
    "1.3-rev1": ("supported", "13.0.1.180"),
    "1.3-rev0": ("supported", "13.0.0.4967"),
    "1.2-rev1": ("deprecated", "12.3.1.1139"),
    "1.2-rev0": ("deprecated", "12.3.0.310"),
    "1.1-rev2": ("deprecated", "12.2.0.334"),
    "1.1-rev1": ("deprecated", "12.1.0.2131"),
    "1.1-rev0": ("deprecated", "12.0.0.1420"),
}


@dataclass(frozen=True)
class Endpoint:
    key: str
    method: str
    path: str
    doc_tag: str          # REFERENCE_BASE + doc_tag
    roles_ok: str         # dokümandaki "Available to" (Viewer dahil mi)
    verified: str         # doğrulama durumu
    fields_used: Tuple[str, ...]
    viewer_ok: bool = True   # dokümandaki "Available to" listesinde Backup Viewer var mı (F.1)


_V = "doküman 1.3-rev1 okundu; gerçek VBR yanıtı doğrulanmadı"

ENDPOINTS: Dict[str, Endpoint] = {e.key: e for e in (
    # Token — Overview → "Requesting Authorization" (grant_type=password; x-www-form-urlencoded)
    Endpoint("token", "POST", "/api/oauth2/token", "SectionOverview", "herkes (kimlik doğrulama)", _V,
             ("access_token", "refresh_token", "expires_in")),
    # Logout — Overview → "Performing Logout"
    Endpoint("logout", "POST", "/api/oauth2/logout", "SectionOverview", "oturum sahibi", _V, ()),
    # Get Backup Server Time — Service tag; "Available to: Anyone"
    Endpoint("server_time", "GET", "/api/v1/serverTime", "Service", "Anyone", _V, ("serverTime",)),
    # Get Backup Server Information — Service tag; YALNIZ Veeam Backup Administrator
    Endpoint("server_info", "GET", "/api/v1/serverInfo", "Service", "Backup Administrator (Viewer 403)", _V,
             ("name", "buildVersion", "platform"), viewer_ok=False),
    # Get All Job States — Jobs tag; Viewer dahil
    Endpoint("jobs_states", "GET", "/api/v1/jobs/states", "Jobs", "Admin/Operator/Restore Op./Viewer/Tape/Security", _V,
             ("id", "name", "type", "status", "lastResult", "lastRun", "nextRun", "nextRunPolicy",
              "repositoryId", "repositoryName", "objectsCount", "sessionId")),
    # Get All Repository States — Repositories tag; Viewer dahil
    Endpoint("repositories_states", "GET", "/api/v1/backupInfrastructure/repositories/states", "Repositories",
             "Admin/Operator/Restore Op./Viewer/Tape", _V,
             ("id", "name", "type", "capacityGB", "freeGB", "isOnline")),
    # Get All Sessions — Sessions tag; Viewer dahil; filtreler: createdAfterFilter, typeFilter, orderColumn, orderAsc
    Endpoint("sessions", "GET", "/api/v1/sessions", "Sessions", "Admin/Operator/Restore Op./Viewer/Tape/Security", _V,
             ("id", "name", "sessionType", "state", "jobId", "creationTime", "endTime", "result.result", "result.message")),
    # Get All Backups — Backups tag; Viewer dahil
    Endpoint("backups", "GET", "/api/v1/backups", "Backups", "Admin/Operator/Restore Op./Viewer/Tape/Security", _V,
             ("id", "jobId", "jobType", "name", "platformName", "repositoryId")),
    # Get All Backup Objects — Backup Objects tag; Viewer dahil
    Endpoint("backup_objects", "GET", "/api/v1/backupObjects", "Backup-Objects",
             "Admin/Operator/Restore Op./Viewer/Tape/Security", _V,
             ("id", "name", "type", "platformName", "objectId", "path", "restorePointsCount")),
    # Get All Restore Points — Restore Points tag; Viewer dahil; filtreler: createdAfterFilter, platformNameFilter
    Endpoint("restore_points", "GET", "/api/v1/restorePoints", "Restore-Points",
             "Admin/Operator/Restore Op./Viewer/…", _V,
             ("id", "name", "platformName", "type", "creationTime", "backupId")),
    # ── F.1 (doküman 1.3-rev1 okundu: 2026-10-13) ─────────────────────────────
    # Get All Jobs — Jobs tag; Available to: Admin, Operator, Restore Op., Viewer, Tape Op., Security Admin.
    # Yanıt modeli: iş yapılandırması (storage.retentionPolicy/gfsPolicy/storageData.encryption,
    # vSphere.changedBlockTracking, guestProcessing.appAwareProcessing, schedule.retry/backupWindow/…).
    Endpoint("jobs", "GET", "/api/v1/jobs", "Jobs", "Admin/Operator/Restore Op./Viewer/Tape/Security", _V,
             ("id", "name", "type", "isDisabled", "virtualMachines.includes[].hostName/name/type",
              "storage.backupRepositoryId", "storage.retentionPolicy.type/quantity",
              "storage.gfsPolicy.isEnabled", "storage.advancedSettings.backupHealth.isEnabled",
              "storage.advancedSettings.storageData.encryption.isEnabled",
              "storage.advancedSettings.vSphere.changedBlockTracking.isEnabled",
              "guestProcessing.appAwareProcessing.isEnabled",
              "schedule.runAutomatically", "schedule.daily/monthly/periodically/continuously.isEnabled",
              "schedule.retry.isEnabled/retryCount/awaitMinutes", "schedule.backupWindow.isEnabled")),
    # Get All Proxy States — Proxies tag; Available to: Admin, Operator, Restore Op., Viewer, Tape Op.
    Endpoint("proxies_states", "GET", "/api/v1/backupInfrastructure/proxies/states", "Proxies",
             "Admin/Operator/Restore Op./Viewer/Tape", _V,
             ("id", "name", "type", "hostName", "isDisabled", "isOnline", "isOutOfDate")),
    # Get All Proxies — Proxies tag; Available to: Admin, Operator, Restore Op., Viewer, Tape Op.
    Endpoint("proxies", "GET", "/api/v1/backupInfrastructure/proxies", "Proxies",
             "Admin/Operator/Restore Op./Viewer/Tape", _V,
             ("id", "name", "type", "server.transportMode", "server.maxTaskCount")),
    # Get All Repositories — Repositories tag; Available to: Admin, Operator, Restore Op., Viewer, Tape Op.
    # Immutability alanı örnek yanıtlarda YOK (bkz. belirsizlik #4) → yalnız type okunur.
    Endpoint("repositories", "GET", "/api/v1/backupInfrastructure/repositories", "Repositories",
             "Admin/Operator/Restore Op./Viewer/Tape", _V, ("id", "name", "type", "description")),
    # Get Restore Points of Backup Object — Backup-Objects tag (yol parametresi {id} = backupObjects[].id)
    Endpoint("object_restore_points", "GET", "/api/v1/backupObjects/{id}/restorePoints", "Backup-Objects",
             "Admin/Operator/Restore Op./Viewer/Tape", _V,
             ("id", "type", "creationTime", "backupId")),
)}

# Rol tablosu (F.1): hangi endpoint Viewer'a açık? UI "ölçülemedi (yetki)" ayrımı için TEK kaynak.
ENDPOINT_ROLE_ROWS = tuple((e.key, e.path, e.roles_ok, e.viewer_ok) for e in ENDPOINTS.values())


def viewer_closed_keys() -> Tuple[str, ...]:
    """Backup Viewer ile 403 alınacak endpoint anahtarları (doküman 'Available to')."""
    return tuple(e.key for e in ENDPOINTS.values() if not e.viewer_ok)


# İstemcinin YAZMA yapabileceği tek yollar (auth). Diğer her şey yalnız GET.
AUTH_WRITE_PATHS = ("/api/oauth2/token", "/api/oauth2/logout")


def doc_url(key: str) -> str:
    return f"{REFERENCE_BASE}{ENDPOINTS[key].doc_tag}/index.html"
