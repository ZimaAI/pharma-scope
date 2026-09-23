#!/usr/bin/env python3
"""Private PostgreSQL backup; keep credentials out of argv and output."""
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone
from sqlalchemy.engine import make_url

url = make_url(os.environ.get("PHARMA_DATABASE_URL") or os.environ["DATABASE_URL"])
if not url.drivername.startswith("postgres"):
    raise SystemExit("PostgreSQL connection required")
directory = Path(sys.argv[1] if len(sys.argv) > 1 else "backups")
directory.mkdir(mode=0o700, parents=True, exist_ok=True)
os.umask(0o077)
output = directory / ("pharmascope-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".dump")
env = dict(os.environ)
env.update(PGHOST=url.host or "localhost", PGPORT=str(url.port or 5432), PGUSER=url.username or "", PGPASSWORD=url.password or "", PGDATABASE=url.database or "")
subprocess.run(["pg_dump", "--format=custom", "--no-password", "--file", str(output)], env=env, check=True)
print(output)
