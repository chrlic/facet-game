"""FACET server service layer: auth, game hub, lobby, background sweeper.

Sits between server.py (HTTP) and storage.py (SQL). Holds the in-memory
game cache — memory is a cache, the database is the truth: any game state
can be rebuilt by replaying its move log through the deterministic engine.
"""
import hashlib
import json
import os
import re
import secrets
import threading
import time

import storage
import backbone_engine
from facet_engine import (BOARDS, CLASSIC_BOARDS, DECAY_BOARDS, FOG_BOARDS,
                          MOMENTUM_BOARDS, make_board, ai_move,
                          ai_evaluate_draw, ai_wants_draw, resolve_fog_move)

GAME_TYPES = ("facet", "backbone")

DIFF = {  # difficulty -> (time_budget_seconds, max_depth)
    "easy":   (0.25, 2),
    "normal": (1.0, 4),
    "hard":   (2.5, 6),
}

NAME_RE = re.compile(r"^[A-Za-z0-9_-]{3,20}$")
MOVE_ALLOWANCE_S = int(os.environ.get("FACET_MOVE_SECONDS", 3 * 24 * 3600))
AI_ABANDON_S = int(os.environ.get("FACET_AI_ABANDON_SECONDS", 7 * 24 * 3600))
LONG_POLL_S = 25


class ApiError(Exception):
    def __init__(self, code, msg):
        self.code = code
        self.msg = msg


# ---------------- passwords / tokens ----------------
def _hash_password(password, salt):
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt),
                          n=2 ** 14, r=8, p=1).hex()


def _check_password(player, password):
    if not player or not player["pass_hash"]:
        return False
    return secrets.compare_digest(
        player["pass_hash"], _hash_password(password, player["pass_salt"]))


def _token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _validate_credentials(name, password):
    if not NAME_RE.match(name or ""):
        raise ApiError(400, "name must be 3-20 chars: letters, digits, _ or -")
    if name.lower().startswith("guest-"):
        raise ApiError(400, "names starting with 'guest-' are reserved")
    if not password or len(password) < 6:
        raise ApiError(400, "password must be at least 6 characters")


def _new_credentials(password):
    salt = secrets.token_hex(16)
    recovery = secrets.token_hex(8)
    return (_hash_password(password, salt), salt,
            hashlib.sha256(recovery.encode()).hexdigest(), recovery)


# ---------------- ratings & ranks ----------------
RANKS = [(1900, "Monarch"), (1700, "Throne"), (1500, "Tower"),
         (1300, "Spire"), (1100, "Gate"), (0, "Field")]
PLACEMENT_GAMES = 10


def rank_of(rating, rated_games):
    if rated_games < PLACEMENT_GAMES:
        return "Unranked"
    for threshold, name in RANKS:
        if rating >= threshold:
            return name
    return "Field"


def _k_factor(rated_games):
    return 40 if rated_games < 15 else 20


def apply_ratings(game, winner):
    """Elo update for a finished rated PvP game — on the ladder for THIS
    game_type (FACET and Backbone keep independent ratings). Idempotent via
    the rating_events primary key + finish_game's one-time gate."""
    gt = game.get("game_type", "facet")
    white = storage.get_player(game["white_id"])
    black = storage.get_player(game["black_id"])
    if not white or not black:
        return
    wr = storage.get_rating(white["id"], gt)
    br = storage.get_rating(black["id"], gt)
    sw = 0.5 if winner == "draw" else (1.0 if str(winner) == "0" else 0.0)
    ew = 1.0 / (1.0 + 10 ** ((br["rating"] - wr["rating"]) / 400.0))
    new_w = wr["rating"] + _k_factor(wr["rated_games"]) * (sw - ew)
    new_b = br["rating"] + _k_factor(br["rated_games"]) * ((1 - sw) - (1 - ew))
    storage.apply_rating(game["id"], white["id"], gt, wr["rating"], new_w)
    storage.apply_rating(game["id"], black["id"], gt, br["rating"], new_b)


def public_player(p):
    # one rating/rank per game type; each UI displays its own game's entry
    ratings = storage.get_all_ratings(p["id"])
    per_game = {}
    for gt in GAME_TYPES:
        r = ratings.get(gt, {"rating": storage.DEFAULT_RATING, "rated_games": 0})
        per_game[gt] = {"rating": round(r["rating"]),
                        "rated_games": r["rated_games"],
                        "rank": rank_of(r["rating"], r["rated_games"])}
    return {"name": p["name"], "ratings": per_game,
            "is_guest": bool(p["is_guest"]),
            "created_at": p["created_at"]}


# ---------------- rate limiting ----------------
class RateLimiter:
    def __init__(self, limit, window_s):
        self.limit = limit
        self.window = window_s
        self.hits = {}
        self.lock = threading.Lock()

    def allow(self, key):
        now = time.time()
        with self.lock:
            q = [t for t in self.hits.get(key, []) if now - t < self.window]
            if len(q) >= self.limit:
                self.hits[key] = q
                return False
            q.append(now)
            self.hits[key] = q
            return True

    def prune(self):
        """Drop keys whose window has fully expired (bounds memory growth)."""
        now = time.time()
        with self.lock:
            for k in list(self.hits):
                q = [t for t in self.hits[k] if now - t < self.window]
                if q:
                    self.hits[k] = q
                else:
                    del self.hits[k]


# per-IP: account actions (register/login/guest/claim/recover/rename/logout)
AUTH_LIMITER = RateLimiter(limit=10, window_s=60)
# per-user: AI move requests — the one CPU-heavy call (env-tunable)
AI_LIMITER = RateLimiter(
    limit=int(os.environ.get("FACET_AI_RATE", 30)), window_s=60)
# per-user: game and seek creation
ACTION_LIMITER = RateLimiter(
    limit=int(os.environ.get("FACET_ACTION_RATE", 30)), window_s=60)
# per-user: bug-report submission (low frequency, spam guard)
REPORT_LIMITER = RateLimiter(
    limit=int(os.environ.get("FACET_REPORT_RATE", 5)), window_s=60)


# ---------------- auth ----------------
def register(name, password):
    _validate_credentials(name, password)
    if storage.get_player_by_name(name):
        raise ApiError(409, "name already taken")
    ph, salt, rh, recovery = _new_credentials(password)
    pid = storage.create_player(name, ph, salt, rh)
    token = _issue_session(pid)
    return {"token": token, "recovery_code": recovery,
            "player": public_player(storage.get_player(pid))}


def login(name, password):
    p = storage.get_player_by_name(name)
    if not _check_password(p, password):
        raise ApiError(401, "wrong name or password")
    token = _issue_session(p["id"])
    return {"token": token, "player": public_player(p)}


def guest():
    for _ in range(20):
        name = f"guest-{secrets.token_hex(2)}"
        if not storage.get_player_by_name(name):
            break
    pid = storage.create_player(name, is_guest=1)
    token = _issue_session(pid)
    return {"token": token, "player": public_player(storage.get_player(pid))}


def claim(player, name, password):
    if not player["is_guest"]:
        raise ApiError(400, "account is already registered")
    _validate_credentials(name, password)
    if storage.get_player_by_name(name):
        raise ApiError(409, "name already taken")
    ph, salt, rh, recovery = _new_credentials(password)
    storage.claim_guest(player["id"], name, ph, salt, rh)
    return {"recovery_code": recovery,
            "player": public_player(storage.get_player(player["id"]))}


def recover(name, recovery_code, new_password):
    p = storage.get_player_by_name(name)
    if not p or not p["recovery_hash"] or not secrets.compare_digest(
            p["recovery_hash"],
            hashlib.sha256((recovery_code or "").encode()).hexdigest()):
        raise ApiError(401, "wrong name or recovery code")
    if not new_password or len(new_password) < 6:
        raise ApiError(400, "password must be at least 6 characters")
    salt = secrets.token_hex(16)
    storage.set_password(p["id"], _hash_password(new_password, salt), salt)
    storage.delete_player_sessions(p["id"])
    token = _issue_session(p["id"])
    return {"token": token, "player": public_player(p)}


def rename(player, new_name):
    if player["is_guest"]:
        raise ApiError(403, "guests set their name by claiming the account")
    if not NAME_RE.match(new_name or ""):
        raise ApiError(400, "name must be 3-20 chars: letters, digits, _ or -")
    if new_name.lower().startswith("guest-"):
        raise ApiError(400, "names starting with 'guest-' are reserved")
    existing = storage.get_player_by_name(new_name)
    if existing and existing["id"] != player["id"]:
        raise ApiError(409, "name already taken")
    try:
        storage.rename_player(player["id"], new_name)
    except Exception:  # unique-constraint race
        raise ApiError(409, "name already taken")
    return {"player": public_player(storage.get_player(player["id"]))}


# ---------------- admin ----------------
def promote_admin_from_env():
    """FACET_ADMIN=<name> grants admin to that player at startup (register
    the account first, then set the env var and restart)."""
    name = os.environ.get("FACET_ADMIN")
    if not name:
        return
    p = storage.get_player_by_name(name)
    if p and not p["is_admin"]:
        storage.set_admin(p["id"])
        print(f"[admin] promoted '{p['name']}'")


def require_admin(player):
    if not player or not player["is_admin"]:
        raise ApiError(403, "admin access required")


def admin_reset_password(target_name):
    p = storage.get_player_by_name(target_name)
    if not p:
        raise ApiError(404, "no such player")
    if p["is_guest"]:
        raise ApiError(400, "guest accounts have no password")
    temp = secrets.token_hex(6)
    salt = secrets.token_hex(16)
    storage.set_password(p["id"], _hash_password(temp, salt), salt)
    storage.delete_player_sessions(p["id"])
    return {"name": p["name"], "temp_password": temp}


def admin_abort_game(gid):
    game = storage.get_game(gid)
    if not game:
        raise ApiError(404, "no such game")
    if game["status"] != "active":
        raise ApiError(400, "game is not active")
    storage.abort_game(gid)
    HUB.forget(gid)
    HUB.bump(gid)


def admin_games_payload():
    out = []
    for g in storage.all_active_games():
        out.append({"id": g["id"], "board": g["board"], "modes": g["modes"],
                    "type": "ai" if g["ai_difficulty"] else "pvp",
                    "difficulty": g["ai_difficulty"],
                    "white": g["white_name"] or "AI",
                    "black": g["black_name"] or "AI",
                    "rated": bool(g["rated"]), "ply": g["ply"],
                    "created_at": g["created_at"],
                    "last_move_at": g["last_move_at"]})
    return out


def _issue_session(pid):
    token = secrets.token_hex(32)
    storage.create_session(_token_hash(token), pid)
    return token


def authenticate(token):
    if not token:
        return None
    th = _token_hash(token)
    p = storage.get_session_player(th)
    if p:
        storage.refresh_session(th)
    return p


def logout(token):
    storage.delete_session(_token_hash(token))


# ---------------- boards / modes ----------------
def boards_payload():
    return {k: {"name": v["name"], "desc": v["desc"], "size": v["size"],
                "supports_classic": k in CLASSIC_BOARDS,
                "supports_decay": k in DECAY_BOARDS,
                "supports_fog": k in FOG_BOARDS,
                "supports_momentum": k in MOMENTUM_BOARDS}
            for k, v in BOARDS.items()}


def validate_setup(board_id, req_modes):
    if board_id not in BOARDS:
        raise ApiError(400, "unknown board")
    modes = set()
    req = set(req_modes or [])
    if "decay" in req and board_id in DECAY_BOARDS:
        modes.add("decay")
    if "fog" in req and board_id in FOG_BOARDS:
        modes.add("fog")
    if "momentum" in req and board_id in MOMENTUM_BOARDS and not modes:
        modes.add("momentum")
    if not modes and board_id not in CLASSIC_BOARDS:
        raise ApiError(400, "board requires a mode it supports")
    return modes


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
        # fog: the mover's legal list is derived from THEIR vision — sending
        # it to the opponent would leak hidden piece positions
        legal = []
    else:
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


# ---------------- game hub ----------------
class GameHub:
    """In-memory cache of live boards + long-poll wakeups + persistence."""

    def __init__(self):
        self.lock = threading.Lock()
        self.boards = {}      # gid -> Board (cache; truth is the move log)
        self.conds = {}       # gid -> threading.Condition
        self.versions = {}    # gid -> int (bumped on any observable change)
        self.glocks = {}      # gid -> mutation lock (one writer per game)

    def glock(self, gid):
        with self.lock:
            return self.glocks.setdefault(gid, threading.Lock())

    # -- infrastructure --
    def _cond(self, gid):
        with self.lock:
            if gid not in self.conds:
                self.conds[gid] = threading.Condition()
                self.versions[gid] = 0
            return self.conds[gid]

    def bump(self, gid):
        cond = self._cond(gid)
        with cond:
            self.versions[gid] += 1
            cond.notify_all()

    def version(self, gid):
        self._cond(gid)
        return self.versions[gid]

    def board_for(self, game):
        gid = game["id"]
        with self.lock:
            b = self.boards.get(gid)
        if b is not None:
            return b
        if game.get("game_type") == "backbone":
            b = backbone_engine.Board()
            for m in storage.get_moves(gid):
                b.apply(json.loads(m["data"]))
        else:
            b = make_board(game["board"], modes=set(game["modes"]))
            for m in storage.get_moves(gid):
                b.apply(((m["fx"], m["fy"]), (m["tx"], m["ty"])))
        with self.lock:
            self.boards[gid] = b
        return b

    def forget(self, gid):
        with self.lock:
            self.boards.pop(gid, None)

    def prune_inactive(self):
        """Drop cached boards + long-poll bookkeeping for games that are no
        longer active, so these dicts don't grow without bound over the life
        of the process. Terminal games reload lazily if anyone views them."""
        with self.lock:
            gids = list(self.boards.keys() | self.conds.keys())
        for gid in gids:
            g = storage.get_game(gid)
            if g and g["status"] == "active":
                continue
            with self.lock:
                self.boards.pop(gid, None)
                self.conds.pop(gid, None)
                self.versions.pop(gid, None)
                self.glocks.pop(gid, None)

    # -- game access --
    def load_game(self, gid, player):
        game = storage.get_game(gid)
        if not game:
            raise ApiError(404, "no such game")
        side = self.side_of(game, player["id"])
        if side is None:
            raise ApiError(403, "not your game")
        return game, side

    @staticmethod
    def side_of(game, player_id):
        if game["white_id"] == player_id:
            return 0
        if game["black_id"] == player_id:
            return 1
        return None

    @staticmethod
    def is_ai_game(game):
        return game["ai_difficulty"] is not None

    def meta(self, game, side, board):
        return {
            "id": game["id"], "board": game["board"], "modes": game["modes"],
            "game_type": game.get("game_type", "facet"),
            "type": "ai" if self.is_ai_game(game) else "pvp",
            "difficulty": game["ai_difficulty"],
            "white": game.get("white_name") or ("AI" if game["white_id"] is None else "?"),
            "black": game.get("black_name") or ("AI" if game["black_id"] is None else "?"),
            "your_side": side,
            "status": game["status"],
            "winner": game["winner"], "win_type": game["win_type"],
            "draw_offer_by": game["draw_offer_by"],
            "rated": bool(game["rated"]),
            "ply": len(storage.get_moves(game["id"])),
            "last_move_at": game["last_move_at"],
        }

    def _names(self, game):
        g = dict(game)
        for key, nkey in (("white_id", "white_name"), ("black_id", "black_name")):
            if g.get(key):
                p = storage.get_player(g[key])
                g[nkey] = p["name"] if p else "?"
        return g

    def state_payload(self, game, side, draw_agreed=False):
        game = self._names(game)
        board = self.board_for(game)
        if game.get("game_type") == "backbone":
            st = backbone_engine.serialize(board)
            if draw_agreed:
                st["winner"] = "draw"
        else:
            st = serialize(board, draw_agreed=draw_agreed, viewer=side)
        if game["status"] == "finished":
            # resign/forfeit/agreement aren't visible on the board itself
            st["winner"] = ("draw" if game["winner"] == "draw"
                            else int(game["winner"]))
            st["legal"] = []
        elif game["status"] == "aborted":
            st["legal"] = []
        meta = self.meta(game, side, board)
        if game["status"] == "finished" and game["rated"]:
            my_id = game["white_id"] if side == 0 else game["black_id"]
            for ev in storage.get_rating_events(game["id"]):
                if ev["player_id"] == my_id:
                    meta["your_rating_change"] = round(
                        ev["rating_after"] - ev["rating_before"], 1)
        return {"state": st, "meta": meta, "v": self.version(game["id"])}

    # -- creation --
    def create_ai_game(self, player, board_id, modes, difficulty, human_side,
                       game_type="facet"):
        if game_type == "backbone":
            board_id, modes = "standard", set()
            if difficulty not in backbone_engine.DIFF:
                difficulty = "normal"
        else:
            modes = validate_setup(board_id, modes)
            if difficulty not in DIFF:
                difficulty = "normal"
        human_side = 1 if human_side == 1 else 0
        white = player["id"] if human_side == 0 else None
        black = player["id"] if human_side == 1 else None
        gid = storage.create_game(board_id, modes, white, black,
                                  ai_difficulty=difficulty,
                                  move_allowance_s=MOVE_ALLOWANCE_S,
                                  game_type=game_type)
        return gid

    def create_pvp_game(self, seek, accepter):
        game_type = seek.get("game_type", "facet")
        if game_type == "backbone":
            modes = set()
        else:
            modes = validate_setup(seek["board"], seek["modes"])
        seeker_id = seek["player_id"]
        pref = seek["side_pref"]
        if pref == "white":
            seeker_side = 0
        elif pref == "black":
            seeker_side = 1
        else:
            seeker_side = secrets.randbelow(2)
        if seek["rated"]:
            # rated rematches alternate colors — the first-mover advantage
            # is measurable, so the ladder must average it out
            prev = storage.last_rated_game_between(seeker_id, accepter["id"])
            if prev:
                seeker_side = 1 if prev["white_id"] == seeker_id else 0
        ids = [None, None]
        ids[seeker_side] = seeker_id
        ids[seeker_side ^ 1] = accepter["id"]
        gid = storage.create_game(seek["board"], modes, ids[0], ids[1],
                                  rated=seek["rated"],
                                  move_allowance_s=MOVE_ALLOWANCE_S,
                                  game_type=game_type)
        return gid

    # -- play --
    def make_action(self, game, side, action):
        """Backbone: apply one action dict for the side to move."""
        if game["status"] != "active":
            raise ApiError(400, "game over")
        board = self.board_for(game)
        if board.to_move != side:
            raise ApiError(400, "not your turn")
        if not isinstance(action, dict) or not board.is_legal(action, side):
            raise ApiError(400, "illegal action")
        ply = len(storage.get_moves(game["id"]))
        board.apply(action)
        storage.record_move(game["id"], ply, (0, 0), (0, 0), False,
                            data=json.dumps(action))
        if board.winner is not None:
            self._finish_backbone(game, board)
        self.bump(game["id"])
        return action

    def _finish_backbone(self, game, board):
        w = board.winner
        if w == "draw":
            self.finish(game, "draw", "stalemate")
        else:
            wt = ("victory" if board.score(w) >= board.target_vp
                  else "stalemate")
            self.finish(game, w, wt)

    def ai_step_backbone(self, game, side):
        board = self.board_for(game)
        ai_side = 0 if game["white_id"] is None else 1
        if game["status"] != "active":
            return {"move": None}
        if board.to_move != ai_side:
            raise ApiError(400, "not the AI's turn")
        act = backbone_engine.ai_move(board, game["ai_difficulty"])
        explain = backbone_engine.explain_action(board, act, ai_side)
        ply = len(storage.get_moves(game["id"]))
        board.apply(act)
        storage.record_move(game["id"], ply, (0, 0), (0, 0), False,
                            data=json.dumps(act))
        if board.winner is not None:
            self._finish_backbone(game, board)
        self.bump(game["id"])
        return {"move": act, "info": {"difficulty": game["ai_difficulty"],
                                      "explain": explain}}

    def make_move(self, game, side, fr, to):
        if game["status"] != "active":
            raise ApiError(400, "game over")
        board = self.board_for(game)
        if board.to_move != side:
            raise ApiError(400, "not your turn")
        mv = ((fr[0], fr[1]), (to[0], to[1]))
        src = board.fog_view(side) if 'fog' in board.modes else board
        if mv not in set(src.legal_moves(side)):
            raise ApiError(400, "illegal move")
        mv, bumped = resolve_fog_move(board, mv, side)
        ply = len(storage.get_moves(game["id"]))
        board.apply(mv)
        storage.record_move(game["id"], ply, mv[0], mv[1], bumped)
        if game["draw_offer_by"] is not None:
            storage.set_draw_offer(game["id"], None)  # moving declines
        w = board.winner()
        if w is not None:
            self._finish_by_board(game, board, w)
        self.bump(game["id"])
        return mv, bumped

    def ai_step(self, game, side):
        """Compute and apply one AI move in an AI game. Returns response dict."""
        if not self.is_ai_game(game):
            raise ApiError(400, "not an AI game")
        if game["status"] != "active":
            return {"move": None}
        if game.get("game_type") == "backbone":
            return self.ai_step_backbone(game, side)
        board = self.board_for(game)
        ai_side = 0 if game["white_id"] is None else 1
        if board.to_move != ai_side:
            raise ApiError(400, "not the AI's turn")
        budget, depth = DIFF[game["ai_difficulty"]]
        mv, info = ai_move(board, time_budget=budget, max_depth=depth)
        out = {"move": None, "info": info}
        if mv is not None:
            ply = len(storage.get_moves(game["id"]))
            board.apply(mv)
            storage.record_move(game["id"], ply, mv[0], mv[1], False)
            out["move"] = [list(mv[0]), list(mv[1])]
        w = board.winner()
        if w is not None:
            self._finish_by_board(game, board, w)
        elif mv is not None and ai_wants_draw(board, ai_side,
                                              time_budget=0.3, max_depth=3):
            out["draw_offer"] = True
        self.bump(game["id"])
        return out

    def finish(self, game, winner, win_type):
        """Single exit point for all game endings; applies ratings once."""
        if not storage.finish_game(game["id"], winner, win_type):
            return
        if game["rated"] and not self.is_ai_game(game):
            try:
                apply_ratings(game, winner)
            except Exception as e:  # never lose the game result to a rating bug
                print(f"[ratings] error for game {game['id']}: {e}")

    def _finish_by_board(self, game, board, w):
        if w == "draw":
            self.finish(game, "draw", "stalemate")
            return
        loser = w ^ 1
        if not board.monarch_alive(loser):
            wt = "regicide"
        elif board.piece_count(loser) == 1:
            wt = "elimination"
        else:
            wt = "coronation"
        self.finish(game, w, wt)

    def resign(self, game, side):
        if game["status"] != "active":
            raise ApiError(400, "game over")
        self.finish(game, side ^ 1, "resign")
        self.bump(game["id"])

    def abort(self, game, side):
        """End a game without a result. AI games: any time. PvP: only before
        the second move — after that, ending the game means resigning."""
        if game["status"] != "active":
            raise ApiError(400, "game over")
        if not self.is_ai_game(game):
            ply = len(storage.get_moves(game["id"]))
            if ply >= 2:
                raise ApiError(400, "game is under way — resign instead")
        storage.abort_game(game["id"])
        self.forget(game["id"])
        self.bump(game["id"])

    def draw_action(self, game, side, action):
        if game["status"] != "active":
            raise ApiError(400, "game over")
        if self.is_ai_game(game):
            if game.get("game_type") == "backbone":
                # the backbone AI has no draw evaluation: play it out
                if action == "accept":
                    self.finish(game, "draw", "agreed")
                    self.bump(game["id"])
                    return {"accepted": True, "draw_agreed": True}
                return {"accepted": False, "draw_agreed": False,
                        "reason": "The AI wants to play on."}
            # AI answers immediately, like the legacy endpoint
            board = self.board_for(game)
            ai_side = 0 if game["white_id"] is None else 1
            budget, depth = DIFF[game["ai_difficulty"]]
            accepted, reason = ai_evaluate_draw(
                board, ai_side, time_budget=min(budget, 0.5),
                max_depth=min(depth, 4))
            if action == "accept":  # human accepts an AI offer
                accepted, reason = True, "Draw agreed."
            if accepted:
                self.finish(game, "draw", "agreed")
                self.bump(game["id"])
            return {"accepted": accepted, "reason": reason,
                    "draw_agreed": accepted}
        # PvP: persistent offer / accept / decline
        if action == "offer":
            storage.set_draw_offer(game["id"], side)
            self.bump(game["id"])
            return {"offered": True}
        if action == "accept":
            if game["draw_offer_by"] is None or game["draw_offer_by"] == side:
                raise ApiError(400, "no draw offer to accept")
            self.finish(game, "draw", "agreed")
            self.bump(game["id"])
            return {"accepted": True, "draw_agreed": True}
        if action == "decline":
            storage.set_draw_offer(game["id"], None)
            self.bump(game["id"])
            return {"declined": True}
        raise ApiError(400, "unknown draw action")

    def wait_for_change(self, gid, since_v, timeout=LONG_POLL_S):
        cond = self._cond(gid)
        deadline = time.time() + timeout
        with cond:
            while self.versions[gid] <= since_v:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                cond.wait(remaining)

    # -- sweeper --
    def sweep_forfeits(self):
        for gid in storage.expired_pvp_games():
            game = storage.get_game(gid)
            if not game or game["status"] != "active":
                continue
            board = self.board_for(game)
            self.finish(game, board.to_move ^ 1, "forfeit")
            self.bump(gid)
        # abandoned AI games quietly clean themselves up
        for gid in storage.abandoned_ai_games(AI_ABANDON_S):
            if storage.abort_game(gid):
                self.forget(gid)
                self.bump(gid)


HUB = GameHub()


def start_sweeper(interval_s=60):
    def loop():
        while True:
            time.sleep(interval_s)
            try:
                HUB.sweep_forfeits()
                HUB.prune_inactive()
                storage.sweep_sessions()
                storage.sweep_seeks()
                AUTH_LIMITER.prune()
                AI_LIMITER.prune()
                ACTION_LIMITER.prune()
                REPORT_LIMITER.prune()
            except Exception as e:  # keep the sweeper alive
                print(f"[sweeper] error: {e}")
    t = threading.Thread(target=loop, daemon=True, name="facet-sweeper")
    t.start()
    return t


# ---------------- lobby ----------------
def create_seek(player, board_id, modes, side_pref, rated, target_name,
                game_type="facet"):
    if game_type not in GAME_TYPES:
        raise ApiError(400, "unknown game type")
    if game_type == "backbone":
        board_id, modes = "standard", set()
    else:
        modes = validate_setup(board_id, modes)
    if rated and player["is_guest"]:
        raise ApiError(403, "guests play casual only — claim your account"
                            " to play rated games")
    if side_pref not in ("white", "black", "random"):
        side_pref = "random"
    target_id = None
    if target_name:
        t = storage.get_player_by_name(target_name)
        if not t:
            raise ApiError(404, "no such player")
        if t["id"] == player["id"]:
            raise ApiError(400, "cannot challenge yourself")
        target_id = t["id"]
    sid = storage.create_seek(player["id"], board_id, modes, side_pref,
                              1 if rated else 0, target_id,
                              game_type=game_type)
    return sid


def accept_seek(sid, accepter):
    seek = storage.get_seek(sid)
    if not seek:
        raise ApiError(404, "seek no longer available")
    if seek["player_id"] == accepter["id"]:
        raise ApiError(400, "cannot accept your own seek")
    if seek["target_player"] and seek["target_player"] != accepter["id"]:
        raise ApiError(403, "this challenge is for someone else")
    if seek["rated"] and accepter["is_guest"]:
        raise ApiError(403, "guests play casual only — claim your account"
                            " to play rated games")
    if not storage.delete_seek(sid):  # atomic claim: only one accepter wins
        raise ApiError(404, "seek no longer available")
    gid = HUB.create_pvp_game(seek, accepter)
    # a new game consumes both players' remaining seeks — prevents crossed
    # double-games when two players offer and accept simultaneously
    storage.delete_player_seeks(seek["player_id"])
    storage.delete_player_seeks(accepter["id"])
    return gid


def seeks_payload(player):
    out = []
    for s in storage.list_seeks(player["id"]):
        mine = s["player_id"] == player["id"]
        # the color the VIEWER would play if they accepted this seek
        if s["side_pref"] == "white":
            you_play = "black"
        elif s["side_pref"] == "black":
            you_play = "white"
        else:
            you_play = "random"
        if s["rated"] and not mine:
            # rated rematches alternate colors, overriding the preference
            prev = storage.last_rated_game_between(s["player_id"],
                                                   player["id"])
            if prev:
                you_play = ("white" if prev["white_id"] == s["player_id"]
                            else "black")
        gt = s.get("game_type", "facet")
        out.append({"id": s["id"], "player": s["player_name"],
                    "rating": round(storage.get_rating(s["player_id"], gt)["rating"]),
                    "is_guest": bool(s["is_guest"]),
                    "game_type": s.get("game_type", "facet"),
                    "board": s["board"], "modes": s["modes"],
                    "side_pref": s["side_pref"], "you_play": you_play,
                    "rated": bool(s["rated"]),
                    "mine": mine,
                    "direct": s["target_player"] is not None,
                    "created_at": s["created_at"]})
    return out


# ---------------- bug reports ----------------
MAX_REPORT_DESC = 4000
MAX_REPORT_INFO = 40000


def submit_report(player, description, game_id=None, client_info=None):
    description = (description or "").strip()
    if not description:
        raise ApiError(400, "a description is required")
    if len(description) > MAX_REPORT_DESC:
        description = description[:MAX_REPORT_DESC]
    # only attach a game the reporter actually took part in
    game_type = None
    if game_id:
        g = storage.get_game(game_id)
        if g and HUB.side_of(g, player["id"]) is not None:
            game_type = g.get("game_type", "facet")
        else:
            game_id = None  # not their game (or gone) — drop the reference
    info_json = None
    if client_info is not None:
        info_json = json.dumps(client_info, separators=(",", ":"))[:MAX_REPORT_INFO]
    rid = storage.create_report(player["id"], game_id, game_type,
                                description, info_json)
    return {"report_id": rid}


def my_games_payload(player):
    out = []
    for g in storage.list_games(player["id"], status="active"):
        side = HUB.side_of(g, player["id"])
        board = HUB.board_for(g)
        opp = g["black_name"] if side == 0 else g["white_name"]
        out.append({"id": g["id"], "board": g["board"], "modes": g["modes"],
                    "game_type": g.get("game_type", "facet"),
                    "type": "ai" if g["ai_difficulty"] else "pvp",
                    "opponent": opp or "AI",
                    "your_side": side,
                    "your_turn": board.to_move == side,
                    "draw_offer_by": g["draw_offer_by"],
                    "ply": len(storage.get_moves(g["id"])),
                    "created_at": g["created_at"],
                    "last_move_at": g["last_move_at"]})
    return out
