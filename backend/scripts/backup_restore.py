"""Database + private Storage backup helper.

Credentials are read from environment variables and are never written to the
manifest. Restore is deliberately guarded by an explicit confirmation token.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from datetime import UTC, datetime

from app.config.settings import settings

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(root: Path) -> dict:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    errors = []
    for item in manifest["files"]:
        path = root / item["path"]
        if not path.exists() or sha256(path) != item["sha256"]:
            errors.append(item["path"])
    return {"valid": not errors, "invalidFiles": errors, "fileCount": len(manifest["files"])}


def backup(root: Path) -> dict:
    database_url = os.getenv("DATABASE_URL") or settings.database_url
    if not database_url:
        raise SystemExit("DATABASE_URL is required")
    root.mkdir(parents=True, exist_ok=False)
    dump = root / "database.dump"
    subprocess.run(["pg_dump", "--format=custom", "--no-owner", "--file", str(dump), database_url], check=True)
    manifest = {
        "formatVersion": 1, "createdAt": datetime.now(UTC).isoformat(),
        "files": [{"path": dump.name, "sha256": sha256(dump), "bytes": dump.stat().st_size}],
        "storage": {"included": False, "reason": "Export private Storage separately via provider lifecycle policy"},
    }
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def restore(root: Path, confirmation: str) -> None:
    if confirmation != "RESTORE":
        raise SystemExit("Restore requires --confirm RESTORE")
    result = verify(root)
    if not result["valid"]:
        raise SystemExit(f"Backup verification failed: {result['invalidFiles']}")
    database_url = os.getenv("DATABASE_URL") or settings.database_url
    if not database_url:
        raise SystemExit("DATABASE_URL is required")
    subprocess.run(
        ["pg_restore", "--clean", "--if-exists", "--no-owner", "--dbname", database_url, str(root / "database.dump")],
        check=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("backup", "verify", "restore"):
        command = sub.add_parser(name)
        command.add_argument("directory", type=Path)
        if name == "restore":
            command.add_argument("--confirm", default="")
    args = parser.parse_args()
    if args.command == "backup":
        print(json.dumps(backup(args.directory), ensure_ascii=False))
    elif args.command == "verify":
        result = verify(args.directory)
        print(json.dumps(result, ensure_ascii=False))
        raise SystemExit(0 if result["valid"] else 1)
    else:
        restore(args.directory, args.confirm)


if __name__ == "__main__":
    main()
