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
import os
import time
import traceback
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from pathlib import Path

import storage
import service
from service import HUB, ApiError

STATIC = Path(__file__).parent / "docs"
STATIC_ROOT = STATIC.resolve()

MAX_BODY = 64 * 1024  # reject larger request bodies (memory-DoS guard)

# Behind a reverse proxy the socket peer is the proxy, so its forwarded
# client-IP header must be trusted for per-IP rate limiting. Enable with
# FACET_TRUST_PROXY=1 and have nginx set:  proxy_set_header X-Real-IP $remote_addr;
TRUST_PROXY = os.environ.get("FACET_TRUST_PROXY", "").lower() \
    not in ("", "0", "false", "no")

# Cross-origin API access is refused unless the Origin is in this allowlist.
# The SPA is served same-origin and needs nothing here; set
# FACET_ALLOWED_ORIGINS (comma-separated) only for a genuine cross-origin caller.
ALLOWED_ORIGINS = {o.strip() for o in
                   os.environ.get("FACET_ALLOWED_ORIGINS", "").split(",")
                   if o.strip()}


def _ts():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Handler(BaseHTTPRequestHandler):
    timeout = 30  # drop idle/slow sockets (slowloris guard)

    def log_message(self, fmt, *args):
        print(f"[{_ts()}] {self._client_ip()} {fmt % args}")

    def _client_ip(self):
        if TRUST_PROXY:
            xri = self.headers.get("X-Real-IP")
            if xri:
                return xri.strip()
            xff = self.headers.get("X-Forwarded-For")
            if xff:
                # nginx's $proxy_add_x_forwarded_for appends the true peer
                # last, so the final entry is the one it vouches for
                return xff.split(",")[-1].strip()
        return self.client_address[0]

    def _cors(self):
        origin = self.headers.get("Origin")
        if origin and origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers",
                             "Content-Type, Authorization")

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
        if n <= 0:
            return {}
        if n > MAX_BODY:
            self.close_connection = True  # don't try to keep a half-read socket
            raise ApiError(413, "request body too large")
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
        except ApiError as e:
            return self._send(e.code, {"error": e.msg})
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
            if not service.AUTH_LIMITER.allow(self._client_ip()):
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
            if not service.ACTION_LIMITER.allow(p["id"]):
                raise ApiError(429, "too many requests, slow down")
            sid = service.create_seek(
                p, data.get("board", "classic"), data.get("modes", []),
                data.get("side_pref", "random"), data.get("rated", False),
                data.get("target"),
                game_type=data.get("game_type", "facet"))
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
            if not service.ACTION_LIMITER.allow(p["id"]):
                raise ApiError(429, "too many requests, slow down")
            gt = data.get("game_type", "facet")
            if gt not in service.GAME_TYPES:
                raise ApiError(400, "unknown game type")
            gid = HUB.create_ai_game(
                p, data.get("board", "classic"), data.get("modes", []),
                data.get("difficulty", "normal"), data.get("human_side", 0),
                game_type=gt)
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
            # AI search is the one expensive operation — cap it per user so a
            # scripted client can't monopolise CPU
            if (action == "ai" and method == "POST"
                    and not service.AI_LIMITER.allow(p["id"])):
                raise ApiError(429, "too many AI requests, slow down")
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
                        if game.get("game_type") == "backbone":
                            act = HUB.make_action(game, side,
                                                  data.get("action"))
                            game = storage.get_game(gid)
                            return self._send(200, {
                                "move": act,
                                **HUB.state_payload(game, side)})
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
            # resolve and confirm the target stays inside docs/ — otherwise
            # "../" sequences would escape the static root (path traversal)
            try:
                target = (STATIC / name).resolve()
                target.relative_to(STATIC_ROOT)
            except (ValueError, OSError):
                return self._send(404, {"error": "not found"})
            if target.is_file():
                ctypes = {".js": "application/javascript", ".css": "text/css",
                          ".png": "image/png", ".svg": "image/svg+xml",
                          ".html": "text/html; charset=utf-8",
                          ".json": "application/json",
                          ".webmanifest": "application/manifest+json"}
                ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""
                ctype = ctypes.get(ext, "application/octet-stream")
                return self._serve_static(name, ctype)
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/v1/"):
            return self._v1("POST", parsed)
        return self._send(404, {"error": "not found"})

    def _serve_static(self, name, ctype):
        p = STATIC / name
        if not p.exists():
            return self._send(404, body=b"missing static")
        self._send(200, body=p.read_bytes(), ctype=ctype)


def main():
    storage.init_db()
    service.promote_admin_from_env()
    service.start_sweeper(int(os.environ.get("FACET_SWEEP_SECONDS", 60)))
    port = int(os.environ.get("PORT", 8000))
    # bind 0.0.0.0 by default (Docker); set HOST=127.0.0.1 when nginx runs on
    # the same host, so the app port isn't reachable from outside
    host = os.environ.get("HOST", "0.0.0.0")
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True  # don't let lingering connections block shutdown
    print(f"[{_ts()}] FACET server on http://{host}:{port}"
          f" (db: {storage.DB_PATH})")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
