"""Command-line entry point: ``atlas serve | create-admin | backup | verify-backup | offline-check | migrate``."""

from __future__ import annotations

import argparse
import getpass
import json
import sys


def _ctx():
    from project_atlas.core.config import load_settings
    from project_atlas.core.context import build_context

    return build_context(load_settings())


def cmd_serve(args) -> int:
    import uvicorn

    from project_atlas.core.config import load_settings
    from project_atlas.main import create_app

    s = load_settings()
    app = create_app(s)
    print(f"Project Atlas listening on http://{s.host}:{s.port}  (offline mode: {s.offline_mode})")
    uvicorn.run(app, host=s.host, port=s.port, log_level=s.log_level.lower(), proxy_headers=s.tls_terminated)
    return 0


def cmd_create_admin(args) -> int:
    from sqlalchemy import func, select

    from project_atlas.database.models import User
    from project_atlas.security.passwords import WeakPasswordError, check_policy, hash_password

    ctx = _ctx()
    with ctx.sm() as db:
        if db.execute(select(func.count()).select_from(User)).scalar_one() > 0 and not args.additional:
            print("Users already exist; pass --additional to add another system administrator.", file=sys.stderr)
            return 1
        pw = getpass.getpass("Password: ")
        if pw != getpass.getpass("Repeat password: "):
            print("Passwords differ.", file=sys.stderr)
            return 1
        try:
            check_policy(pw, args.username)
        except WeakPasswordError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        u = User(username=args.username, display_name=args.display_name or args.username, password_hash=hash_password(pw),
                 global_role="system_admin")
        db.add(u)
        db.commit()
        ctx.audit.record("auth.setup", actor_id=u.id, actor_name=u.username, resource_type="user", resource_id=u.id,
                         details={"via": "cli"})
    ctx.ensure_setup_token()  # removes the web setup token now that a user exists
    print(f"Created system administrator {args.username}")
    return 0


def cmd_backup(args) -> int:
    from project_atlas.backup.service import create_backup

    ctx = _ctx()
    pw = getpass.getpass("Backup passphrase (empty for unencrypted): ") if args.encrypt else None
    res = create_backup(ctx, user_id=None, passphrase=pw or None, kind="manual")
    ctx.audit.record("backup.create", actor_id=None, actor_name="cli", resource_type="backup", resource_id=res["filename"])
    print(json.dumps(res, indent=2))
    return 0


def cmd_verify_backup(args) -> int:
    from project_atlas.backup.service import verify_backup

    ctx = _ctx()
    pw = getpass.getpass("Passphrase: ") if args.filename.endswith(".enc") else None
    res = verify_backup(ctx, args.filename, pw)
    print(json.dumps(res, indent=2, default=str))
    return 0 if res["valid"] else 2


def cmd_offline_check(args) -> int:
    from project_atlas.core.netguard import guard

    ctx = _ctx()
    s = ctx.settings
    probe = guard.probe()
    out = {"offline_mode": s.offline_mode, "telemetry_enabled": s.telemetry_enabled, "host": s.host,
           "ai_base_url": s.ai_base_url or None, "guard": guard.report(), "probe": probe}
    print(json.dumps(out, indent=2))
    return 0 if s.offline_mode and probe.startswith("blocked") else 2


def cmd_migrate(args) -> int:
    from project_atlas.database.session import current_revision

    ctx = _ctx()  # build_context upgrades the schema
    print(f"Database at revision {current_revision(ctx.engine)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="atlas", description="Project Atlas — Navigate the Complexity of Data.")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve", help="run the atlas-api server (serves the UI if built)").set_defaults(fn=cmd_serve)
    ca = sub.add_parser("create-admin", help="create the initial system administrator interactively")
    ca.add_argument("username")
    ca.add_argument("--display-name")
    ca.add_argument("--additional", action="store_true")
    ca.set_defaults(fn=cmd_create_admin)
    b = sub.add_parser("backup", help="create a backup archive")
    b.add_argument("--encrypt", action="store_true")
    b.set_defaults(fn=cmd_backup)
    vb = sub.add_parser("verify-backup", help="verify a backup archive")
    vb.add_argument("filename")
    vb.set_defaults(fn=cmd_verify_backup)
    sub.add_parser("offline-check", help="verify offline configuration and the network guard").set_defaults(fn=cmd_offline_check)
    sub.add_parser("migrate", help="apply database migrations").set_defaults(fn=cmd_migrate)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
