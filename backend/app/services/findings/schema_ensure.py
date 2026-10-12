"""Mevcut DB'ye Dilim B kolonlarını ekler (create_all ALTER yapmaz)."""
from __future__ import annotations

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)


def ensure_infra_finding_columns(engine) -> None:
    stmts = [
        "ALTER TABLE infra_findings ADD COLUMN IF NOT EXISTS stale boolean NOT NULL DEFAULT false",
        "ALTER TABLE infra_findings ADD COLUMN IF NOT EXISTS data_age_sec double precision",
        "ALTER TABLE infra_findings ADD COLUMN IF NOT EXISTS resolved_reason varchar(32)",
    ]
    try:
        with engine.begin() as conn:
            for s in stmts:
                conn.execute(text(s))
    except Exception as e:  # noqa: BLE001
        logger.warning("infra_findings kolon ensure: %s", e)


def ensure_backup_columns(engine) -> None:
    """bk_* tablolarına Dilim D kolonları (tablolar create_all ile, ALTER ile genişler)."""
    stmts = [
        "ALTER TABLE bk_jobs ADD COLUMN IF NOT EXISTS status varchar(32)",
        "ALTER TABLE bk_jobs ADD COLUMN IF NOT EXISTS last_result varchar(32)",
        "ALTER TABLE bk_jobs ADD COLUMN IF NOT EXISTS last_run_at timestamptz",
        "ALTER TABLE bk_jobs ADD COLUMN IF NOT EXISTS next_run_at timestamptz",
        "ALTER TABLE bk_jobs ADD COLUMN IF NOT EXISTS repository_provider_id varchar(128)",
        "ALTER TABLE bk_jobs ADD COLUMN IF NOT EXISTS repository_name varchar(512)",
        "ALTER TABLE bk_jobs ADD COLUMN IF NOT EXISTS objects_count integer",
        "ALTER TABLE bk_sessions ADD COLUMN IF NOT EXISTS session_type varchar(64)",
        "ALTER TABLE bk_sessions ADD COLUMN IF NOT EXISTS message text",
        "ALTER TABLE bk_repositories ADD COLUMN IF NOT EXISTS used_bytes bigint",
        "ALTER TABLE bk_repositories ADD COLUMN IF NOT EXISTS is_online boolean",
        "ALTER TABLE bk_repositories ADD COLUMN IF NOT EXISTS repo_type varchar(64)",
        "ALTER TABLE bk_protected_objects ADD COLUMN IF NOT EXISTS object_ref varchar(256)",
        "ALTER TABLE bk_protected_objects ADD COLUMN IF NOT EXISTS path varchar(1024)",
        "ALTER TABLE bk_protected_objects ADD COLUMN IF NOT EXISTS last_restore_point_at timestamptz",
        "ALTER TABLE bk_protected_objects ADD COLUMN IF NOT EXISTS restore_points_count integer",
        "ALTER TABLE bk_protected_objects ADD COLUMN IF NOT EXISTS job_provider_id varchar(128)",
        # F.1 (yalnız eklemeli; mevcut veri silinmez/değişmez)
        "ALTER TABLE bk_jobs ADD COLUMN IF NOT EXISTS encryption_enabled boolean",
        "ALTER TABLE bk_jobs ADD COLUMN IF NOT EXISTS cbt_enabled boolean",
        "ALTER TABLE bk_jobs ADD COLUMN IF NOT EXISTS app_aware_enabled boolean",
        "ALTER TABLE bk_jobs ADD COLUMN IF NOT EXISTS backup_health_enabled boolean",
        "ALTER TABLE bk_jobs ADD COLUMN IF NOT EXISTS retention_type varchar(32)",
        "ALTER TABLE bk_jobs ADD COLUMN IF NOT EXISTS retention_quantity integer",
        "ALTER TABLE bk_jobs ADD COLUMN IF NOT EXISTS gfs_enabled boolean",
        "ALTER TABLE bk_jobs ADD COLUMN IF NOT EXISTS retry_enabled boolean",
        "ALTER TABLE bk_jobs ADD COLUMN IF NOT EXISTS retry_count integer",
        "ALTER TABLE bk_jobs ADD COLUMN IF NOT EXISTS retry_wait_min integer",
        "ALTER TABLE bk_jobs ADD COLUMN IF NOT EXISTS window_enabled boolean",
        "ALTER TABLE bk_jobs ADD COLUMN IF NOT EXISTS schedule_summary varchar(255)",
        "ALTER TABLE bk_jobs ADD COLUMN IF NOT EXISTS config_state varchar(16)",
        "ALTER TABLE bk_jobs ADD COLUMN IF NOT EXISTS config_json text",
        "ALTER TABLE bk_repositories ADD COLUMN IF NOT EXISTS immutability_status varchar(24) NOT NULL DEFAULT 'not_measurable'",
        "ALTER TABLE bk_protected_objects ADD COLUMN IF NOT EXISTS host_name varchar(255)",
        "ALTER TABLE bk_protected_objects ADD COLUMN IF NOT EXISTS host_verified boolean NOT NULL DEFAULT false",
    ]
    try:
        with engine.begin() as conn:
            for st in stmts:
                conn.execute(text(st))
    except Exception as e:  # noqa: BLE001
        logger.warning("bk_* kolon ensure: %s", e)
