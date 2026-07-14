# FACET (+ BACKBONE)

A chess-inspired strategy game where the board shapes your pieces. Your move isn't determined by what piece you are — it's determined by where you stand.
An illustrated, printable player's guide is at `FACET_GUIDE.pdf`.

The server also hosts **BACKBONE** (`/backbone.html`) — a 2-player
network-building game on a hex grid (rules in `Backbone_Rulebook.md`,
illustrated guide at `BACKBONE_GUIDE.pdf`): build routers, servers and
datacenters, connect cities, hack your rival. Same accounts, lobby, ratings,
AI difficulties, and offline mode as FACET; engine in `backbone_engine.py`
with a line-for-line JS port (`docs/backbone_engine.js`, parity-verified).

And **HYPERSCALE** (`/hyperscale.html`) — a solo-vs-AI economic strategy game on
a 9×9 hex board (illustrated guide at `HYPERSCALE_GUIDE.pdf`): claim ground, wire
datacenters to scarce shared power stations, staff them from your HQ, equip them
from a finite parts market, and race the computer to the most AI tokens over 24
days. Engine in `docs/hyperscale_engine.js`.

## The idea

In chess, a rook is always a rook. In FACET, every stone is the same — but it borrows its movement from the **terrain tile** beneath it. Step onto a Tower tile and you slide like a rook. Jump to a Gate tile and you leap like a knight. The board itself becomes the most important piece.

## Rules

**Terrain tiles** grant movement to whatever stone stands on them:

| Tile | Icon | Movement |
|------|------|----------|
| Field | • | Step 1 square in any direction |
| Tower | ♜ | Slide horizontally or vertically (rook) |
| Spire | ♝ | Slide diagonally (bishop) |
| Gate | ♞ | Leap in an L-shape (knight) |
| Throne | ♛ | Slide in all 8 directions (queen) + win objective |

**The Monarch** (♚) is special — it always moves 1 step regardless of terrain.

**Capture** by landing on an enemy stone. Sliders are blocked by pieces in their path; the Gate leaps over everything.

**Win** by any of:
- **Regicide** — capture the enemy Monarch
- **Coronation** — hold all Throne tiles for a full round (opponent gets one turn to contest)
- **Elimination** — capture all enemy agents, leaving a bare Monarch

**Draw** by stalemate (no legal moves) or mutual agreement. Either side can offer a draw; the opponent may accept or decline.

## Boards

10 simulation-tested layouts across three sizes, each with a distinct character:

**7x7** (7 pieces per side)
- **Classic** — the original centre-corridor layout
- **Knight's Arena** — gates everywhere, chaotic leaping battles
- **Crossroads** — features at key intersections

**8x8** (8 pieces per side)
- **Standard** — chess-sized, balanced mix of terrain
- **Diamond** — features form a diamond pattern

**9x9** (11 pieces per side)
- **Sprawl** — most decisive (97% of games end in a win)
- **Citadel** — long strategic games, thrones guarded by feature rings
- **Arena** — open centre ringed by features, all-out brawl
- **Flux** — spiral features, fluid positional play
- **Temple** — power tiles guard the thrones

Every board is 180° rotationally symmetric with exactly 2 Thrones and screened
with AI-vs-AI simulations for first-mover balance.

## Optional modes

Selectable before board choice; the board list filters to compatible layouts.

**Terrain decay** — when a stone leaves a special tile, the tile degrades one
tier (Tower → Spire → Gate → Field; Thrones never decay). Movement power is a
consumable resource. Boards: Classic, Standard, Sprawl, Arena, Temple.

**Fog of war** — each player sees only Manhattan radius 2 around their stones
(radius 3 around the Monarch); Thrones are always visible. Enemy stones you
have spotted linger as faded *ghosts* at their last-seen square. If a slider's
path crosses a hidden enemy, the slide **bumps**: it stops there and captures
it. The AI plays under the same fog and keeps the same kind of sighting
memory a human has. Boards: Knight's Arena, Diamond, Temple, Lantern.

**Momentum** — a stone that leaves a special tile keeps that tile's rank for
one more move, on top of what its new tile grants. The retained rank shows as
a badge on the stone (public information for both sides) and expires after the
next move. Leaving a Throne keeps the queen-slide for a move, so throne raids
have an exit. Validated over 400+ games per board: draws drop to under 10% and
elimination wins roughly double. Boards: Classic, Knight's Arena, Standard,
Diamond, Citadel. Not combinable with decay or fog.

Temple supports decay and fog at once. Lantern 8x8 is fog-only — its far-flank
thrones are designed for hidden-information play and it is not offered for
plain games. The board list always shows only layouts validated for the
selected mode.

## Side choice

White moves first, and the first move is a measurable advantage. Before each
game you can play White, Black, or Random — your stones always start at the
bottom of the screen.

## AI

The AI opponent uses iterative-deepening alpha-beta search with:
- Killer move and history heuristics for move ordering
- Null-move pruning
- Quiescence search (extends captures to avoid horizon blunders)
- Transposition table with exact/bound flags
- Opening noise for game variety

Three difficulty levels: Easy (depth 2), Normal (depth 4), Hard (depth 6).

The AI can also propose and evaluate draw offers based on its position evaluation.

In fog of war the AI searches only its own fog view — it never peeks at the
full board. It remembers recent enemy sightings (like a human does) and plays
more cautiously while enemy pieces are unaccounted for.

## Digital Play Notes

These are software controls the app provides on top of the ruleset above —
not tabletop rules themselves:

- **Mode/board/side selection** — before starting a new game, pick optional
  modes (terrain decay, fog of war, momentum — see *Optional modes* above),
  a board, and your side (White/Black/Random) from the checkboxes and
  dropdowns on the new-game screen.
- **Rated toggle** — registered (non-guest) players can check "Rated" when
  offering or accepting a PvP game so it counts toward Elo; AI games and
  guest games are always casual (see *Ratings & ranks* above).
- **Draw offers** — either side can offer a draw mid-game; the opponent sees
  Accept/Decline buttons at that point.
- **Bug reporter** — built into the UI; captures full reproducible board
  state, move history, and AI search info in one downloadable report (see
  *Bug reports* below).

## Play in the browser (no install)

**Gitpod** — prepend `gitpod.io/#` to the repo URL:

```
gitpod.io/#https://github.com/YOUR_USER/facet
```

**GitHub Codespaces** — from the repo page:

> **Code** → **Codespaces** → **Create codespace on main**

Both start the server automatically and open the game in your browser.

## Game server (accounts, lobby, PvP)

`server.py` is a full game server — still stdlib-only:

- **Accounts** — register with name + password (scrypt-hashed), or play
  instantly as an auto-created **guest** and claim the account later. A
  one-time recovery code (shown at registration) replaces email resets.
- **Lobby** — offer your current board + modes to other players, accept open
  offers, or challenge someone directly. Turn delivery uses long-polling.
- **PvP games** are correspondence-style: no clocks, but an inactive player
  forfeits after the move allowance (default 3 days, `FACET_MOVE_SECONDS`).
  Resign and draw-by-agreement are supported; in fog games each player is
  served only their own view — hidden pieces never leave the server.
- **Persistence** — everything lives in a single SQLite file (`facet.db`,
  `FACET_DB` to relocate). Games are stored as move logs and replayed through
  the deterministic engine on demand, so a server restart loses nothing.
  All SQL sits in `storage.py`; swapping in a standard DB engine later means
  reimplementing that one module.

- **Ratings & ranks** — rated PvP games move an Elo rating (K=40 for
  the first 15 rated games, then K=20). Each game — FACET and BACKBONE —
  keeps its **own independent rating, ladder, and placement count**; a game
  in one never affects the other. Ranks are computed from rating bands:
  Field → Gate → Spire → Tower → Throne → Monarch, shown after 10 placement
  games (per game). The leaderboard is per game (`/api/v1/leaderboard?game_type=`).
  Rated rematches
  between the same players alternate colors (the first-mover advantage is
  measured, so the ladder averages it out). Guests play casual only; AI
  games never affect the rating. Leaderboard and public profiles included.
  Names are changeable self-service (uniqueness enforced).

- **Administration** — `/admin.html` (admin accounts only) shows server
  statistics, all players with search and password reset, and active games
  with force-abort. Grant admin with `python3 manage.py make-admin <name>`
  (or `FACET_ADMIN=<name>` at startup). `manage.py` also does
  `list-players`, `reset-password`, `stats`, and the bug-report commands
  (`list-reports` / `show-report` / `resolve-report`) from the shell — safe to
  run while the server is up.

The old anonymous `/api/*` endpoints remain for cached PWA clients; the SPA
uses the authenticated `/api/v1/*` API. GitHub Pages offline mode is
unaffected (AI-only, in-browser engine, no accounts).

## Running locally

No dependencies beyond Python 3.10+.

```bash
python3 server.py
```

Open http://localhost:8000

## Deploying to Fly.io

```bash
fly launch
fly deploy
```

The included `Dockerfile` and `fly.toml` are ready to go. The server reads `PORT` from the environment (defaults to 8000 locally, 8080 on Fly).

Note: game state lives in memory — restarting the server loses active games.

## Project structure

```
facet_engine.py        Game rules, board definitions, AI (Python — server mode)
server.py              HTTP API + static file server (stdlib only)
docs/                  Shared frontend — served by Python AND GitHub Pages
  index.html           Vue 3 single-page UI
  facet_engine.js      Game engine + AI (JavaScript — browser mode)
  adapter.js           ServerAdapter / LocalAdapter — auto-detects mode
  vue.global.prod.js   Vue 3 framework (bundled, no CDN)
.github/workflows/
  pages.yml            Auto-deploy docs/ to GitHub Pages on push to main
Dockerfile             Deployment image (Fly.io)
fly.toml               Fly.io configuration
```

The app runs in two modes:
- **Server mode** — `python3 server.py` serves `docs/`, frontend uses `ServerAdapter` (fetch to Python API)
- **Local mode** — open `docs/index.html` directly or via GitHub Pages, frontend uses `LocalAdapter` (JS engine in the browser, no server needed)

Mode is auto-detected: the frontend tries to reach `/api/boards` — if the server responds, it uses server mode; otherwise it falls back to local mode. The UI shows "(offline mode)" when running locally.

## Bug reports

The UI includes a built-in bug reporter. Describe the issue, then either:
- **Submit to server** (online mode) — stores the report in the database for
  admin review, tied to the current game, with the board snapshot, UI state,
  client event log, and browser info. The server already holds the full move
  log, so the whole game is reconstructable from the report.
- **Download full report** — saves the same context (plus the complete move
  history) as a local JSON file. Always available, including offline.

Admins pull submitted reports from the shell (safe while the server runs):

```bash
python3 manage.py list-reports [--status open|reviewed|all]
python3 manage.py show-report <id> [--json]   # report + full game record + moves
python3 manage.py resolve-report <id> [--reopen]
```

`show-report` bundles the report with all related game data — the game record,
both players, and every move — reconstructed from the database by `game_id`.

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/new` | POST | Create a game `{difficulty, board}` |
| `/api/state?id=` | GET | Get current game state |
| `/api/move` | POST | Make a move `{id, from, to}` |
| `/api/ai` | POST | Trigger AI move `{id}` |
| `/api/draw` | POST | Offer a draw `{id}` |
| `/api/boards` | GET | List available boards |
| `/api/log?id=` | GET | Get server event log |
