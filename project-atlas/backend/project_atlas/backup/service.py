"""Backup, verification and restore.

Archive layout (tar.gz, optionally encrypted with AES-256-GCM, key from scrypt):

    manifest.json        counts per table, file hashes, schema revision, software version
    database.sqlite3     consistent snapshot via the SQLite online-backup API
    workspace/files/...  uploaded originals
    workspace/derived/...columnar dataset copies
    workspace/exports/...report exports
    workspace/audit-checkpoints.jsonl
    workspace/audit-checkpoint.key   (encrypted archives only)

PostgreSQL deployments must use pg_dump/pg_restore for the database portion;
see docs/backup-recovery.md (not automated in this release).
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import inspect, select, text

from project_atlas import __version__
from project_atlas.core.errors import NotFound, ValidationFailed
from project_atlas.database.models import BackupManifest
from project_atlas.database.session import current_revision, upgrade_database

if TYPE_CHECKING:
    from project_atlas.core.context import AtlasContext

MAGIC = b"ATLASENC1"
WORKSPACE_DIRS = ["files", "derived", "exports"]
WORKSPACE_FILES = ["audit-checkpoints.jsonl"]
RETENTION_DEFAULT = 10
_restore_lock = threading.Lock()


def _db_path(ctx: "AtlasContext") -> Path:
    url = ctx.settings.resolved_database_url
    if not url.startswith("sqlite:///"):
        raise ValidationFailed("Automated backups support SQLite deployments; use pg_dump for PostgreSQL")
    return Path(url[len("sqlite:///"):])


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def _counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                                         "AND name NOT LIKE 'search_index_%'")]
    return {t: conn.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in sorted(tables)}


def _kdf(passphrase: str, salt: bytes) -> bytes:
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(passphrase.encode())


def encrypt(data: bytes, passphrase: str) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    salt, nonce = os.urandom(16), os.urandom(12)
    return MAGIC + salt + nonce + AESGCM(_kdf(passphrase, salt)).encrypt(nonce, data, MAGIC)


def decrypt(blob: bytes, passphrase: str) -> bytes:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if not blob.startswith(MAGIC):
        raise ValidationFailed("Not an encrypted Atlas backup")
    salt, nonce, ct = blob[9:25], blob[25:37], blob[37:]
    try:
        return AESGCM(_kdf(passphrase, salt)).decrypt(nonce, ct, MAGIC)
    except InvalidTag as exc:
        raise ValidationFailed("Wrong passphrase or corrupted backup") from exc


def create_backup(ctx: "AtlasContext", *, user_id: str | None, passphrase: str | None, kind: str = "manual") -> dict[str, Any]:
    if passphrase is not None and len(passphrase) < 12:
        raise ValidationFailed("Backup passphrase must be at least 12 characters")
    db_path = _db_path(ctx)
    ws = ctx.settings.storage_dir
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    with tempfile.TemporaryDirectory(dir=ctx.settings.backup_dir) as td:
        snap = Path(td) / "database.sqlite3"
        src = sqlite3.connect(str(db_path))
        dst = sqlite3.connect(str(snap))
        with dst:
            src.backup(dst)
        counts = _counts(dst)
        integrity = dst.execute("PRAGMA integrity_check").fetchone()[0]
        dst.close()
        src.close()
        if integrity != "ok":
            raise RuntimeError(f"Live database failed integrity check: {integrity}")
        files: dict[str, str] = {"database.sqlite3": _sha(snap)}
        members: list[tuple[Path, str]] = [(snap, "database.sqlite3")]
        for d in WORKSPACE_DIRS:
            root = ws / d
            if root.exists():
                for p in sorted(root.rglob("*")):
                    if p.is_file():
                        arc = f"workspace/{p.relative_to(ws).as_posix()}"
                        files[arc] = _sha(p)
                        members.append((p, arc))
        extra = list(WORKSPACE_FILES) + (["audit-checkpoint.key"] if passphrase else [])
        for name in extra:
            p = ws / name
            if p.exists():
                files[f"workspace/{name}"] = _sha(p)
                members.append((p, f"workspace/{name}"))
        revision = current_revision(ctx.engine)
        manifest = {"format": "atlas-backup-1", "created_at": stamp, "software_version": __version__,
                    "schema_revision": revision, "counts": counts, "files": files, "encrypted": passphrase is not None,
                    "kind": kind, "includes_checkpoint_key": passphrase is not None}
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            mb = json.dumps(manifest, indent=2).encode()
            ti = tarfile.TarInfo("manifest.json")
            ti.size = len(mb)
            ti.mtime = int(time.time())
            tar.addfile(ti, io.BytesIO(mb))
            for p, arc in members:
                tar.add(str(p), arcname=arc, recursive=False)
        data = buf.getvalue()
    if passphrase:
        data = encrypt(data, passphrase)
    name = f"atlas-backup-{stamp}.tar.gz" + (".enc" if passphrase else "")
    out = ctx.settings.backup_dir / name
    out.write_bytes(data)
    os.chmod(out, 0o600)
    sha = hashlib.sha256(data).hexdigest()
    with ctx.sm() as db:
        db.add(BackupManifest(filename=name, sha256=sha, size_bytes=len(data), encrypted=bool(passphrase),
                              counts=counts, kind=kind, created_by=user_id))
        db.commit()
    apply_retention(ctx)
    return {"filename": name, "sha256": sha, "size_bytes": len(data), "encrypted": bool(passphrase), "counts": counts}


def apply_retention(ctx: "AtlasContext", keep: int | None = None) -> list[str]:
    keep = keep or ctx.settings.backup_retention or RETENTION_DEFAULT
    removed = []
    with ctx.sm() as db:
        rows = db.execute(select(BackupManifest).where(BackupManifest.kind == "scheduled")
                          .order_by(BackupManifest.created_at.desc())).scalars().all()
        for r in rows[keep:]:
            (ctx.settings.backup_dir / r.filename).unlink(missing_ok=True)
            removed.append(r.filename)
            db.delete(r)
        db.commit()
    return removed


def _safe_backup_path(ctx: "AtlasContext", filename: str) -> Path:
    if "/" in filename or "\\" in filename or filename.startswith("."):
        raise ValidationFailed("Invalid backup filename")
    p = (ctx.settings.backup_dir / filename).resolve()
    if p.parent != ctx.settings.backup_dir.resolve() or not p.is_file():
        raise NotFound("Backup not found")
    return p


def _open(ctx: "AtlasContext", filename: str, passphrase: str | None) -> tuple[bytes, dict[str, Any]]:
    p = _safe_backup_path(ctx, filename)
    data = p.read_bytes()
    if data.startswith(MAGIC):
        if not passphrase:
            raise ValidationFailed("This backup is encrypted; a passphrase is required")
        data = decrypt(data, passphrase)
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            manifest = json.loads(tar.extractfile("manifest.json").read())
    except (tarfile.TarError, KeyError, json.JSONDecodeError) as exc:
        raise ValidationFailed(f"Backup archive is unreadable: {exc}") from exc
    return data, manifest


def verify_backup(ctx: "AtlasContext", filename: str, passphrase: str | None = None) -> dict[str, Any]:
    data, manifest = _open(ctx, filename, passphrase)
    problems = []
    with tempfile.TemporaryDirectory(dir=ctx.settings.backup_dir) as td:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            for m in tar.getmembers():
                if m.name == "manifest.json":
                    continue
                if not m.isfile() or m.name.startswith("/") or ".." in Path(m.name).parts:
                    problems.append(f"unsafe member {m.name}")
                    continue
                f = tar.extractfile(m)
                h = hashlib.sha256(f.read()).hexdigest()
                if manifest["files"].get(m.name) != h:
                    problems.append(f"hash mismatch: {m.name}")
            missing = set(manifest["files"]) - {m.name for m in tar.getmembers()}
            problems += [f"missing member {x}" for x in sorted(missing)]
            tar.extract("database.sqlite3", path=td, filter="data")
        conn = sqlite3.connect(str(Path(td) / "database.sqlite3"))
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        counts = _counts(conn)
        conn.close()
    if integrity != "ok":
        problems.append(f"database integrity_check: {integrity}")
    if counts != manifest["counts"]:
        problems.append("record counts differ from manifest")
    ok = not problems
    if ok:
        with ctx.sm() as db:
            rec = db.execute(select(BackupManifest).where(BackupManifest.filename == filename)).scalar_one_or_none()
            if rec:
                rec.verified_at = datetime.now(timezone.utc)
                db.commit()
    return {"filename": filename, "valid": ok, "problems": problems, "manifest": {k: v for k, v in manifest.items() if k != "files"},
            "file_count": len(manifest["files"]), "database_integrity": integrity}


def restore_backup(ctx: "AtlasContext", filename: str, passphrase: str | None = None) -> dict[str, Any]:
    """Replace the live database and workspace files with the backup's contents.

    The current state is moved aside to ``<workspace>/.pre-restore-<timestamp>`` first so that a
    failed restore can be rolled back manually. Running jobs should be stopped beforehand.
    """
    report = verify_backup(ctx, filename, passphrase)
    if not report["valid"]:
        raise ValidationFailed("Backup failed verification; refusing to restore", details={"problems": report["problems"]})
    data, manifest = _open(ctx, filename, passphrase)
    db_path = _db_path(ctx)
    ws = ctx.settings.storage_dir
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    aside = ws / f".pre-restore-{stamp}"
    with _restore_lock:
        ctx.engine.dispose()
        aside.mkdir(parents=True)
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(db_path) + suffix)
            if p.exists():
                shutil.move(str(p), aside / p.name)
        for d in WORKSPACE_DIRS + WORKSPACE_FILES + (["audit-checkpoint.key"] if manifest.get("includes_checkpoint_key") else []):
            p = ws / d
            if p.exists():
                shutil.move(str(p), aside / d)
        with tempfile.TemporaryDirectory(dir=ctx.settings.backup_dir) as td:
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
                tar.extractall(path=td, filter="data")
            shutil.move(str(Path(td) / "database.sqlite3"), str(db_path))
            restored_ws = Path(td) / "workspace"
            if restored_ws.exists():
                for item in restored_ws.iterdir():
                    shutil.move(str(item), str(ws / item.name))
        for d in WORKSPACE_DIRS:
            (ws / d).mkdir(exist_ok=True)
        upgrade_database(ctx.engine)  # backups from older schema revisions are migrated forward
    with ctx.sm() as db:
        live = {}
        insp = inspect(ctx.engine)
        for t in manifest["counts"]:
            live[t] = db.execute(text(f'SELECT count(*) FROM "{t}"')).scalar_one() if insp.has_table(t) or t == "search_index" else None
    mismatched = {t: (manifest["counts"][t], live[t]) for t in manifest["counts"] if live.get(t) != manifest["counts"][t]
                  and t not in {"alembic_version"}}
    return {"restored": filename, "previous_state_moved_to": str(aside), "count_mismatches": mismatched,
            "schema_revision": current_revision(ctx.engine), "backup_schema_revision": manifest["schema_revision"]}


def list_backups(ctx: "AtlasContext") -> list[dict[str, Any]]:
    with ctx.sm() as db:
        known = {r.filename: r for r in db.execute(select(BackupManifest)).scalars()}
    out = []
    for p in sorted(ctx.settings.backup_dir.glob("atlas-backup-*"), reverse=True):
        r = known.get(p.name)
        out.append({"filename": p.name, "size_bytes": p.stat().st_size, "encrypted": p.name.endswith(".enc"),
                    "registered": r is not None, "sha256": r.sha256 if r else None, "kind": r.kind if r else "unknown",
                    "verified_at": r.verified_at if r else None, "created_at": r.created_at if r else None,
                    "counts": r.counts if r else None})
    return out


def scheduled_passphrase(ctx: "AtlasContext") -> str | None:
    """Passphrase for scheduled backups, read from ATLAS_BACKUP_PASSPHRASE_FILE at each run (never stored by Atlas)."""
    f = ctx.settings.backup_passphrase_file
    if f is None:
        return None
    if not f.is_file():
        raise ValidationFailed(f"ATLAS_BACKUP_PASSPHRASE_FILE {f} does not exist")
    if os.name == "posix" and f.stat().st_mode & 0o077:
        raise ValidationFailed(f"{f} must not be readable by group/other (chmod 600)")
    pw = f.read_text(encoding="utf-8").strip()
    if len(pw) < 12:
        raise ValidationFailed("Scheduled backup passphrase must be at least 12 characters")
    return pw


class BackupScheduler:
    """Background maintenance: scheduled (optionally encrypted) backups and optional retention sweeps."""

    def __init__(self, ctx: "AtlasContext", interval_hours: float, retention_hours: float = 0.0):
        self.ctx, self.interval, self.retention_interval = ctx, interval_hours * 3600, retention_hours * 3600
        self._stop = threading.Event()
        self.threads: list[threading.Thread] = []
        self.last_error: str | None = None

    def start(self) -> None:
        for interval, fn, name in ((self.interval, self._backup, "atlas-backup-scheduler"),
                                   (self.retention_interval, self._retention, "atlas-retention-scheduler")):
            if interval > 0:
                t = threading.Thread(target=self._loop, args=(interval, fn), name=name, daemon=True)
                t.start()
                self.threads.append(t)

    def _loop(self, interval: float, fn) -> None:
        while not self._stop.wait(interval):
            fn()

    def _backup(self) -> None:
        try:
            res = create_backup(self.ctx, user_id=None, passphrase=scheduled_passphrase(self.ctx), kind="scheduled")
            self.ctx.audit.record("backup.scheduled", actor_id=None, actor_name="system:scheduler", resource_type="backup",
                                  resource_id=res["filename"], details={"encrypted": res["encrypted"]})
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(getattr(exc, "message", exc))
            self.ctx.audit.record("backup.scheduled", actor_id=None, actor_name="system:scheduler", resource_type="backup",
                                  outcome="failure", details={"error": self.last_error})

    def _retention(self) -> None:
        from project_atlas.retention import apply_retention

        try:
            with self.ctx.sm() as db:
                apply_retention(self.ctx, db, actor_id=None)
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)
            self.ctx.audit.record("retention.apply", actor_id=None, actor_name="system:scheduler", resource_type="retention",
                                  outcome="failure", details={"error": str(exc)})

    def stop(self) -> None:
        self._stop.set()
