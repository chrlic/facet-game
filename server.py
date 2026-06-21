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

from facet_engine import canonical_board, make_board, BOARDS, ai_move, ai_evaluate_draw, ai_wants_draw

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


def serialize(board, draw_agreed=False):
    w = "draw" if draw_agreed else board.winner()
    return {
        "W": board.W, "H": board.H,
        "terrain": {f"{x},{y}": g for (x, y), g in board.terrain.items()},
        "pieces": {f"{x},{y}": {"owner": o, "monarch": m}
                   for (x, y), (o, m) in board.pieces.items()},
        "to_move": board.to_move,
        "thrones": [[x, y] for (x, y) in board.thrones()],
        "winner": w,
        "legal": ([] if w is not None else
                  [[[fx, fy], [tx, ty]]
                   for ((fx, fy), (tx, ty)) in board.legal_moves(board.to_move)]),
    }


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

    # ---- routing ----
    def do_GET(self):
        parsed = urlparse(self.path)
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
                return self._send(200, {"id": gid, "state": serialize(g["board"], g.get("draw_agreed", False))})
        if parsed.path == "/api/boards":
            bl = {k: {"name": v["name"], "desc": v["desc"], "size": v["size"]}
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
            gid = uuid.uuid4().hex[:12]
            with LOCK:
                g = {"board": make_board(board_id), "difficulty": diff, "log": []}
                GAMES[gid] = g
                _log_event(g, "new_game", difficulty=diff, board=board_id, game_id=gid)
                return self._send(200, {"id": gid, "difficulty": diff,
                                        "state": serialize(g["board"])})

        if parsed.path == "/api/move":
            gid = data.get("id")
            fr = data.get("from"); to = data.get("to")
            with LOCK:
                g = GAMES.get(gid)
                if not g:
                    return self._send(404, {"error": "no such game"})
                board = g["board"]
                if board.winner() is not None:
                    _log_event(g, "error", msg="move after game over",
                               move={"from": fr, "to": to})
                    return self._send(400, {"error": "game over",
                                            "state": serialize(board)})
                mv = ((fr[0], fr[1]), (to[0], to[1]))
                legal = set(board.legal_moves(board.to_move))
                if mv not in legal:
                    _log_event(g, "error", msg="illegal move",
                               move={"from": fr, "to": to},
                               player=board.to_move)
                    return self._send(400, {"error": "illegal move",
                                            "state": serialize(board)})
                board.apply(mv)
                _log_event(g, "move", player=board.to_move ^ 1,
                           move={"from": fr, "to": to})
                w = board.winner()
                if w is not None:
                    _log_event(g, "game_over", winner=w)
                return self._send(200, {"state": serialize(board)})

        if parsed.path == "/api/ai":
            gid = data.get("id")
            with LOCK:
                g = GAMES.get(gid)
                if not g:
                    return self._send(404, {"error": "no such game"})
                board = g["board"]
                diff = g["difficulty"]
            if board.winner() is not None:
                return self._send(200, {"state": serialize(board), "move": None})
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
                                        "state": serialize(board)})
            with LOCK:
                if mv is not None:
                    board.apply(mv)
                move_out = ([list(mv[0]), list(mv[1])] if mv else None)
                _log_event(g, "ai_move", move=move_out, info=info)
                w = board.winner()
                if w is not None:
                    _log_event(g, "game_over", winner=w)
                resp = {"state": serialize(board),
                        "move": move_out, "info": info}
                # AI may propose a draw if it thinks it's losing badly
                if w is None and ai_wants_draw(board, 1, time_budget=0.3,
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
                if board.winner() is not None:
                    return self._send(400, {"error": "game over",
                                            "state": serialize(board)})
            budget_t, depth_t = DIFF.get(g["difficulty"], DIFF["normal"])
            accepted, reason = ai_evaluate_draw(board, 1,
                                                time_budget=min(budget_t, 0.5),
                                                max_depth=min(depth_t, 4))
            with LOCK:
                _log_event(g, "draw_offer", by="human",
                           accepted=accepted, reason=reason)
                if accepted:
                    g["draw_agreed"] = True
                    _log_event(g, "game_over", winner="draw")
                return self._send(200, {"accepted": accepted, "reason": reason,
                                        "state": serialize(board),
                                        "draw_agreed": accepted})

        return self._send(404, {"error": "not found"})

    def _serve_static(self, name, ctype):
        p = STATIC / name
        if not p.exists():
            return self._send(404, body=b"missing static")
        self._send(200, body=p.read_bytes(), ctype=ctype)


def main():
    import os
    port = int(os.environ.get("PORT", 8000))
    httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"[{_ts()}] FACET server on http://localhost:{port}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
