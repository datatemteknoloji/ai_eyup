#!/usr/bin/env python3
"""One-shot RAG metadata migrate (chash / model / tsv). Writes /tmp/rag_migrate_report.json."""
from __future__ import annotations

import json
import sys
import time

from sqlalchemy import text

from app.core.database import engine
from app.services import rag_store as rs


def _counts() -> dict:
    with engine.connect() as c:
        row = c.execute(
            text(
                """
                SELECT
                  count(*) AS total,
                  count(*) FILTER (
                    WHERE coalesce(metadata->>'chash','') = ''
                  ) AS missing_chash,
                  count(*) FILTER (
                    WHERE coalesce(metadata->>'_chash_skip','') = 'true'
                  ) AS chash_skip,
                  count(*) FILTER (
                    WHERE embedding_model IS NOT NULL AND embedding_model <> ''
                  ) AS has_model,
                  count(*) FILTER (WHERE document_tsv IS NOT NULL) AS has_tsv
                FROM rag_embeddings
                """
            )
        ).mappings().first()
    return dict(row or {})


def main() -> int:
    print("counts_before", _counts(), flush=True)
    rs._schema_ready = False
    rs._metadata_migrated = False
    rs.ensure_schema()
    # ensure_schema arka plan thread'i başlatmış olabilir — biz force ile sahipleniyoruz
    time.sleep(0.5)
    rs._metadata_migrated = False
    t0 = time.time()
    print("migrate_start", flush=True)
    rep = rs.migrate_rag_embedding_metadata(force=True, batch_size=500)
    rep["elapsed_sec"] = round(time.time() - t0, 1)
    rep["counts_after"] = _counts()
    print(json.dumps(rep, ensure_ascii=False, indent=2), flush=True)
    with open("/tmp/rag_migrate_report.json", "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=2, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
