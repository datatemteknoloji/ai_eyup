#!/usr/bin/env python3
"""
SECRET_KEY rotasyonu (container içi).

Kullanım (backend container):
  OLD_SECRET_KEY='...' NEW_SECRET_KEY='...' python -m app.scripts.rotate_secret_key

veya host: scripts/rotate-secrets.sh
"""
from __future__ import annotations

import json
import os
import sys


def main() -> int:
    old_key = os.environ.get("OLD_SECRET_KEY") or os.environ.get("SECRET_KEY") or ""
    new_key = os.environ.get("NEW_SECRET_KEY") or ""
    if not new_key:
        print("NEW_SECRET_KEY gerekli", file=sys.stderr)
        return 2
    if not old_key:
        print("OLD_SECRET_KEY / SECRET_KEY gerekli", file=sys.stderr)
        return 2

    from app.core.database import SessionLocal
    from app.services.secret_key_rotate import apply_runtime_secret_key, rotate_secret_key
    from app.services.secret_policy import is_insecure_secret_value

    if is_insecure_secret_value(new_key, min_len=32):
        print("NEW_SECRET_KEY zayıf/placeholder — openssl rand -hex 32 kullanın", file=sys.stderr)
        return 2

    db = SessionLocal()
    try:
        stats = rotate_secret_key(db, old_key, new_key)
        db.commit()
        apply_runtime_secret_key(new_key)
        # stdout: sadece özet (key yok)
        print(json.dumps({"ok": True, **stats}, ensure_ascii=False))
        return 0
    except Exception as e:
        db.rollback()
        print(json.dumps({"ok": False, "error": str(e)}), file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
