"""
FACET game server (stdlib only).

Run:  python3 server.py        then open http://localhost:8000

API:
  POST /api/new        {difficulty?}          -> {id, state}
  GET  /api/state?id=                          -> {state}
  POST /api/move       {id, from:[x,y], to:[x,y]} -> {state, error?}
  POST /api/ai         {id}                     -> {state, move, info, draw_offer?}
  POST /api/draw       {id}                     -> {accepted, reason, state}
  GET  /api/log?id=                             -> {log:[...events]}
"""
import json
import uuid
import time
import traceback
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from pathlib import Path

from facet_engine import (canonical_board, make_board, BOARDS, CLASSIC_BOARDS,
                          DECAY_BOARDS, FOG_BOARDS, MOMENTUM_BOARDS, ai_move,
                          ai_evaluate_draw, ai_wants_draw, resolve_fog_move)
import storage
import service
from service import HUB, ApiError

# Legacy anonymous in-memory games (/api/*) are kept for older cached PWA
# clients; the SPA now uses the persistent /api/v1/* API below.
GAMES = {}            # id -> {"board": Board, "difficulty": str, "log": [...]}
LOCK = threading.Lock()
STATIC = Path(__file__).parent / "docs"

DIFF = {  # name -> (time_budget_seconds, max_depth)
    "easy":   (0.25, 2),
    "normal": (1.0, 4),
    "hard":   (2.5, 6),
}


def _ts():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _log_event(game, kind, **kw):
    entry = {"t": _ts(), "event": kind, **kw}
    game["log"].append(entry)


def serialize(board, draw_agreed=False, viewer=0):
    w = "draw" if draw_agreed else board.winner()
    fog = 'fog' in board.modes
    vis = board.visible_cells(viewer) if fog else None
    pieces = {}
    for (x, y), (o, m) in board.pieces.items():
        if fog and vis is not None and (x, y) not in vis and o != viewer:
            continue
        pieces[f"{x},{y}"] = {"owner": o, "monarch": m}
    if w is not None or (fog and board.to_move != viewer):
        legal = []
    else:
        # fog: legal moves come from the mover's own view, so the list never
        # reveals hidden pieces (slides through fog resolve as bumps on apply)
        src = board.fog_view(board.to_move) if fog else board
        legal = src.legal_moves(board.to_move)
    out = {
        "W": board.W, "H": board.H,
        "terrain": {f"{x},{y}": g for (x, y), g in board.terrain.items()},
        "pieces": pieces,
        "to_move": board.to_move,
        "thrones": [[x, y] for (x, y) in board.thrones()],
        "winner": w,
        "modes": list(board.modes),
        "legal": [[[fx, fy], [tx, ty]] for ((fx, fy), (tx, ty)) in legal],
    }
    if 'momentum' in board.modes:
        out["momentum"] = {f"{x},{y}": g for (x, y), g in board.linger.items()}
    return out


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[{_ts()}] {self.client_address[0]} {fmt % args}")

    def _cors(self):
        origin = self.headers.get("Origin", "*")
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send(self, code, obj=None, body=None, ctype="application/json"):
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", ctype)
        if obj is not None:
            body = json.dumps(obj).encode()
        if body is None:
            body = b""
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        if not n:
            return {}
        return json.loads(self.rfile.read(n) or b"{}")

    # ---- v1 API ----
    def _bearer(self):
        h = self.headers.get("Authorization", "")
        return h[7:] if h.startswith("Bearer ") else None

    def _auth(self):
        p = service.authenticate(self._bearer())
        if not p:
            raise ApiError(401, "authentication required")
        return p

    def _v1(self, method, parsed):
        try:
            data = self._read_json() if method == "POST" else {}
        except Exception:
            return self._send(400, {"error": "bad json"})
        try:
            return self._v1_route(method, parsed, data)
        except ApiError as e:
            return self._send(e.code, {"error": e.msg})
        except Exception:
            tb = traceback.format_exc()
            print(f"[{_ts()}] V1 ERROR {parsed.path}\n{tb}")
            return self._send(500, {"error": "internal error"})

    def _v1_route(self, method, parsed, data):
        path = parsed.path[len("/api/v1"):]
        parts = [p for p in path.split("/") if p]

        # ---- auth (rate-limited per IP) ----
        if parts and parts[0] == "auth" and method == "POST":
            if not service.AUTH_LIMITER.allow(self.client_address[0]):
                return self._send(429, {"error": "too many attempts, slow down"})
            action = parts[1] if len(parts) > 1 else ""
            if action == "register":
                return self._send(200, service.register(
                    data.get("name", ""), data.get("password", "")))
            if action == "login":
                return self._send(200, service.login(
                    data.get("name", ""), data.get("password", "")))
            if action == "guest":
                return self._send(200, service.guest())
            if action == "claim":
                return self._send(200, service.claim(
                    self._auth(), data.get("name", ""),
                    data.get("password", "")))
            if action == "recover":
                return self._send(200, service.recover(
                    data.get("name", ""), data.get("recovery_code", ""),
                    data.get("new_password", "")))
            if action == "rename":
                return self._send(200, service.rename(
                    self._auth(), data.get("name", "")))
            if action == "logout":
                service.logout(self._bearer())
                return self._send(200, {"ok": True})
            raise ApiError(404, "not found")

        if path == "/boards" and method == "GET":
            return self._send(200, {"boards": service.boards_payload()})

        if path == "/leaderboard" and method == "GET":
            rows = []
            for i, p in enumerate(storage.leaderboard()):
                rows.append({"pos": i + 1, "name": p["name"],
                             "rating": round(p["rating"]),
                             "rated_games": p["rated_games"],
                             "rank": service.rank_of(p["rating"],
                                                     p["rated_games"])})
            return self._send(200, {"leaderboard": rows})

        if len(parts) == 2 and parts[0] == "players" and method == "GET":
            p = storage.get_player_by_name(parts[1])
            if not p:
                raise ApiError(404, "no such player")
            return self._send(200, {
                "player": service.public_player(p),
                "stats": storage.player_stats(p["id"]),
                "rating_history": storage.rating_history(p["id"])})

        if path == "/me" and method == "GET":
            p = self._auth()
            storage.touch_player(p["id"])
            return self._send(200, {
                "player": service.public_player(p),
                "is_admin": bool(p["is_admin"]),
                "stats": storage.player_stats(p["id"]),
                "active_games": service.my_games_payload(p)})

        # ---- admin ----
        if parts and parts[0] == "admin":
            service.require_admin(self._auth())
            if path == "/admin/overview" and method == "GET":
                return self._send(200, {"stats": storage.overview_stats()})
            if path == "/admin/players" and method == "GET":
                qs = parse_qs(parsed.query)
                q = (qs.get("q") or [None])[0]
                return self._send(200, {"players": storage.all_players(q)})
            if path == "/admin/games" and method == "GET":
                return self._send(200, {"games": service.admin_games_payload()})
            if (len(parts) == 4 and parts[1] == "players"
                    and parts[3] == "reset_password" and method == "POST"):
                return self._send(200,
                                  service.admin_reset_password(parts[2]))
            if (len(parts) == 4 and parts[1] == "games"
                    and parts[3] == "abort" and method == "POST"):
                service.admin_abort_game(parts[2])
                return self._send(200, {"ok": True})
            raise ApiError(404, "not found")

        # ---- lobby ----
        if path == "/seeks" and method == "GET":
            return self._send(200, {"seeks": service.seeks_payload(self._auth())})
        if path == "/seeks" and method == "POST":
            p = self._auth()
            sid = service.create_seek(
                p, data.get("board", "classic"), data.get("modes", []),
                data.get("side_pref", "random"), data.get("rated", False),
                data.get("target"))
            return self._send(200, {"seek_id": sid})
        if (len(parts) == 3 and parts[0] == "seeks" and method == "POST"
                and parts[2] in ("accept", "cancel")):
            p = self._auth()
            if parts[2] == "cancel":
                seek = storage.get_seek(parts[1])
                if seek and seek["player_id"] == p["id"]:
                    storage.delete_seek(parts[1])
                return self._send(200, {"ok": True})
            gid = service.accept_seek(parts[1], p)
            game, side = HUB.load_game(gid, p)
            return self._send(200, {"game_id": gid,
                                    **HUB.state_payload(game, side)})

        # ---- games ----
        if path == "/games" and method == "POST":
            p = self._auth()
            gid = HUB.create_ai_game(
                p, data.get("board", "classic"), data.get("modes", []),
                data.get("difficulty", "normal"), data.get("human_side", 0))
            game, side = HUB.load_game(gid, p)
            return self._send(200, {"game_id": gid,
                                    **HUB.state_payload(game, side)})
        if path == "/games" and method == "GET":
            p = self._auth()
            qs = parse_qs(parsed.query)
            status = (qs.get("status") or ["active"])[0]
            if status == "active":
                return self._send(200, {"games": service.my_games_payload(p)})
            games = storage.list_games(p["id"], status="finished")
            out = [{"id": g["id"], "board": g["board"], "modes": g["modes"],
                    "type": "ai" if g["ai_difficulty"] else "pvp",
                    "white": g["white_name"] or "AI",
                    "black": g["black_name"] or "AI",
                    "your_side": HUB.side_of(g, p["id"]),
                    "winner": g["winner"], "win_type": g["win_type"],
                    "finished_at": g["finished_at"]} for g in games]
            return self._send(200, {"games": out})

        if len(parts) >= 3 and parts[0] == "games":
            p = self._auth()
            gid, action = parts[1], parts[2]
            if action == "state" and method == "GET":
                game, side = HUB.load_game(gid, p)
                qs = parse_qs(parsed.query)
                since_v = int((qs.get("v") or ["-1"])[0])
                wait = (qs.get("wait") or ["0"])[0] == "1"
                if (wait and game["status"] == "active"
                        and HUB.version(gid) <= since_v):
                    HUB.wait_for_change(gid, since_v)
                    game, side = HUB.load_game(gid, p)  # may have changed
                return self._send(200, HUB.state_payload(game, side))
            if action == "moves" and method == "GET":
                HUB.load_game(gid, p)  # participants only
                return self._send(200, {"moves": storage.get_moves(gid)})
            if method == "POST":
                with HUB.glock(gid):
                    game, side = HUB.load_game(gid, p)
                    if action == "move":
                        fr, to = data.get("from"), data.get("to")
                        mv, bumped = HUB.make_move(game, side, fr, to)
                        game = storage.get_game(gid)
                        return self._send(200, {
                            "move": [list(mv[0]), list(mv[1])],
                            "bumped": bumped,
                            **HUB.state_payload(game, side)})
                    if action == "ai":
                        t0 = time.monotonic()
                        out = HUB.ai_step(game, side)
                        if "info" in out:
                            out["info"]["time_s"] = round(
                                time.monotonic() - t0, 3)
                        game = storage.get_game(gid)
                        return self._send(200, {
                            **out, **HUB.state_payload(game, side)})
                    if action == "resign":
                        HUB.resign(game, side)
                        game = storage.get_game(gid)
                        return self._send(200, HUB.state_payload(game, side))
                    if action == "abort":
                        HUB.abort(game, side)
                        game = storage.get_game(gid)
                        return self._send(200, HUB.state_payload(game, side))
                    if action == "draw":
                        out = HUB.draw_action(game, side,
                                              data.get("action", "offer"))
                        game = storage.get_game(gid)
                        return self._send(200, {
                            **out, **HUB.state_payload(
                                game, side,
                                draw_agreed=out.get("draw_agreed", False))})
        raise ApiError(404, "not found")

    # ---- routing ----
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/v1/"):
            return self._v1("GET", parsed)
        if parsed.path in ("/", "/index.html"):
            self._serve_static("index.html", "text/html; charset=utf-8")
            return
        if parsed.path.startswith("/") and not parsed.path.startswith("/api/"):
            name = parsed.path.lstrip("/")
            ctypes = {".js": "application/javascript", ".css": "text/css",
                      ".png": "image/png", ".svg": "image/svg+xml"}
            ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""
            ctype = ctypes.get(ext, "application/octet-stream")
            if (STATIC / name).exists():
                return self._serve_static(name, ctype)

        if parsed.path == "/api/state":
            qs = parse_qs(parsed.query)
            gid = (qs.get("id") or [""])[0]
            with LOCK:
                g = GAMES.get(gid)
                if not g:
                    return self._send(404, {"error": "no such game"})
                return self._send(200, {"id": gid, "state": serialize(g["board"], g.get("draw_agreed", False), viewer=g.get("human", 0))})
        if parsed.path == "/api/boards":
            bl = {k: {"name": v["name"], "desc": v["desc"], "size": v["size"],
                       "supports_classic": k in CLASSIC_BOARDS,
                       "supports_decay": k in DECAY_BOARDS,
                       "supports_fog": k in FOG_BOARDS,
                       "supports_momentum": k in MOMENTUM_BOARDS}
                  for k, v in BOARDS.items()}
            return self._send(200, {"boards": bl})
        if parsed.path == "/api/log":
            qs = parse_qs(parsed.query)
            gid = (qs.get("id") or [""])[0]
            with LOCK:
                g = GAMES.get(gid)
                if not g:
                    return self._send(404, {"error": "no such game"})
                return self._send(200, {"id": gid, "log": list(g["log"])})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/v1/"):
            return self._v1("POST", parsed)
        try:
            data = self._read_json()
        except Exception:
            return self._send(400, {"error": "bad json"})

        if parsed.path == "/api/new":
            diff = data.get("difficulty", "normal")
            if diff not in DIFF:
                diff = "normal"
            board_id = data.get("board", "classic")
            if board_id not in BOARDS:
                board_id = "classic"
            req_modes = set(data.get("modes", []))
            modes = set()
            if 'decay' in req_modes and board_id in DECAY_BOARDS:
                modes.add('decay')
            if 'fog' in req_modes and board_id in FOG_BOARDS:
                modes.add('fog')
            # momentum is mutually exclusive with decay/fog (validation data)
            if ('momentum' in req_modes and board_id in MOMENTUM_BOARDS
                    and not modes):
                modes.add('momentum')
            if not modes and board_id not in CLASSIC_BOARDS:
                board_id = "classic"
            human = data.get("human_side", 0)
            if human not in (0, 1):
                human = 0
            gid = uuid.uuid4().hex[:12]
            with LOCK:
                g = {"board": make_board(board_id, modes=modes),
                     "difficulty": diff, "human": human, "log": []}
                GAMES[gid] = g
                _log_event(g, "new_game", difficulty=diff, board=board_id,
                           modes=list(modes), human_side=human, game_id=gid)
                return self._send(200, {"id": gid, "difficulty": diff,
                                        "modes": list(modes),
                                        "human_side": human,
                                        "state": serialize(g["board"], viewer=human)})

        if parsed.path == "/api/move":
            gid = data.get("id")
            fr = data.get("from"); to = data.get("to")
            with LOCK:
                g = GAMES.get(gid)
                if not g:
                    return self._send(404, {"error": "no such game"})
                board = g["board"]
                human = g.get("human", 0)
                if board.winner() is not None:
                    _log_event(g, "error", msg="move after game over",
                               move={"from": fr, "to": to})
                    return self._send(400, {"error": "game over",
                                            "state": serialize(board, viewer=human)})
                mv = ((fr[0], fr[1]), (to[0], to[1]))
                src = (board.fog_view(board.to_move)
                       if 'fog' in board.modes else board)
                legal = set(src.legal_moves(board.to_move))
                if mv not in legal:
                    _log_event(g, "error", msg="illegal move",
                               move={"from": fr, "to": to},
                               player=board.to_move)
                    return self._send(400, {"error": "illegal move",
                                            "state": serialize(board, viewer=human)})
                mv, bumped = resolve_fog_move(board, mv, board.to_move)
                board.apply(mv)
                _log_event(g, "move", player=board.to_move ^ 1,
                           move={"from": fr, "to": list(mv[1])}, bumped=bumped)
                w = board.winner()
                if w is not None:
                    _log_event(g, "game_over", winner=w)
                return self._send(200, {"state": serialize(board, viewer=human),
                                        "move": [list(mv[0]), list(mv[1])],
                                        "bumped": bumped})

        if parsed.path == "/api/ai":
            gid = data.get("id")
            with LOCK:
                g = GAMES.get(gid)
                if not g:
                    return self._send(404, {"error": "no such game"})
                board = g["board"]
                diff = g["difficulty"]
                human = g.get("human", 0)
                ai_side = human ^ 1
            if board.winner() is not None:
                return self._send(200, {"state": serialize(board, viewer=human),
                                        "move": None})
            budget, depth_limit = DIFF[diff]
            try:
                t0 = time.monotonic()
                mv, info = ai_move(board, time_budget=budget, max_depth=depth_limit)
                elapsed = round(time.monotonic() - t0, 3)
                info["time_s"] = elapsed
            except Exception:
                tb = traceback.format_exc()
                print(f"[{_ts()}] AI ERROR game={gid}\n{tb}")
                with LOCK:
                    _log_event(g, "error", msg="ai crash", traceback=tb)
                return self._send(500, {"error": "AI error, see game log",
                                        "state": serialize(board, viewer=human)})
            with LOCK:
                if mv is not None:
                    board.apply(mv)
                move_out = ([list(mv[0]), list(mv[1])] if mv else None)
                _log_event(g, "ai_move", move=move_out, info=info)
                w = board.winner()
                if w is not None:
                    _log_event(g, "game_over", winner=w)
                resp = {"state": serialize(board, viewer=human),
                        "move": move_out, "info": info}
                # AI may propose a draw if it thinks it's losing badly
                if w is None and ai_wants_draw(board, ai_side, time_budget=0.3,
                                               max_depth=3):
                    resp["draw_offer"] = True
                    _log_event(g, "ai_draw_offer")
                return self._send(200, resp)

        if parsed.path == "/api/draw":
            gid = data.get("id")
            with LOCK:
                g = GAMES.get(gid)
                if not g:
                    return self._send(404, {"error": "no such game"})
                board = g["board"]
                human = g.get("human", 0)
                if board.winner() is not None:
                    return self._send(400, {"error": "game over",
                                            "state": serialize(board, viewer=human)})
            budget_t, depth_t = DIFF.get(g["difficulty"], DIFF["normal"])
            accepted, reason = ai_evaluate_draw(board, human ^ 1,
                                                time_budget=min(budget_t, 0.5),
                                                max_depth=min(depth_t, 4))
            with LOCK:
                _log_event(g, "draw_offer", by="human",
                           accepted=accepted, reason=reason)
                if accepted:
                    g["draw_agreed"] = True
                    _log_event(g, "game_over", winner="draw")
                return self._send(200, {"accepted": accepted, "reason": reason,
                                        "state": serialize(board, viewer=human),
                                        "draw_agreed": accepted})

        return self._send(404, {"error": "not found"})

    def _serve_static(self, name, ctype):
        p = STATIC / name
        if not p.exists():
            return self._send(404, body=b"missing static")
        self._send(200, body=p.read_bytes(), ctype=ctype)


def main():
    import os
    storage.init_db()
    service.promote_admin_from_env()
    service.start_sweeper(int(os.environ.get("FACET_SWEEP_SECONDS", 60)))
    port = int(os.environ.get("PORT", 8000))
    httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"[{_ts()}] FACET server on http://localhost:{port}"
          f" (db: {storage.DB_PATH})")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
