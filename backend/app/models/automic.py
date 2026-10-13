"""Automic (UC4) modülü ORM modelleri.

Ayrı Automic modül DB'sinde (:5435) yaşar — ainew ana DB'yle karıştırılmaz.
Hypertable olan tablolarda zaman kolonu birincil anahtarın parçasıdır (Timescale şartı).
"""
from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

from app.services.automic.database import AutomicBase


class AutomicSystem(AutomicBase):
    """Bağlı AE sistemi (ör. PROD, TEST) ve veri kaynağı yapılandırması."""
    __tablename__ = "automic_systems"

    id = Column(Integer, primary_key=True)
    name = Column(String(64), nullable=False, unique=True)
    is_default = Column(Boolean, default=False, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    source_type = Column(String(32), nullable=False, default="db_oracle")
    connection = Column(JSONB, nullable=False, default=dict)   # host, port, service_name, dsn, user, tcps, driver_mode
    secret_enc = Column(Text, nullable=True)                    # encrypt_secret(şifre)
    clients = Column(JSONB, nullable=False, default=list)       # izlenen client numaraları
    settings = Column(JSONB, nullable=False, default=dict)      # toplama, koruma, saklama, kota, sınıflandırma, maskeleme
    capability = Column(JSONB, nullable=True)                   # keşif sonucu yetenek matrisi
    capability_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AutomicRunIdHourMap(AutomicBase):
    """Saat başına min/max AH_Idnr (aktivasyon zamanına göre) — zaman sorgularını PK'ye çevirir."""
    __tablename__ = "automic_runid_hour_map"

    system_id = Column(Integer, primary_key=True)
    hour_utc = Column(DateTime(timezone=True), primary_key=True)  # saat dilimi başı UTC
    min_run_id = Column(BigInteger, nullable=False)
    max_run_id = Column(BigInteger, nullable=False)
    sample_count = Column(Integer, default=0, nullable=False)


class AutomicCollectorState(AutomicBase):
    __tablename__ = "automic_collector_state"

    system_id = Column(Integer, primary_key=True)
    watermark = Column(DateTime(timezone=True), nullable=True)        # bitiş zamanı su seviyesi (UTC)
    backfill_from = Column(DateTime(timezone=True), nullable=True)
    backfill_cursor = Column(DateTime(timezone=True), nullable=True)  # geriye doğru (eski zaman imleci; legacy)
    backfill_run_id_cursor = Column(BigInteger, nullable=True)        # AH_Idnr geriye doğru imleç
    backfill_done = Column(Boolean, default=False, nullable=False)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    last_success_at = Column(DateTime(timezone=True), nullable=True)
    next_run_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)
    last_rows = Column(Integer, default=0)
    last_duration_sec = Column(Float, default=0)
    source_lag_sec = Column(Float, nullable=True)
    source_lag_method = Column(String(32), nullable=True)
    source_latest_at = Column(DateTime(timezone=True), nullable=True)
    active_snapshot_at = Column(DateTime(timezone=True), nullable=True)
    jpp_oh_id_cursor = Column(BigInteger, nullable=True)              # JPP senkron OH_Idnr imleci
    jpp_synced_at = Column(DateTime(timezone=True), nullable=True)    # son tam JPP turu
    script_oh_id_cursor = Column(BigInteger, nullable=True)           # OT script senkron OH_Idnr imleci
    script_synced_at = Column(DateTime(timezone=True), nullable=True)
    users_oh_id_cursor = Column(BigInteger, nullable=True)            # USER senkron OH_Idnr imleci
    users_synced_at = Column(DateTime(timezone=True), nullable=True)
    infra_synced_at = Column(DateTime(timezone=True), nullable=True)  # HOST/MQSRV/OHG son senkron
    infra_source_now = Column(DateTime(timezone=True), nullable=True)  # kaynak MQSRV max LastUpdate
    infra_warning = Column(Text, nullable=True)                       # küçük tablo eşik vb.
    reconcile_at = Column(DateTime(timezone=True), nullable=True)     # son mutabakat turu
    source_min_by_client = Column(JSONB, nullable=True)               # legacy (kullanılmıyor)
    # client → son okunan/yazılan max AH_Idnr (RunID watermark)
    run_id_watermark_by_client = Column(JSONB, nullable=True)
    ingest_paused_reason = Column(String(64), nullable=True)          # ör. quota_critical
    # Adım imleçleri (refresh, resync…) + adım bazında son süre/bütçe + bütçe aşımı toplamları
    step_state = Column(JSONB, nullable=True)


class AutomicCollectorRun(AutomicBase):
    """Collector turu geçmişi — entegrasyon sağlığı widget'ı için (7 gün)."""
    __tablename__ = "automic_collector_runs"

    id = Column(BigInteger, primary_key=True)
    system_id = Column(Integer, nullable=False, index=True)
    kind = Column(String(16), nullable=False, default="incremental")  # incremental|backfill|active|discovery
    started_at = Column(DateTime(timezone=True), nullable=False, index=True)
    duration_sec = Column(Float, default=0)
    rows = Column(Integer, default=0)
    failed_rows = Column(Integer, default=0)
    reports = Column(Integer, default=0)
    source_lag_sec = Column(Float, nullable=True)
    error = Column(Text, nullable=True)
    step_metrics = Column(JSONB, nullable=True)   # {adım: {duration_sec, budget_sec, overrun, items, error}}


class AutomicDataGap(AutomicBase):
    """Kaynakta artık bulunmayan / boşluk RunID aralığı (reorg veya kaçırılan toplama)."""
    __tablename__ = "automic_data_gaps"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    system_id = Column(Integer, nullable=False, index=True)
    client = Column(Integer, nullable=True)
    id_min = Column(BigInteger, nullable=False)
    id_max = Column(BigInteger, nullable=False)
    reason = Column(String(64), nullable=False, default="missing_in_source")
    detail = Column(Text, nullable=True)
    detected_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_automic_gaps_sys", "system_id", "detected_at"),
    )


class AutomicReconcileReport(AutomicBase):
    """Saatlik kaynak ↔ modül DB mutabakat özeti."""
    __tablename__ = "automic_reconcile_reports"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    system_id = Column(Integer, nullable=False, index=True)
    hour_utc = Column(DateTime(timezone=True), nullable=False)
    source_count = Column(Integer, nullable=False, default=0)
    module_count = Column(Integer, nullable=False, default=0)
    diff_pct = Column(Float, nullable=True)
    id_min = Column(BigInteger, nullable=True)
    id_max = Column(BigInteger, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_automic_reconcile_sys_hour", "system_id", "hour_utc", unique=True),
    )


class AutomicExecution(AutomicBase):
    """Biten çalışmalar. Hypertable / PK zaman kolonu: activation_time (değişmez)."""
    __tablename__ = "automic_executions"

    system_id = Column(Integer, primary_key=True)
    client = Column(Integer, primary_key=True)
    run_id = Column(BigInteger, primary_key=True)
    activation_time = Column(DateTime(timezone=True), primary_key=True)
    end_time = Column(DateTime(timezone=True), nullable=False, index=True)
    parent_run_id = Column(BigInteger, nullable=True)
    top_run_id = Column(BigInteger, nullable=True)
    restart_ref_run_id = Column(BigInteger, nullable=True)
    object_name = Column(String(200), nullable=False)
    object_type = Column(String(16), nullable=True)
    folder = Column(String(400), nullable=True)
    status_code = Column(Integer, nullable=True)
    status_class = Column(String(16), nullable=False, default="other")
    start_time = Column(DateTime(timezone=True), nullable=True)
    duration_sec = Column(Float, nullable=True)
    agent = Column(String(200), nullable=True)         # fiili agent (AH_HostDst; grup çözülmüşse)
    agent_group = Column(String(200), nullable=True)   # AH_HGDst — tanımda atanan grup
    agent_assigned = Column(String(200), nullable=True)  # tanımda atanan (grup veya agent)
    platform = Column(String(32), nullable=True)
    queue = Column(String(200), nullable=True)
    user = Column(String(200), nullable=True)          # görüntüleme (join ile güncellenir; legacy)
    user_idnr = Column(BigInteger, nullable=True)      # AH_USR_Idnr (= OH_Idnr varsayımı; doğrulanacak)
    user_name_at_run = Column(String(200), nullable=True)  # toplama anındaki OH_Name
    return_code = Column(Integer, nullable=True)
    run_time_sec = Column(Integer, nullable=True)      # AH_RunTime (saniye)
    ert_sec = Column(Integer, nullable=True)           # AH_ERT — AE'nin tahmini çalışma süresi (saniye)

    __table_args__ = (
        Index("ix_automic_exec_obj", "system_id", "client", "object_name", "end_time"),
        Index("ix_automic_exec_class", "system_id", "status_class", "end_time"),
        Index("ix_automic_exec_run", "system_id", "run_id"),
        Index("ix_automic_exec_parent", "system_id", "parent_run_id"),
        Index("ix_automic_exec_user", "system_id", "client", "user_idnr"),
        Index("ix_automic_exec_end", "system_id", "end_time"),
    )


class AutomicActiveExecution(AutomicBase):
    """Kaynaktaki aktif çalışmaların son anlık görüntüsü (EH)."""
    __tablename__ = "automic_active"

    system_id = Column(Integer, primary_key=True)
    client = Column(Integer, primary_key=True)
    run_id = Column(BigInteger, primary_key=True)
    parent_run_id = Column(BigInteger, nullable=True)
    object_name = Column(String(200), nullable=False)
    object_type = Column(String(16), nullable=True)
    status_code = Column(Integer, nullable=True)
    status_class = Column(String(16), nullable=False, default="active")
    activation_time = Column(DateTime(timezone=True), nullable=True)
    start_time = Column(DateTime(timezone=True), nullable=True)
    agent = Column(String(200), nullable=True)
    agent_group = Column(String(200), nullable=True)
    agent_assigned = Column(String(200), nullable=True)
    snapshot_at = Column(DateTime(timezone=True), nullable=False)
    # Resmi EH kolonları (EH_USR_Idnr, EH_Queue, EH_HostAttrType, EH_Ert, EH_ERTEnd, EH_ERTCalc, EH_Signal ...)
    top_run_id = Column(BigInteger, nullable=True)
    folder = Column(String(400), nullable=True)
    platform = Column(String(32), nullable=True)
    queue = Column(String(200), nullable=True)
    user = Column(String(200), nullable=True)
    user_idnr = Column(BigInteger, nullable=True)
    user_name_at_run = Column(String(200), nullable=True)
    run_time_sec = Column(Integer, nullable=True)      # EH_RunTime
    ert_sec = Column(Integer, nullable=True)           # EH_Ert — tahmini çalışma süresi
    ert_end_time = Column(DateTime(timezone=True), nullable=True)  # EH_ERTEnd — tahmini bitiş
    ert_calc = Column(Integer, nullable=True)          # EH_ERTCalc: 0 yok, 1 hesaplanıyor, 2 başarılı, 3 başarısız
    signal = Column(Integer, nullable=True)            # EH_Signal bitmask: 1 TCP, 2 MRT, 4 SRT
    mrt_sec = Column(Integer, nullable=True)           # EH_Mrt
    srt_sec = Column(Integer, nullable=True)           # EH_Srt


class AutomicUser(AutomicBase):
    """AE USER nesnesi (OH OType=USER) — client bazlı; USR tablosu okunmaz."""
    __tablename__ = "automic_users"

    system_id = Column(Integer, primary_key=True)
    client = Column(Integer, primary_key=True)
    user_idnr = Column(BigInteger, primary_key=True)   # OH_Idnr
    name = Column(String(200), nullable=False)         # OH_Name'in / öncesi (veya tamamı)
    department = Column(String(200), nullable=True)    # OH_Name'in / sonrası
    delete_flag = Column(Integer, nullable=True)       # OH_DeleteFlag
    first_seen = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_seen = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    synced_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_automic_users_name", "system_id", "client", "name"),
        Index("ix_automic_users_dept", "system_id", "client", "department"),
    )


class AutomicReportExcerpt(AutomicBase):
    """Hatalı çalışmaların maskelenmiş rapor kırpıntıları. Hypertable: end_time."""
    __tablename__ = "automic_report_excerpts"

    system_id = Column(Integer, primary_key=True)
    client = Column(Integer, primary_key=True)
    run_id = Column(BigInteger, primary_key=True)
    report_type = Column(String(16), primary_key=True)
    end_time = Column(DateTime(timezone=True), primary_key=True)
    content = Column(Text, nullable=False)
    total_lines = Column(Integer, nullable=True)
    truncated = Column(Boolean, default=False)
    error_signature = Column(String(300), nullable=True)
    size_bytes = Column(Integer, default=0)


class AutomicReportAttempt(AutomicBase):
    """Rapor toplama kuyruğu durumu (hatalı çalışma başına): deneme sayısı + son deneme + sonuç.

    status: done (kırpıntı yazıldı) | unavailable (kaynakta rapor yok / deneme hakkı bitti — "rapor alınamadı",
    bir daha denenmez) | error (geçici hata; geri çekilmeyle yeniden denenir).
    """
    __tablename__ = "automic_report_attempts"

    system_id = Column(Integer, primary_key=True)
    client = Column(Integer, primary_key=True)
    run_id = Column(BigInteger, primary_key=True)
    end_time = Column(DateTime(timezone=True), nullable=False)
    attempts = Column(Integer, nullable=False, default=0)
    last_attempt_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(16), nullable=False, default="error")
    last_error = Column(String(300), nullable=True)

    __table_args__ = (
        Index("ix_automic_rep_attempts_status", "system_id", "status", "end_time"),
    )


class AutomicFailedIndex(AutomicBase):
    """Hatalı çalışma indeksi (rapor yok) — 12 ay. Hypertable: day."""
    __tablename__ = "automic_failed_index"

    system_id = Column(Integer, primary_key=True)
    client = Column(Integer, primary_key=True)
    run_id = Column(BigInteger, primary_key=True)
    day = Column(Date, primary_key=True)
    object_name = Column(String(200), nullable=False)
    object_type = Column(String(16), nullable=True)
    agent = Column(String(200), nullable=True)
    status_code = Column(Integer, nullable=True)
    return_code = Column(Integer, nullable=True)
    error_signature = Column(String(300), nullable=True)

    __table_args__ = (Index("ix_automic_fidx_obj", "system_id", "object_name", "day"),)


class AutomicDailyAggregate(AutomicBase):
    """Nesne başına günlük özet — 2 yıl. Hypertable: day."""
    __tablename__ = "automic_daily_aggregates"

    system_id = Column(Integer, primary_key=True)
    client = Column(Integer, primary_key=True)
    day = Column(Date, primary_key=True)
    object_name = Column(String(200), primary_key=True)
    object_type = Column(String(16), nullable=True)
    folder = Column(String(400), nullable=True)
    run_count = Column(Integer, default=0)
    ok_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    cancelled_count = Column(Integer, default=0)
    duration_min = Column(Float, nullable=True)
    duration_avg = Column(Float, nullable=True)
    duration_p95 = Column(Float, nullable=True)
    duration_max = Column(Float, nullable=True)
    first_start = Column(DateTime(timezone=True), nullable=True)
    last_end = Column(DateTime(timezone=True), nullable=True)
    top_error_signature = Column(String(300), nullable=True)
    agents = Column(JSONB, nullable=True)


class AutomicReportCache(AutomicBase):
    """Kaynaktan istendiğinde okunan raporların kısa süreli cache'i (maskeli)."""
    __tablename__ = "automic_report_cache"

    system_id = Column(Integer, primary_key=True)
    client = Column(Integer, primary_key=True)
    run_id = Column(BigInteger, primary_key=True)
    report_type = Column(String(16), primary_key=True)
    content = Column(Text, nullable=False)
    total_lines = Column(Integer, nullable=True)
    truncated = Column(Boolean, default=False)
    fetched_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)


class AutomicObjectHeader(AutomicBase):
    """AE nesne başlığı (OH) — güncel kayıt tutulur."""
    __tablename__ = "automic_object_headers"

    system_id = Column(Integer, primary_key=True)
    client = Column(Integer, primary_key=True)
    object_name = Column(String(200), primary_key=True)
    object_id = Column(BigInteger, nullable=True, index=True)
    object_type = Column(String(16), nullable=True)
    title = Column(String(400), nullable=True)
    folder = Column(String(400), nullable=True)
    archive1 = Column(String(512), nullable=True)      # OH_Archive1
    archive2 = Column(String(512), nullable=True)      # OH_Archive2
    created_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(String(200), nullable=True)
    modified_at = Column(DateTime(timezone=True), nullable=True)
    modified_by = Column(String(200), nullable=True)
    ert_sec = Column(Integer, nullable=True)           # OH_Ert — nesnenin tahmini çalışma süresi (saniye)
    seen_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_automic_oh_type", "system_id", "object_type"),
        Index("ix_automic_oh_mod", "system_id", "modified_at"),
    )


class AutomicObjectUsage(AutomicBase):
    """JPP workflow görev satırları — kaynak OH_Idnr PK aralığıyla senkron; sorgu modül DB'de."""
    __tablename__ = "automic_object_usage"

    system_id = Column(Integer, primary_key=True)
    client = Column(Integer, primary_key=True)
    parent_object_id = Column(BigInteger, primary_key=True)
    line_no = Column(Integer, primary_key=True)
    parent_object_name = Column(String(200), nullable=True)
    child_name = Column(String(200), nullable=False)
    child_type = Column(String(16), nullable=True)
    seen_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_automic_usage_child", "system_id", "client", "child_name"),
        Index("ix_automic_usage_parent_name", "system_id", "client", "parent_object_name"),
    )


class AutomicObjectScriptVersion(AutomicBase):
    """OT script metni — hash ile sürümlenir (istendiğinde alınır)."""
    __tablename__ = "automic_object_script_versions"

    id = Column(BigInteger, primary_key=True)
    system_id = Column(Integer, nullable=False, index=True)
    client = Column(Integer, nullable=False)
    object_name = Column(String(200), nullable=False)
    object_id = Column(BigInteger, nullable=True)
    version_no = Column(Integer, nullable=False)
    content_hash = Column(String(64), nullable=False)
    content = Column(Text, nullable=False)
    line_count = Column(Integer, default=0)
    size_bytes = Column(Integer, default=0)
    fetched_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    source_modified_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_automic_osv_obj", "system_id", "client", "object_name", "version_no"),
        Index("ix_automic_osv_hash", "system_id", "client", "object_name", "content_hash"),
    )


class AutomicAgent(AutomicBase):
    """AE agent (HOST + OH) — altyapı senkronu."""
    __tablename__ = "automic_agents"

    system_id = Column(Integer, primary_key=True)
    name = Column(String(200), primary_key=True)          # OH_Name
    client = Column(Integer, nullable=True)               # OH_Client (0 = sistem)
    oh_idnr = Column(BigInteger, nullable=True, index=True)
    ip = Column(String(64), nullable=True)                # HOST_TcpIpAddr
    hostname_automic = Column(String(256), nullable=True)  # HOST_HostName
    port = Column(Integer, nullable=True)
    os = Column(String(64), nullable=True)                # HOST_HTYP_SW
    hardware = Column(String(64), nullable=True)          # HOST_HTYP_HW
    platform = Column(String(16), nullable=True)          # HOST_HostAttrType
    version = Column(String(270), nullable=True)          # HOST_Version
    host_active = Column(Integer, nullable=True)          # HOST_Active (1=aktif)
    roles = Column(String(256), nullable=True)            # HOST_HostRoles
    last_life_sign = Column(DateTime(timezone=True), nullable=True)  # MQSRV Type=8 LastUpdate
    status = Column(String(16), nullable=False, default="unknown")  # connected|disconnected|unknown|missing
    status_rule = Column(String(120), nullable=True)
    missing_since = Column(DateTime(timezone=True), nullable=True)  # kayıt kayboldu
    synced_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    first_seen = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_seen = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_automic_agents_status", "system_id", "status"),
        Index("ix_automic_agents_platform", "system_id", "platform"),
    )


class AutomicAgentGroup(AutomicBase):
    __tablename__ = "automic_agent_groups"

    system_id = Column(Integer, primary_key=True)
    name = Column(String(200), primary_key=True)
    client = Column(Integer, nullable=True)
    oh_idnr = Column(BigInteger, nullable=True, index=True)
    platform = Column(String(16), nullable=True)          # OHG_HostAttrType
    mode = Column(String(4), nullable=True)               # OHG_Mode
    synced_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    missing_since = Column(DateTime(timezone=True), nullable=True)


class AutomicAgentGroupMember(AutomicBase):
    """OHGF Type=H tek agent üyeliği (filtre satırları ayrıca saklanmaz ilk sürümde)."""
    __tablename__ = "automic_agent_group_members"

    system_id = Column(Integer, primary_key=True)
    group_name = Column(String(200), primary_key=True)
    agent_name = Column(String(200), primary_key=True)
    synced_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_automic_agm_agent", "system_id", "agent_name"),
    )


class AutomicEngineProcess(AutomicBase):
    """MQSRV process (CP/WP/PWP/JWP/JCP/REST) — Type≠8."""
    __tablename__ = "automic_engine_processes"

    system_id = Column(Integer, primary_key=True)
    name = Column(String(64), primary_key=True)           # MQSRV_Name
    process_type = Column(String(16), nullable=False)     # CP|WP|PWP|JWP|JCP|REST
    mqsrv_type = Column(Integer, nullable=False)
    ip = Column(String(64), nullable=True)
    port = Column(Integer, nullable=True)
    node = Column(String(256), nullable=True)             # çözülmüş hostname
    rest_endpoint = Column(String(128), nullable=True)
    connection_count = Column(Integer, nullable=True)
    pwp_connected = Column(Integer, nullable=True)
    last_life_sign = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(16), nullable=False, default="unknown")
    status_rule = Column(String(120), nullable=True)
    missing_since = Column(DateTime(timezone=True), nullable=True)
    synced_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    first_seen = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_seen = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_automic_eng_ip", "system_id", "ip"),
        Index("ix_automic_eng_type", "system_id", "process_type"),
    )


class AutomicInfraStatusSnapshot(AutomicBase):
    """Agent / Engine durum snapshot — 90 gün detay + günlük özet."""
    __tablename__ = "automic_infra_status_snapshots"

    system_id = Column(Integer, primary_key=True)
    kind = Column(String(16), primary_key=True)           # agent|engine
    name = Column(String(200), primary_key=True)
    snapshot_at = Column(DateTime(timezone=True), primary_key=True)
    status = Column(String(16), nullable=False)
    host_active = Column(Integer, nullable=True)
    last_life_sign = Column(DateTime(timezone=True), nullable=True)
    ip = Column(String(64), nullable=True)
    detail = Column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_automic_infra_snap_kind", "system_id", "kind", "snapshot_at"),
    )


class AutomicInfraDailySummary(AutomicBase):
    __tablename__ = "automic_infra_daily_summaries"

    system_id = Column(Integer, primary_key=True)
    kind = Column(String(16), primary_key=True)
    name = Column(String(200), primary_key=True)
    day = Column(Date, primary_key=True)
    samples = Column(Integer, default=0)
    connected_samples = Column(Integer, default=0)
    disconnected_samples = Column(Integer, default=0)
    unknown_samples = Column(Integer, default=0)
    missing_samples = Column(Integer, default=0)
    approx_uptime_pct = Column(Float, nullable=True)


class AutomicHostnameOverride(AutomicBase):
    """Elle hostname / IP eşlemesi — senkronlarda korunur."""
    __tablename__ = "automic_hostname_overrides"

    system_id = Column(Integer, primary_key=True)
    kind = Column(String(16), primary_key=True)           # agent|ip
    key = Column(String(256), primary_key=True)           # agent adı veya IP
    hostname = Column(String(256), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_by = Column(String(200), nullable=True)


class AutomicTeamRule(AutomicBase):
    """Sıralı ekip eşleme kuralları (ilk eşleşen geçerli)."""
    __tablename__ = "automic_team_rules"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    system_id = Column(Integer, nullable=False, index=True)
    priority = Column(Integer, nullable=False, default=100)
    rule_type = Column(String(32), nullable=False)
    # object_exact | folder_prefix | name_pattern | archive_key | user_department | client
    match_value = Column(String(512), nullable=False)
    team = Column(String(200), nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    updated_by = Column(String(200), nullable=True)

    __table_args__ = (
        Index("ix_automic_team_rules_sys", "system_id", "priority"),
    )


class AutomicAwiServer(AutomicBase):
    """Elle tanımlı AWI sunucuları + HTTP sağlık kontrolü."""
    __tablename__ = "automic_awi_servers"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    system_id = Column(Integer, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    url = Column(String(512), nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    last_check_at = Column(DateTime(timezone=True), nullable=True)
    last_status = Column(String(16), nullable=True)       # up|down|unknown
    last_http_code = Column(Integer, nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_automic_awi_sys_name", "system_id", "name", unique=True),
    )
