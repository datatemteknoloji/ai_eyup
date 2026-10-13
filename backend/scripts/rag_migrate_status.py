#!/usr/bin/env python3
from sqlalchemy import text
from app.core.database import engine

with engine.connect() as c:
    row = c.execute(
        text(
            """
            SELECT
              count(*) FILTER (WHERE coalesce(metadata->>'chash','')='') AS missing_chash,
              count(*) FILTER (
                WHERE embedding_model IS NOT NULL AND embedding_model <> ''
              ) AS has_model,
              count(*) FILTER (WHERE document_tsv IS NOT NULL) AS has_tsv
            FROM rag_embeddings
            """
        )
    ).mappings().first()
    print("counts", dict(row))
    acts = c.execute(
        text(
            """
            SELECT pid, state, wait_event_type, left(query, 100) AS q
            FROM pg_stat_activity
            WHERE datname = current_database()
              AND pid <> pg_backend_pid()
              AND query ILIKE '%rag_embeddings%'
            ORDER BY query_start
            """
        )
    ).fetchall()
    print("activity", acts)
