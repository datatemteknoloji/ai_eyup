#!/usr/bin/env python3
"""Gerçek bir VBR'den SALT-OKUNUR, maskeli fixture toplar — ayrıntı ve güvenlik notları:
``app/services/backup/fixture_collect.py`` (docstring). Kullanım:

  VBR_PASSWORD='…' PYTHONPATH=backend python backend/scripts/veeam_collect_fixtures.py \\
      --host vbr.example.local --user svc-ainew --revision 1.3-rev1 --dry-run
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.backup.fixture_collect import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
