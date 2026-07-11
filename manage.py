"""FACET server management CLI — operates directly on the database.

Usage:
  python3 manage.py list-players [query]
  python3 manage.py make-admin <name> [--revoke]
  python3 manage.py reset-password <name>
  python3 manage.py stats
  python3 manage.py list-reports [--status open|reviewed|all]
  python3 manage.py show-report <id> [--json]
  python3 manage.py resolve-report <id> [--reopen]

Safe to run while the server is up (SQLite WAL; sessions are DB-backed, so
password resets take effect immediately). FACET_DB selects the database file,
same as for server.py.
"""
import argparse
import json
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

    p = sub.add_parser("list-reports", help="list submitted bug reports")
    p.add_argument("--status", default="open",
                   choices=["open", "reviewed", "all"],
                   help="filter by status (default: open)")

    p = sub.add_parser("show-report",
                       help="full report + all related game data")
    p.add_argument("id")
    p.add_argument("--json", action="store_true",
                   help="dump everything as JSON")

    p = sub.add_parser("resolve-report",
                       help="mark a report reviewed (or --reopen)")
    p.add_argument("id")
    p.add_argument("--reopen", action="store_true")

    args = ap.parse_args()
    storage.init_db()

    if args.cmd == "list-players":
        rows = storage.all_players(args.query)
        if not rows:
            print("no players found")
            return
        print(f"{'name':22s} {'act/fin':>8s} {'type':7s} {'admin':5s}"
              f" {'ratings (per game)':28s} last seen")
        for r in rows:
            print(f"{r['name']:22s}"
                  f" {r['active_games']:>3d}/{r['finished_games']:<4d}"
                  f" {'guest' if r['is_guest'] else 'account':7s}"
                  f" {'yes' if r['is_admin'] else '':5s}"
                  f" {(r['ratings'] or '-'):28s}"
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

    elif args.cmd == "list-reports":
        status = None if args.status == "all" else args.status
        rows = storage.list_reports(status)
        if not rows:
            print("no reports found")
            return
        print(f"{'id':16s} {'when':16s} {'status':8s} {'player':16s}"
              f" {'game':16s} description")
        for r in rows:
            desc = (r["description"] or "").replace("\n", " ")
            if len(desc) > 50:
                desc = desc[:47] + "..."
            print(f"{r['id']:16s} {r['created_at'][:16]:16s} {r['status']:8s}"
                  f" {(r['player_name'] or '-'):16s}"
                  f" {(r['game_id'] or '-'):16s} {desc}")

    elif args.cmd == "show-report":
        rep = storage.get_report(args.id)
        if not rep:
            sys.exit(f"error: no report '{args.id}'")
        bundle = _report_bundle(rep)
        if args.json:
            print(json.dumps(bundle, indent=2, default=str))
        else:
            _print_report(bundle)

    elif args.cmd == "resolve-report":
        status = "open" if args.reopen else "reviewed"
        if not storage.set_report_status(args.id, status):
            sys.exit(f"error: no report '{args.id}'")
        print(f"report {args.id} marked {status}")


def _report_bundle(rep):
    """A report plus every bit of related game data we can reconstruct."""
    out = {"report": rep, "client_info": None, "game": None,
           "players": None, "moves": None}
    if rep.get("client_info"):
        try:
            out["client_info"] = json.loads(rep["client_info"])
        except Exception:
            out["client_info"] = rep["client_info"]
    gid = rep.get("game_id")
    if gid:
        game = storage.get_game(gid)
        out["game"] = game
        if game:
            out["players"] = {
                "white": storage.get_player(game["white_id"]) if game["white_id"] else None,
                "black": storage.get_player(game["black_id"]) if game["black_id"] else None,
            }
            out["moves"] = storage.get_moves(gid)
    return out


def _print_report(b):
    r = b["report"]
    print(f"Report {r['id']}  [{r['status']}]")
    print(f"  submitted : {r['created_at']}  by {r.get('player_name') or '-'}")
    print(f"  game      : {r.get('game_id') or '(none)'}"
          f"  type={r.get('game_type') or '-'}")
    print("\nDescription:")
    print("  " + (r["description"] or "").replace("\n", "\n  "))
    ci = b["client_info"]
    if isinstance(ci, dict):
        print("\nClient context:")
        for k in ("board", "board_name", "modes", "difficulty", "type",
                  "your_side", "winner", "mode", "browser", "screen"):
            if k in ci:
                print(f"  {k:12s}: {ci[k]}")
        if ci.get("client_events"):
            print(f"  client_events: {len(ci['client_events'])}"
                  f" (use --json to see them)")
    g = b["game"]
    if g:
        pw = b["players"]["white"]; pb = b["players"]["black"]
        print("\nGame record:")
        print(f"  board={g['board']} modes={g['modes']} type="
              f"{'ai' if g['ai_difficulty'] else 'pvp'}"
              f" diff={g['ai_difficulty'] or '-'} rated={bool(g['rated'])}")
        print(f"  white={(pw['name'] if pw else 'AI')}"
              f"  black={(pb['name'] if pb else 'AI')}")
        print(f"  status={g['status']} winner={g['winner']}"
              f" win_type={g['win_type']}")
        print(f"  created={g['created_at']} last_move={g['last_move_at']}")
        moves = b["moves"] or []
        print(f"\nMoves ({len(moves)}):")
        for m in moves:
            if m.get("data"):  # backbone action JSON
                print(f"  {m['ply']:>3d}. {m['data']}")
            else:
                bump = " (bump)" if m["bumped"] else ""
                print(f"  {m['ply']:>3d}. ({m['fx']},{m['fy']})->"
                      f"({m['tx']},{m['ty']}){bump}")
    elif b["report"].get("game_id"):
        print("\n  (referenced game no longer exists)")


if __name__ == "__main__":
    main()
