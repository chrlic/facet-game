"""SQLite persistence layer for the FACET game server.

ALL SQL lives in this module (see SERVER_PLAN.md). Rules that keep the
backend swappable for a standard DB engine later:
  - ANSI-portable SQL only (pragmas are the sole SQLite-specific code)
  - application-generated ids (uuid hex), no auto-increment semantics
  - callers never see sqlite3 objects, only dicts/values

Set FACET_DB to override the database file location (default: facet.db
next to this file).
"""
import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

DB_PATH = os.environ.get("FACET_DB", str(Path(__file__).parent / "facet.db"))

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS players(
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE COLLATE NOCASE,
  pass_hash TEXT, pass_salt TEXT,
  recovery_hash TEXT,
  created_at TEXT NOT NULL, last_seen TEXT NOT NULL,
  rating REAL NOT NULL DEFAULT 1200,
  rd REAL NOT NULL DEFAULT 350,
  rated_games INTEGER NOT NULL DEFAULT 0,
  is_guest INTEGER NOT NULL DEFAULT 0,
  is_admin INTEGER NOT NULL DEFAULT 0);

CREATE TABLE IF NOT EXISTS sessions(
  token_hash TEXT PRIMARY KEY,
  player_id TEXT NOT NULL REFERENCES players(id),
  created_at TEXT NOT NULL, expires_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS games(
  id TEXT PRIMARY KEY,
  board TEXT NOT NULL, modes TEXT NOT NULL,
  white_id TEXT REFERENCES players(id),
  black_id TEXT REFERENCES players(id),
  ai_difficulty TEXT,
  rated INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL,                 -- active|finished|aborted
  winner TEXT, win_type TEXT,
  draw_offer_by INTEGER,
  move_allowance_s INTEGER NOT NULL DEFAULT 259200,
  created_at TEXT NOT NULL, finished_at TEXT,
  last_move_at TEXT NOT NULL);

CREATE INDEX IF NOT EXISTS idx_games_white ON games(white_id, status);
CREATE INDEX IF NOT EXISTS idx_games_black ON games(black_id, status);
CREATE INDEX IF NOT EXISTS idx_games_status ON games(status, last_move_at);

CREATE TABLE IF NOT EXISTS moves(
  game_id TEXT NOT NULL REFERENCES games(id),
  ply INTEGER NOT NULL,
  fx INTEGER NOT NULL, fy INTEGER NOT NULL,
  tx INTEGER NOT NULL, ty INTEGER NOT NULL,
  bumped INTEGER NOT NULL DEFAULT 0,
  played_at TEXT NOT NULL,
  PRIMARY KEY (game_id, ply));

CREATE TABLE IF NOT EXISTS seeks(
  id TEXT PRIMARY KEY,
  player_id TEXT NOT NULL REFERENCES players(id),
  board TEXT NOT NULL, modes TEXT NOT NULL,
  side_pref TEXT NOT NULL DEFAULT 'random',
  rated INTEGER NOT NULL DEFAULT 0,
  target_player TEXT,
  created_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS rating_events(
  game_id TEXT NOT NULL REFERENCES games(id),
  player_id TEXT NOT NULL REFERENCES players(id),
  rating_before REAL NOT NULL, rating_after REAL NOT NULL,
  applied_at TEXT NOT NULL,
  PRIMARY KEY (game_id, player_id));
"""


def _conn():
    c = getattr(_local, "conn", None)
    if c is None:
        c = sqlite3.connect(DB_PATH, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA busy_timeout=5000")
        _local.conn = c
    return c


def init_db():
    c = _conn()
    c.executescript(SCHEMA)
    c.commit()


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _iso_plus(seconds):
    return (datetime.now(timezone.utc)
            + timedelta(seconds=seconds)).isoformat(timespec="milliseconds")


def new_id():
    return uuid.uuid4().hex[:16]


def _row(r):
    return dict(r) if r is not None else None


# ---------------- players ----------------
def create_player(name, pass_hash=None, pass_salt=None, recovery_hash=None,
                  is_guest=0):
    c = _conn()
    pid = new_id()
    t = now_iso()
    c.execute(
        "INSERT INTO players(id, name, pass_hash, pass_salt, recovery_hash,"
        " created_at, last_seen, is_guest) VALUES (?,?,?,?,?,?,?,?)",
        (pid, name, pass_hash, pass_salt, recovery_hash, t, t, is_guest))
    c.commit()
    return pid


def get_player(pid):
    r = _conn().execute("SELECT * FROM players WHERE id=?", (pid,)).fetchone()
    return _row(r)


def get_player_by_name(name):
    r = _conn().execute("SELECT * FROM players WHERE name=?",
                        (name,)).fetchone()
    return _row(r)


def touch_player(pid):
    c = _conn()
    c.execute("UPDATE players SET last_seen=? WHERE id=?", (now_iso(), pid))
    c.commit()


def claim_guest(pid, name, pass_hash, pass_salt, recovery_hash):
    c = _conn()
    c.execute(
        "UPDATE players SET name=?, pass_hash=?, pass_salt=?,"
        " recovery_hash=?, is_guest=0 WHERE id=?",
        (name, pass_hash, pass_salt, recovery_hash, pid))
    c.commit()


def set_password(pid, pass_hash, pass_salt):
    c = _conn()
    c.execute("UPDATE players SET pass_hash=?, pass_salt=? WHERE id=?",
              (pass_hash, pass_salt, pid))
    c.commit()


def rename_player(pid, name):
    c = _conn()
    c.execute("UPDATE players SET name=? WHERE id=?", (name, pid))
    c.commit()


def set_admin(pid, flag=1):
    c = _conn()
    c.execute("UPDATE players SET is_admin=? WHERE id=?", (flag, pid))
    c.commit()


def all_players(q=None, limit=500):
    sql = ("SELECT p.id, p.name, p.rating, p.rated_games, p.is_guest,"
           " p.is_admin, p.created_at, p.last_seen,"
           " (SELECT COUNT(*) FROM games g WHERE g.status='active'"
           "   AND (g.white_id=p.id OR g.black_id=p.id)) AS active_games,"
           " (SELECT COUNT(*) FROM games g WHERE g.status='finished'"
           "   AND (g.white_id=p.id OR g.black_id=p.id)) AS finished_games"
           " FROM players p")
    args = []
    if q:
        sql += " WHERE p.name LIKE ?"
        args.append(f"%{q}%")
    sql += " ORDER BY p.last_seen DESC LIMIT ?"
    args.append(limit)
    return [dict(r) for r in _conn().execute(sql, args).fetchall()]


def all_active_games(limit=200):
    rs = _conn().execute(
        "SELECT g.*, wp.name AS white_name, bp.name AS black_name,"
        " (SELECT COUNT(*) FROM moves m WHERE m.game_id=g.id) AS ply"
        " FROM games g"
        " LEFT JOIN players wp ON wp.id=g.white_id"
        " LEFT JOIN players bp ON bp.id=g.black_id"
        " WHERE g.status='active' ORDER BY g.last_move_at DESC LIMIT ?",
        (limit,)).fetchall()
    out = []
    for r in rs:
        g = dict(r)
        g["modes"] = json.loads(g["modes"])
        out.append(g)
    return out


def overview_stats():
    c = _conn()
    day_ago = (datetime.now(timezone.utc)
               - timedelta(days=1)).isoformat(timespec="milliseconds")

    def one(sql, *args):
        return c.execute(sql, args).fetchone()[0]

    return {
        "players_total": one("SELECT COUNT(*) FROM players"),
        "players_guests": one("SELECT COUNT(*) FROM players WHERE is_guest=1"),
        "players_new_24h": one(
            "SELECT COUNT(*) FROM players WHERE created_at > ?", day_ago),
        "games_active": one("SELECT COUNT(*) FROM games WHERE status='active'"),
        "games_active_pvp": one(
            "SELECT COUNT(*) FROM games WHERE status='active'"
            " AND ai_difficulty IS NULL"),
        "games_finished": one(
            "SELECT COUNT(*) FROM games WHERE status='finished'"),
        "games_aborted": one(
            "SELECT COUNT(*) FROM games WHERE status='aborted'"),
        "games_finished_24h": one(
            "SELECT COUNT(*) FROM games WHERE status='finished'"
            " AND finished_at > ?", day_ago),
        "games_rated": one("SELECT COUNT(*) FROM games WHERE rated=1"),
        "moves_total": one("SELECT COUNT(*) FROM moves"),
        "moves_24h": one("SELECT COUNT(*) FROM moves WHERE played_at > ?",
                         day_ago),
        "open_seeks": one("SELECT COUNT(*) FROM seeks"),
        "sessions_active": one(
            "SELECT COUNT(*) FROM sessions WHERE expires_at > ?",
            now_iso()),
    }


def leaderboard(limit=50):
    rs = _conn().execute(
        "SELECT name, rating, rated_games, is_guest FROM players"
        " WHERE rated_games >= 1"
        " ORDER BY rating DESC, rated_games DESC LIMIT ?",
        (limit,)).fetchall()
    return [dict(r) for r in rs]


# ---------------- sessions ----------------
SESSION_TTL_S = 30 * 24 * 3600


def create_session(token_hash, player_id):
    c = _conn()
    c.execute(
        "INSERT INTO sessions(token_hash, player_id, created_at, expires_at)"
        " VALUES (?,?,?,?)",
        (token_hash, player_id, now_iso(), _iso_plus(SESSION_TTL_S)))
    c.commit()


def get_session_player(token_hash):
    r = _conn().execute(
        "SELECT p.*, s.expires_at AS session_expires FROM sessions s"
        " JOIN players p ON p.id = s.player_id WHERE s.token_hash=?",
        (token_hash,)).fetchone()
    if r is None or r["session_expires"] < now_iso():
        return None
    return _row(r)


def refresh_session(token_hash):
    c = _conn()
    c.execute("UPDATE sessions SET expires_at=? WHERE token_hash=?",
              (_iso_plus(SESSION_TTL_S), token_hash))
    c.commit()


def delete_session(token_hash):
    c = _conn()
    c.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))
    c.commit()


def delete_player_sessions(player_id):
    c = _conn()
    c.execute("DELETE FROM sessions WHERE player_id=?", (player_id,))
    c.commit()


def sweep_sessions():
    c = _conn()
    c.execute("DELETE FROM sessions WHERE expires_at < ?", (now_iso(),))
    c.commit()


# ---------------- games ----------------
def create_game(board, modes, white_id, black_id, ai_difficulty=None,
                rated=0, move_allowance_s=259200):
    c = _conn()
    gid = new_id()
    t = now_iso()
    c.execute(
        "INSERT INTO games(id, board, modes, white_id, black_id,"
        " ai_difficulty, rated, status, move_allowance_s, created_at,"
        " last_move_at) VALUES (?,?,?,?,?,?,?,'active',?,?,?)",
        (gid, board, json.dumps(sorted(modes)), white_id, black_id,
         ai_difficulty, rated, move_allowance_s, t, t))
    c.commit()
    return gid


def get_game(gid):
    r = _conn().execute("SELECT * FROM games WHERE id=?", (gid,)).fetchone()
    g = _row(r)
    if g:
        g["modes"] = json.loads(g["modes"])
    return g


def record_move(gid, ply, fr, to, bumped):
    c = _conn()
    t = now_iso()
    c.execute(
        "INSERT INTO moves(game_id, ply, fx, fy, tx, ty, bumped, played_at)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (gid, ply, fr[0], fr[1], to[0], to[1], 1 if bumped else 0, t))
    c.execute("UPDATE games SET last_move_at=? WHERE id=?", (t, gid))
    c.commit()


def get_moves(gid):
    rs = _conn().execute(
        "SELECT ply, fx, fy, tx, ty, bumped, played_at FROM moves"
        " WHERE game_id=? ORDER BY ply", (gid,)).fetchall()
    return [dict(r) for r in rs]


def set_draw_offer(gid, side):
    c = _conn()
    c.execute("UPDATE games SET draw_offer_by=? WHERE id=?", (side, gid))
    c.commit()


def abort_game(gid):
    """Abort an active game (no result, no stats). Returns True if aborted."""
    c = _conn()
    cur = c.execute(
        "UPDATE games SET status='aborted', finished_at=?, draw_offer_by=NULL"
        " WHERE id=? AND status='active'", (now_iso(), gid))
    c.commit()
    return cur.rowcount > 0


def abandoned_ai_games(max_idle_s):
    """Active AI games idle longer than max_idle_s (housekeeping sweep)."""
    rs = _conn().execute(
        "SELECT id, last_move_at FROM games"
        " WHERE status='active' AND ai_difficulty IS NOT NULL").fetchall()
    out = []
    now = datetime.now(timezone.utc)
    for r in rs:
        last = datetime.fromisoformat(r["last_move_at"])
        if (now - last).total_seconds() > max_idle_s:
            out.append(r["id"])
    return out


def finish_game(gid, winner, win_type):
    """Finish a game; returns True only for the transition that won the race
    (callers gate one-time effects like rating application on this)."""
    c = _conn()
    cur = c.execute(
        "UPDATE games SET status='finished', winner=?, win_type=?,"
        " finished_at=?, draw_offer_by=NULL WHERE id=? AND status='active'",
        (str(winner), win_type, now_iso(), gid))
    c.commit()
    return cur.rowcount > 0


def apply_rating(game_id, player_id, before, after):
    c = _conn()
    c.execute(
        "INSERT INTO rating_events(game_id, player_id, rating_before,"
        " rating_after, applied_at) VALUES (?,?,?,?,?)",
        (game_id, player_id, before, after, now_iso()))
    c.execute(
        "UPDATE players SET rating=?, rated_games=rated_games+1 WHERE id=?",
        (after, player_id))
    c.commit()


def get_rating_events(game_id):
    rs = _conn().execute(
        "SELECT * FROM rating_events WHERE game_id=?", (game_id,)).fetchall()
    return [dict(r) for r in rs]


def rating_history(player_id, limit=50):
    rs = _conn().execute(
        "SELECT rating_before, rating_after, applied_at FROM rating_events"
        " WHERE player_id=? ORDER BY applied_at DESC LIMIT ?",
        (player_id, limit)).fetchall()
    return [dict(r) for r in rs]


def last_rated_game_between(a_id, b_id):
    r = _conn().execute(
        "SELECT * FROM games WHERE rated=1 AND"
        " ((white_id=? AND black_id=?) OR (white_id=? AND black_id=?))"
        " ORDER BY created_at DESC LIMIT 1",
        (a_id, b_id, b_id, a_id)).fetchone()
    return _row(r)


def list_games(player_id, status=None, limit=50):
    q = ("SELECT g.*, wp.name AS white_name, bp.name AS black_name"
         " FROM games g"
         " LEFT JOIN players wp ON wp.id = g.white_id"
         " LEFT JOIN players bp ON bp.id = g.black_id"
         " WHERE (g.white_id=? OR g.black_id=?)")
    args = [player_id, player_id]
    if status:
        q += " AND g.status=?"
        args.append(status)
    q += " ORDER BY g.last_move_at DESC LIMIT ?"
    args.append(limit)
    out = []
    for r in _conn().execute(q, args).fetchall():
        g = dict(r)
        g["modes"] = json.loads(g["modes"])
        out.append(g)
    return out


def expired_pvp_games():
    """Active PvP games whose side to move has exceeded the allowance."""
    rs = _conn().execute(
        "SELECT id, last_move_at, move_allowance_s FROM games"
        " WHERE status='active' AND ai_difficulty IS NULL"
        " AND white_id IS NOT NULL AND black_id IS NOT NULL").fetchall()
    out = []
    now = datetime.now(timezone.utc)
    for r in rs:
        last = datetime.fromisoformat(r["last_move_at"])
        if (now - last).total_seconds() > r["move_allowance_s"]:
            out.append(r["id"])
    return out


def player_stats(player_id):
    rs = _conn().execute(
        "SELECT winner, win_type, white_id, black_id, ai_difficulty"
        " FROM games WHERE status='finished'"
        " AND (white_id=? OR black_id=?)",
        (player_id, player_id)).fetchall()
    stats = {"pvp": {"w": 0, "l": 0, "d": 0},
             "ai": {"w": 0, "l": 0, "d": 0, "by_difficulty": {}}}
    for r in rs:
        side = 0 if r["white_id"] == player_id else 1
        bucket = stats["ai"] if r["ai_difficulty"] else stats["pvp"]
        if r["winner"] == "draw":
            bucket["d"] += 1
        elif r["winner"] == str(side):
            bucket["w"] += 1
        else:
            bucket["l"] += 1
        if r["ai_difficulty"]:
            d = stats["ai"]["by_difficulty"].setdefault(
                r["ai_difficulty"], {"w": 0, "l": 0, "d": 0})
            k = ("d" if r["winner"] == "draw"
                 else "w" if r["winner"] == str(side) else "l")
            d[k] += 1
    return stats


# ---------------- seeks ----------------
def create_seek(player_id, board, modes, side_pref, rated, target_player):
    c = _conn()
    sid = new_id()
    c.execute(
        "INSERT INTO seeks(id, player_id, board, modes, side_pref, rated,"
        " target_player, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (sid, player_id, board, json.dumps(sorted(modes)), side_pref,
         rated, target_player, now_iso()))
    c.commit()
    return sid


def get_seek(sid):
    r = _conn().execute("SELECT * FROM seeks WHERE id=?", (sid,)).fetchone()
    s = _row(r)
    if s:
        s["modes"] = json.loads(s["modes"])
    return s


def list_seeks(for_player_id):
    """Open seeks visible to a player: all public ones + challenges to them."""
    rs = _conn().execute(
        "SELECT s.*, p.name AS player_name, p.rating, p.is_guest FROM seeks s"
        " JOIN players p ON p.id = s.player_id"
        " WHERE s.target_player IS NULL OR s.target_player=? OR s.player_id=?"
        " ORDER BY s.created_at DESC LIMIT 100",
        (for_player_id, for_player_id)).fetchall()
    out = []
    for r in rs:
        s = dict(r)
        s["modes"] = json.loads(s["modes"])
        out.append(s)
    return out


def delete_seek(sid):
    """Delete a seek; returns True if it existed (atomic claim for accept)."""
    c = _conn()
    cur = c.execute("DELETE FROM seeks WHERE id=?", (sid,))
    c.commit()
    return cur.rowcount > 0


def delete_player_seeks(player_id):
    c = _conn()
    c.execute("DELETE FROM seeks WHERE player_id=?", (player_id,))
    c.commit()


def sweep_seeks(max_age_days=7):
    c = _conn()
    cutoff = (datetime.now(timezone.utc)
              - timedelta(days=max_age_days)).isoformat(timespec="milliseconds")
    c.execute("DELETE FROM seeks WHERE created_at < ?", (cutoff,))
    c.commit()
