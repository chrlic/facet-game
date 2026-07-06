# FACET Game Server — Architecture Plan

Turning the current single-process AI server into a full game server with
accounts, matchmaking, human-vs-human play, persistent history, and a ranked
ladder — while staying administratively trivial to run.

## Goals

- Player registration and login, plus friction-free guest play
- Offering / accepting games (lobby seeks, direct challenges, quick match)
- Games against the AI, recorded per player
- Persistent score history and a rating-based rank ladder
- Storage embedded in the Python process (zero administration), swappable
  for a standard DB engine later without touching game logic

## Non-goals (v1)

- Real-time chess clocks (turn-based with inactivity forfeit instead)
- Horizontal scaling (single process + SQLite serves hundreds of concurrent
  games; revisit only if that ceiling is ever reached)
- Email infrastructure (verification, password reset via mail)
- Anti-engine-cheating beyond reporting (unsolvable at this scale)

## Architecture at a glance

```
Browser (Vue SPA, docs/)          Fly.io machine (or any host)
┌──────────────────┐   HTTPS   ┌──────────────────────────────┐
│ auth / lobby /    │ ───────► │ server.py (stdlib HTTP)       │
│ game screens      │  polling │  ├─ api.py     (routing/auth) │
│ (LocalAdapter     │ ◄─────── │  ├─ engine     (facet_engine) │
│  offline mode     │          │  ├─ lobby.py   (seeks/match)  │
│  stays untouched) │          │  ├─ ratings.py (Elo/ranks)    │
└──────────────────┘          │  └─ storage.py (SQLite DAL)   │
                               │        │ facet.db (WAL)       │
                               └────────┼──────────────────────┘
                                        └── Fly volume + nightly snapshot
```

Key principles:

1. **Server-authoritative** — clients send intents; the engine validates
   every move (already true today).
2. **Event-sourced games** — every move is persisted as it happens. The
   engine is deterministic (proven by the Python↔JS parity harness), so any
   game state can be rebuilt by replaying its move log. Server restarts no
   longer lose games; replays and analysis come free.
3. **Thin storage layer** — one module (`storage.py`) owns all SQL. Swapping
   SQLite for Postgres later means reimplementing that one module.

## Storage

**Engine: SQLite via stdlib `sqlite3`.** Single file `facet.db`, WAL mode
(concurrent readers + single writer fits a turn-based game perfectly),
`PRAGMA foreign_keys=ON`. Zero admin: backup = copy one file (later:
Litestream for continuous replication if wanted).

**Swappability rules** kept from day one:
- All SQL lives in `storage.py` behind plain functions
  (`create_player`, `record_move`, `finish_game`, `top_players`, …)
- ANSI-portable SQL only (no SQLite-specific syntax beyond pragmas)
- IDs are application-generated (uuid hex, as today) — no reliance on
  auto-increment semantics
- A `DATABASE_URL` env var selects the backend; `sqlite:///facet.db` default

### Schema (v1)

```sql
players(
  id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL COLLATE NOCASE,
  pass_hash TEXT, pass_salt TEXT,          -- NULL for guests
  recovery_hash TEXT,                      -- one-time recovery code
  created_at TEXT, last_seen TEXT,
  rating REAL DEFAULT 1200, rd REAL DEFAULT 350,  -- rating deviation
  rated_games INTEGER DEFAULT 0,
  is_guest INTEGER DEFAULT 0, is_admin INTEGER DEFAULT 0)

sessions(
  token TEXT PRIMARY KEY, player_id TEXT REFERENCES players(id),
  created_at TEXT, expires_at TEXT)

games(
  id TEXT PRIMARY KEY, board TEXT, modes TEXT,      -- modes: json list
  white_id TEXT REFERENCES players(id),             -- NULL = AI
  black_id TEXT REFERENCES players(id),
  ai_difficulty TEXT,                               -- NULL for PvP
  rated INTEGER, status TEXT,      -- open|active|finished|aborted
  winner TEXT,                     -- '0'|'1'|'draw'|NULL
  win_type TEXT,                   -- regicide|coronation|elimination|resign|forfeit|agreed
  created_at TEXT, finished_at TEXT, last_move_at TEXT)

moves(
  game_id TEXT REFERENCES games(id), ply INTEGER,
  fx INTEGER, fy INTEGER, tx INTEGER, ty INTEGER,
  bumped INTEGER DEFAULT 0, played_at TEXT,
  PRIMARY KEY (game_id, ply))

seeks(
  id TEXT PRIMARY KEY, player_id TEXT, board TEXT, modes TEXT,
  side_pref TEXT,                  -- white|black|random
  rated INTEGER, min_rating REAL, max_rating REAL,
  target_player TEXT,              -- NULL = open seek; set = direct challenge
  created_at TEXT)

rating_events(
  game_id TEXT, player_id TEXT, rating_before REAL, rating_after REAL,
  applied_at TEXT, PRIMARY KEY (game_id, player_id))
```

Hot games also live in an in-memory cache (`{game_id: Board}`), rebuilt lazily
from the move log on demand — memory is a cache, the DB is the truth.

## Accounts & auth (stdlib only)

- **Registration**: username + password. Hash with `hashlib.scrypt`
  (stdlib, memory-hard). On signup, show a one-time recovery code (hashed in
  DB) as the no-email password-reset path.
- **Sessions**: `secrets.token_hex(32)` bearer token, stored hashed,
  30-day sliding expiry. Sent as `Authorization: Bearer` (SPA keeps it in
  localStorage) — avoids CSRF machinery that cookies would need.
- **Guests**: one click creates `guest-xxxx` with a session and no password;
  can play AI games and casual PvP. "Claim account" upgrades a guest in
  place (sets name + password, history retained).
- **Rate limiting**: simple in-memory token bucket per IP on `/auth/*`
  (5/min) and per session on move endpoints (sanity cap).

## Offering and playing games

**Lobby model** — three paths into a PvP game:
1. **Open seek**: post board + modes + side preference + rated flag (+
   optional rating window). Appears in the lobby list; first accepter starts
   the game.
2. **Direct challenge**: a seek with `target_player` set; only they see it.
3. **Quick match**: server pairs compatible open seeks automatically
   (same board/modes/rated, overlapping rating windows) — no separate queue
   system needed, it's just auto-accept between matching seeks.

Side assignment honors preferences, else random; **rated rematches
auto-alternate colors** (first-mover advantage is measurable, so the ladder
must average it out).

**Turn flow (PvP)**: mover POSTs `/api/v1/games/{id}/move`; opponent learns
via polling `GET /api/v1/games/{id}/state?since=<ply>` — returns immediately
with changes, or holds up to ~25 s when `wait=1` (long-poll; works fine on
the stdlib threading server since each waiting client parks one thread —
acceptable at this scale, and the SPA polls only the game being viewed).
SSE can replace polling later without API changes.

**Endings**: normal engine results, plus `resign`, `draw by agreement`
(offer/accept as today), and **inactivity forfeit** — configurable per-move
time allowance (default: 3 days, correspondence-style; a background sweeper
thread forfeits expired games). Abandoning counts as a loss for the abandoner.

**AI games**: exactly today's flow, but persisted and attached to the player.
Difficulty and result recorded for stats.

## Ratings & ranks

- **System**: Elo with a rating-deviation twist (simplified Glicko):
  new players start at 1200 with high K (K=40 for the first 15 rated games,
  then K=20). Draw = 0.5. Only **rated PvP** games move the rating.
- **AI games and ranks**: AI wins never move the Elo rating (they'd be
  farmable), but they do advance a separate **AI ladder** per difficulty
  (beat Normal 5×, Hard 5×, …) shown on the profile — practice progress
  without polluting the ladder.
- **Ranks**: named tiers over rating bands, themed on terrain tiles:

  | Rank | Rating |
  |---|---|
  | Field | < 1100 |
  | Gate | 1100–1299 |
  | Spire | 1300–1499 |
  | Tower | 1500–1699 |
  | Throne | 1700–1899 |
  | Monarch | 1900+ |

  Rank = f(rating), computed, never stored — no rank/rating drift possible.
  Placement: rank shows as "Unranked" until 10 rated games.
- **Leaderboard**: top N by rating (min 10 rated games), plus per-player
  profile with W/L/D, win types, favorite boards, rating graph
  (from `rating_events`).

## API surface (v1, all under /api/v1)

| Endpoint | Method | Purpose |
|---|---|---|
| /auth/register, /auth/login, /auth/logout, /auth/guest | POST | account lifecycle |
| /auth/recover | POST | reset password with recovery code |
| /me | GET | own profile, active games, AI-ladder progress |
| /players/{name} | GET | public profile + stats |
| /leaderboard | GET | ladder |
| /seeks | GET/POST/DELETE | lobby: list, create, cancel |
| /seeks/{id}/accept | POST | start PvP game |
| /games | POST | create AI game (board, modes, difficulty, side) |
| /games/{id}/state | GET | state (+`since`/`wait` long-poll) |
| /games/{id}/move | POST | make a move (server validates, resolves fog bump) |
| /games/{id}/resign, /draw | POST | endings; draw carries offer/accept flow |
| /games/{id}/moves | GET | full move log (replay) |

Existing `/api/*` endpoints stay during transition; the SPA's ServerAdapter
grows the new calls. **LocalAdapter (GitHub Pages offline play) is untouched**
— it simply never sees auth and keeps working AI-only.

## Frontend additions

Login/register/guest bar; lobby screen (open seeks, create seek, challenge);
"my games" list with turn indicators; profile/leaderboard views; in-game
opponent name + rating; resign button. All in the existing single Vue SPA —
no build step introduced.

## Operations

- Fly.io: mount a volume for `facet.db`; single machine, `min_machines=1`
  (in-memory sessions cache warm, but everything critical is in the DB)
- Backup: nightly `sqlite3 facet.db ".backup ..."` cron + volume snapshots
- Admin: `is_admin` flag + three endpoints (ban player, abort game, rename);
  everything else via `sqlite3` CLI on the file — that *is* the admin panel
- Logging: current per-game event log moves into the `moves` table +
  a plain rotating server log

## Migration path to a standard DB

Trigger: sustained write contention or multi-machine need. Path:
1. `storage.py` already exposes the full persistence interface
2. Implement `storage_pg.py` with the same functions (psycopg, same schema —
   ANSI types chosen to map 1:1)
3. `DATABASE_URL=postgres://…` switches; a one-shot script copies tables
4. Nothing above the storage layer changes

## Phases

| Phase | Delivers | Effort |
|---|---|---|
| 1. Persistence — **DONE 2026-07-05** | storage.py + schema, event-sourced games, accounts + guests + sessions, AI games persisted per player, crash-safe restarts | ~1 session |
| 2. PvP — **DONE 2026-07-05** (quick-match deferred; seeks + direct challenges shipped) | seeks/challenges, turn flow with long-poll, resign/draw/forfeit sweeper, my-games UI | ~1–2 sessions |
| 3. Ladder — **DONE 2026-07-05** | Elo + ranks + rating_events, leaderboard + profiles, color alternation in rated rematches, self-service rename | ~1 session |
| 4. Polish | SSE push, presence ("online"), rematch button, spectating, seasons/decay, Litestream backup | as desired |

Each phase ships independently and keeps the game playable throughout.

## Decisions (settled 2026-07-05)

1. **Ratings**: one rating across all boards and modes
2. **Move time allowance**: 3 days (FACET_MOVE_SECONDS to override)
3. **Guest PvP**: casual only — rated seeks require a registered account
4. **Rename**: self-service with case-insensitive duplicate check
   (guests rename by claiming their account)
