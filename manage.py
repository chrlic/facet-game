"""FACET server management CLI — operates directly on the database.

Usage:
  python3 manage.py list-players [query]
  python3 manage.py make-admin <name> [--revoke]
  python3 manage.py reset-password <name>
  python3 manage.py stats

Safe to run while the server is up (SQLite WAL; sessions are DB-backed, so
password resets take effect immediately). FACET_DB selects the database file,
same as for server.py.
"""
import argparse
import sys

import storage
import service


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list-players", help="list players (optionally filtered)")
    p.add_argument("query", nargs="?", default=None)

    p = sub.add_parser("make-admin", help="grant (or revoke) admin rights")
    p.add_argument("name")
    p.add_argument("--revoke", action="store_true")

    p = sub.add_parser("reset-password",
                       help="set a temporary password and log out all sessions")
    p.add_argument("name")

    sub.add_parser("stats", help="server statistics overview")

    args = ap.parse_args()
    storage.init_db()

    if args.cmd == "list-players":
        rows = storage.all_players(args.query)
        if not rows:
            print("no players found")
            return
        print(f"{'name':22s} {'rating':>6s} {'rated':>5s} {'act/fin':>8s}"
              f" {'type':7s} {'admin':5s} last seen")
        for r in rows:
            print(f"{r['name']:22s} {round(r['rating']):>6d}"
                  f" {r['rated_games']:>5d}"
                  f" {r['active_games']:>3d}/{r['finished_games']:<4d}"
                  f" {'guest' if r['is_guest'] else 'account':7s}"
                  f" {'yes' if r['is_admin'] else '':5s}"
                  f" {r['last_seen'][:16]}")

    elif args.cmd == "make-admin":
        player = storage.get_player_by_name(args.name)
        if not player:
            sys.exit(f"error: no player named '{args.name}'")
        if player["is_guest"] and not args.revoke:
            sys.exit("error: guests cannot be admins — claim the account first")
        storage.set_admin(player["id"], 0 if args.revoke else 1)
        print(f"{'revoked admin from' if args.revoke else 'granted admin to'}"
              f" '{player['name']}'")

    elif args.cmd == "reset-password":
        try:
            out = service.admin_reset_password(args.name)
        except service.ApiError as e:
            sys.exit(f"error: {e.msg}")
        print(f"temporary password for {out['name']}: {out['temp_password']}")
        print("all of their sessions have been logged out")

    elif args.cmd == "stats":
        for k, v in storage.overview_stats().items():
            print(f"{k:22s} {v}")


if __name__ == "__main__":
    main()
