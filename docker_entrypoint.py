#!/usr/bin/env python3
"""Prepare bind-mounted data, then drop privileges and start the app."""

from __future__ import annotations

import os
import pwd
import shutil
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("No command specified")

    if os.geteuid() == 0:
        account = pwd.getpwnam("lwpdfgen")
        data = Path(os.getenv("APP_DATA_DIR", "/app/data"))
        storage = Path(os.getenv("PDF_STORAGE_DIR", str(data / "pdf")))
        temporary = storage / ".tmp"

        temporary.mkdir(parents=True, exist_ok=True)
        for directory in (data, storage, temporary):
            os.chown(directory, account.pw_uid, account.pw_gid)
            directory.chmod(directory.stat().st_mode | 0o700)

        defaults = Path("/app/static")
        for filename in ("index.html", "pdf-nicht-gefunden.html"):
            target = data / filename
            if not target.exists():
                shutil.copy2(defaults / filename, target)
            os.chown(target, account.pw_uid, account.pw_gid)

        os.initgroups(account.pw_name, account.pw_gid)
        os.setgid(account.pw_gid)
        os.setuid(account.pw_uid)

    os.execvp(sys.argv[1], sys.argv[1:])


if __name__ == "__main__":
    main()
