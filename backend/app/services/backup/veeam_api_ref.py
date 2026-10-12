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
  4. Immutability (hardened repository / object lock): ``repositories/states``
     yanıtında yok; ``GET /backupInfrastructure/repositories/{id}`` alanları
     okunmadı → ``BkRepository.immutable`` Dilim D'de DOLDURULMAZ.
  5. ``sessions`` (liste) yanıtında işlenen/aktarılan bayt yok; ``jobs/states``
     ``sessionProgress.processedSize`` birimi (bayt?) belirtilmemiş → değişim
     hızı (change_rate) bulgusu Dilim E'ye bırakıldı.
  6. ``serverInfo`` yalnız "Veeam Backup Administrator" rolüne açık
     (Backup Viewer 403 alır): sürüm tespiti Viewer ile yapılamaz; kullanıcı
     ``api_revision`` seçer. Revizyon uyumsuzluğunda VBR'nin hangi HTTP kodunu
     döndüğü dokümanda yazmıyor → otomatik revizyon müzakeresi KODLANMADI.
  7. Naive (saat dilimi yok) zaman damgaları (ör. SureBackup örnekleri) için
     saat dilimi belirtilmemiş; UTC varsayılır.
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
             ("name", "buildVersion", "platform")),
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
)}

# İstemcinin YAZMA yapabileceği tek yollar (auth). Diğer her şey yalnız GET.
AUTH_WRITE_PATHS = ("/api/oauth2/token", "/api/oauth2/logout")


def doc_url(key: str) -> str:
    return f"{REFERENCE_BASE}{ENDPOINTS[key].doc_tag}/index.html"
