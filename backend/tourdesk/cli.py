"""TourDesk command line interface.

Usage examples::

    tourdesk migrate              # apply database migrations
    tourdesk seed                 # load geographic seed data, venues, festivals
    tourdesk init                 # migrate + seed (idempotent)
    tourdesk create-admin --username admin --email admin@example.org
    tourdesk api                  # start the web server (API + frontend)
    tourdesk worker               # start the crawler worker
    tourdesk scheduler            # start the scheduler
    tourdesk crawl --artist "Metallica"   # run one crawl synchronously
    tourdesk example-config       # create the example user from the README
    tourdesk reset-password --username alice
    tourdesk status               # print system status
"""

from __future__ import annotations

import argparse
import getpass
import json
import logging
import sys
import time
from pathlib import Path

from tourdesk import __version__


def _alembic_config():
    from alembic.config import Config

    from tourdesk.core.config import get_settings
    from tourdesk.core.db import _normalise_url

    settings = get_settings()
    cfg = Config()
    cfg.set_main_option("script_location", str(settings.migrations_dir))
    cfg.set_main_option("sqlalchemy.url", _normalise_url(settings.database_url).replace("%", "%%"))
    return cfg


def wait_for_db(timeout: int = 60) -> None:
    from sqlalchemy import text

    from tourdesk.core.db import get_engine

    deadline = time.monotonic() + timeout
    while True:
        try:
            with get_engine().connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except Exception as exc:  # pragma: no cover - depends on infrastructure
            if time.monotonic() > deadline:
                raise SystemExit(f"Datenbank nicht erreichbar: {exc}") from exc
            print("Warte auf Datenbank …", file=sys.stderr)
            time.sleep(2)


def cmd_migrate(args: argparse.Namespace) -> int:
    from alembic import command

    wait_for_db(args.wait)
    command.upgrade(_alembic_config(), "head")
    print("Migrationen angewendet.")
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    from tourdesk.core.db import session_scope
    from tourdesk.seed.loader import seed_all

    wait_for_db(args.wait)
    with session_scope() as db:
        result = seed_all(db, force=args.force)
    if result.get("skipped"):
        print("Seed-Daten sind aktuell.")
    else:
        print(
            f"Seed geladen: {result['countries']} Länder, {result['regions']} Regionen, "
            f"{result['cities']} Städte, {result['venues']} Venues, {result['festivals']} Festivals"
        )
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    cmd_migrate(args)
    return cmd_seed(args)


def _read_password(args: argparse.Namespace) -> str:
    if getattr(args, "password_stdin", False):
        return sys.stdin.readline().rstrip("\n")
    if getattr(args, "password", None):
        return args.password
    first = getpass.getpass("Passwort: ")
    second = getpass.getpass("Passwort wiederholen: ")
    if first != second:
        raise SystemExit("Die Passwörter stimmen nicht überein.")
    return first


def cmd_create_admin(args: argparse.Namespace) -> int:
    from fastapi import HTTPException

    from tourdesk.core.db import session_scope
    from tourdesk.services.users import create_user, find_user_by_login, generate_temporary_password

    wait_for_db(args.wait)
    generated = None
    if args.generate_password:
        generated = password = generate_temporary_password(16)
    else:
        password = _read_password(args)
    with session_scope() as db:
        if find_user_by_login(db, args.username) is not None:
            if args.if_missing:
                print(f"Benutzer {args.username} existiert bereits – übersprungen.")
                return 0
            raise SystemExit(f"Benutzer {args.username} existiert bereits.")
        try:
            user = create_user(db, username=args.username, email=args.email, password=password, role="admin")
        except HTTPException as exc:
            raise SystemExit(str(exc.detail)) from exc
        print(f"Administrator {user.username} angelegt.")
    if generated:
        print(f"Generiertes Passwort: {generated}")
    return 0


def cmd_reset_password(args: argparse.Namespace) -> int:
    from tourdesk.core.db import session_scope
    from tourdesk.core.timeutil import utcnow
    from tourdesk.security.passwords import hash_password
    from tourdesk.security.sessions import revoke_user_sessions
    from tourdesk.services.users import find_user_by_login, generate_temporary_password, validate_password

    with session_scope() as db:
        user = find_user_by_login(db, args.username)
        if user is None:
            raise SystemExit("Benutzer nicht gefunden.")
        password = generate_temporary_password() if args.generate_password else _read_password(args)
        validate_password(password, username=user.username, email=user.email)
        user.password_hash = hash_password(password)
        user.password_changed_at = utcnow()
        user.failed_login_count = 0
        user.locked_until = None
        user.must_change_password = args.generate_password
        revoke_user_sessions(db, user.id)
        print(f"Passwort für {user.username} gesetzt.")
        if args.generate_password:
            print(f"Temporäres Passwort: {password}")
    return 0


def cmd_api(args: argparse.Namespace) -> int:
    if args.migrate:
        cmd_migrate(args)
        cmd_seed(argparse.Namespace(wait=args.wait, force=False))
    from tourdesk.main import run

    run()
    return 0


def cmd_worker(args: argparse.Namespace) -> int:
    from tourdesk_crawler.worker import main as worker_main

    return worker_main([])


def cmd_scheduler(args: argparse.Namespace) -> int:
    from tourdesk_crawler.scheduler import main as scheduler_main

    return scheduler_main([])


def cmd_crawl(args: argparse.Namespace) -> int:
    from tourdesk.core.db import session_scope
    from tourdesk.core.logging import setup_logging
    from tourdesk.core.text import normalize_name
    from tourdesk.models import Artist
    from tourdesk_crawler.jobs.runner import run_job_inline

    setup_logging("cli")
    with session_scope() as db:
        from sqlalchemy import select

        artist = db.execute(select(Artist).where(Artist.name_norm == normalize_name(args.artist))).unique().scalar_one_or_none()
        if artist is None:
            raise SystemExit("Künstler nicht im Katalog. Bitte zuerst in der Weboberfläche anlegen.")
        artist_id = artist.id
    result = run_job_inline("artist_crawl", artist_id=artist_id)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0


def cmd_example_config(args: argparse.Namespace) -> int:
    from tourdesk.core.db import session_scope
    from tourdesk.services.example import create_example_user

    wait_for_db(args.wait)
    with session_scope() as db:
        info = create_example_user(db, username=args.username, email=args.email, password=args.password)
    print(json.dumps(info, indent=2, ensure_ascii=False))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    from sqlalchemy import func, select

    from tourdesk.core.db import check_database, session_scope
    from tourdesk.models import Artist, CrawlerRun, Event, SystemHeartbeat, User

    info = {"version": __version__, "database": check_database()}
    with session_scope() as db:
        info["users"] = db.execute(select(func.count(User.id))).scalar_one()
        info["artists"] = db.execute(select(func.count(Artist.id))).scalar_one()
        info["events"] = db.execute(select(func.count(Event.id))).scalar_one()
        info["last_run"] = db.execute(select(func.max(CrawlerRun.finished_at))).scalar()
        info["heartbeats"] = {h.component: h.last_seen_at for h in db.execute(select(SystemHeartbeat)).scalars()}
    print(json.dumps(info, indent=2, ensure_ascii=False, default=str))
    return 0


def cmd_cleanup(args: argparse.Namespace) -> int:
    from tourdesk_crawler.jobs.maintenance import run_maintenance

    from tourdesk.core.db import session_scope

    with session_scope() as db:
        print(json.dumps(run_maintenance(db), indent=2, default=str))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tourdesk", description="TourDesk Verwaltung")
    parser.add_argument("--version", action="version", version=f"TourDesk {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, func, help_: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_)
        p.set_defaults(func=func)
        p.add_argument("--wait", type=int, default=60, help="Sekunden auf die Datenbank warten")
        return p

    add("migrate", cmd_migrate, "Datenbank-Migrationen anwenden")
    p = add("seed", cmd_seed, "Seed-Daten laden (Geodaten, Venues, Festivals)")
    p.add_argument("--force", action="store_true")
    p = add("init", cmd_init, "Migrationen + Seed")
    p.add_argument("--force", action="store_true")

    p = add("create-admin", cmd_create_admin, "Administrator anlegen")
    p.add_argument("--username", required=True)
    p.add_argument("--email", required=True)
    p.add_argument("--password")
    p.add_argument("--password-stdin", action="store_true")
    p.add_argument("--generate-password", action="store_true")
    p.add_argument("--if-missing", action="store_true", help="Nichts tun, wenn der Benutzer existiert")

    p = add("reset-password", cmd_reset_password, "Passwort eines Benutzers zurücksetzen")
    p.add_argument("--username", required=True)
    p.add_argument("--password")
    p.add_argument("--password-stdin", action="store_true")
    p.add_argument("--generate-password", action="store_true")

    p = add("api", cmd_api, "Webserver starten")
    p.add_argument("--migrate", action="store_true", help="vor dem Start migrieren und seeden")
    add("worker", cmd_worker, "Crawler-Worker starten")
    add("scheduler", cmd_scheduler, "Scheduler starten")
    p = add("crawl", cmd_crawl, "Einen Künstler sofort crawlen (synchron)")
    p.add_argument("--artist", required=True)
    p = add("example-config", cmd_example_config, "Beispielbenutzer aus der Anleitung anlegen")
    p.add_argument("--username", default="beispiel")
    p.add_argument("--email", default="beispiel@tourdesk.local")
    p.add_argument("--password", default=None)
    add("status", cmd_status, "Systemstatus ausgeben")
    add("cleanup", cmd_cleanup, "Wartung ausführen (alte Läufe, Cache, Sessions)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    return int(args.func(args) or 0)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())


__all__ = ["main", "Path"]
