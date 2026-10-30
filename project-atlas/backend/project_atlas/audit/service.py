"""Append-only, hash-chained audit log.

Each event stores ``hash = SHA-256(prev_hash || canonical(event))``. The chain
lets an auditor detect modified, removed or reordered rows. Database triggers
reject UPDATE/DELETE on ``audit_events``. HMAC-signed checkpoints of the chain
head are written to a file outside the database, keyed by a secret in the
workspace directory.

Limitation: a sufficiently privileged local administrator who controls both
the database file and the checkpoint key can rewrite history undetectably.
Export checkpoints to separate media to reduce that risk.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from project_atlas.database.models import AuditEvent, new_id, utcnow

GENESIS = "0" * 64
_lock = threading.Lock()

_SENSITIVE_KEYS = {"password", "new_password", "token", "secret", "totp", "passphrase", "setup_token"}


def _ts_str(ts: datetime) -> str:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def scrub(details: dict[str, Any] | None) -> dict[str, Any]:
    """Remove secrets from audit metadata."""
    out: dict[str, Any] = {}
    for k, v in (details or {}).items():
        if k.lower() in _SENSITIVE_KEYS:
            out[k] = "[redacted]"
        elif isinstance(v, dict):
            out[k] = scrub(v)
        else:
            out[k] = v
    return out


def _canonical(e: AuditEvent) -> str:
    payload = {
        "event_id": e.event_id, "ts": _ts_str(e.ts), "actor_id": e.actor_id, "actor_name": e.actor_name,
        "action": e.action, "resource_type": e.resource_type, "resource_id": e.resource_id,
        "project_id": e.project_id, "outcome": e.outcome, "details": e.details,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def compute_hash(prev_hash: str, e: AuditEvent) -> str:
    return hashlib.sha256((prev_hash + _canonical(e)).encode()).hexdigest()


class AuditLog:
    def __init__(self, sm: sessionmaker[Session], storage_dir: Path):
        self.sm = sm
        self.storage_dir = storage_dir

    # -- writing -------------------------------------------------------------------------------
    def record(
        self,
        action: str,
        *,
        actor_id: str | None,
        actor_name: str,
        resource_type: str,
        resource_id: str | None = None,
        project_id: str | None = None,
        outcome: str = "success",
        details: dict[str, Any] | None = None,
    ) -> AuditEvent:
        with _lock, self.sm() as s:
            last = s.execute(select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(1)).scalar_one_or_none()
            prev = last.hash if last else GENESIS
            e = AuditEvent(
                event_id=new_id("aud"), ts=utcnow(), actor_id=actor_id, actor_name=actor_name, action=action,
                resource_type=resource_type, resource_id=resource_id, project_id=project_id, outcome=outcome,
                details=json.loads(json.dumps(scrub(details), default=str)), prev_hash=prev, hash="",
            )
            e.hash = compute_hash(prev, e)
            s.add(e)
            s.commit()
            return e

    # -- verification --------------------------------------------------------------------------
    def verify(self) -> dict[str, Any]:
        with self.sm() as s:
            prev = GENESIS
            count = 0
            for e in s.execute(select(AuditEvent).order_by(AuditEvent.seq)).scalars():
                count += 1
                if e.prev_hash != prev or compute_hash(prev, e) != e.hash:
                    return {"valid": False, "events_checked": count, "broken_at_seq": e.seq, "head": prev}
                prev = e.hash
        checkpoints = self._verify_checkpoints()
        return {"valid": True and checkpoints["valid"], "events_checked": count, "head": prev,
                "checkpoints": checkpoints}

    # -- checkpoints ---------------------------------------------------------------------------
    @property
    def _key_path(self) -> Path:
        return self.storage_dir / "audit-checkpoint.key"

    @property
    def _cp_path(self) -> Path:
        return self.storage_dir / "audit-checkpoints.jsonl"

    def _key(self) -> bytes:
        if not self._key_path.exists():
            self._key_path.write_bytes(secrets.token_bytes(32))
            os.chmod(self._key_path, 0o600)
        return self._key_path.read_bytes()

    def checkpoint(self) -> dict[str, Any]:
        with self.sm() as s:
            last = s.execute(select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(1)).scalar_one_or_none()
            count = s.execute(select(func.count()).select_from(AuditEvent)).scalar_one()
        if not last:
            return {"created": False, "reason": "no audit events"}
        body = {"seq": last.seq, "hash": last.hash, "count": count, "at": _ts_str(utcnow())}
        mac = hmac.new(self._key(), json.dumps(body, sort_keys=True).encode(), hashlib.sha256).hexdigest()
        with self._cp_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({**body, "hmac": mac}) + "\n")
        return {"created": True, **body}

    def _verify_checkpoints(self) -> dict[str, Any]:
        if not self._cp_path.exists():
            return {"valid": True, "checked": 0}
        key = self._key()
        checked = 0
        with self.sm() as s:
            for line in self._cp_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                cp = json.loads(line)
                mac = cp.pop("hmac")
                expect = hmac.new(key, json.dumps(cp, sort_keys=True).encode(), hashlib.sha256).hexdigest()
                if not hmac.compare_digest(mac, expect):
                    return {"valid": False, "checked": checked, "reason": f"bad checkpoint signature at seq {cp['seq']}"}
                e = s.get(AuditEvent, cp["seq"])
                if e is None or e.hash != cp["hash"]:
                    return {"valid": False, "checked": checked, "reason": f"chain diverges from checkpoint at seq {cp['seq']}"}
                checked += 1
        return {"valid": True, "checked": checked}
