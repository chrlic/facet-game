# FACET

A chess-inspired strategy game where the board shapes your pieces. Your move isn't determined by what piece you are — it's determined by where you stand.

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

9 simulation-tested layouts across three sizes, each with a distinct character:

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

Every board is 180° rotationally symmetric with exactly 2 Thrones. All were validated with 100-game AI-vs-AI simulations for balance (first-mover win ratio between 0.42–0.58).

## AI

The AI opponent uses iterative-deepening alpha-beta search with:
- Killer move and history heuristics for move ordering
- Null-move pruning
- Quiescence search (extends captures to avoid horizon blunders)
- Transposition table with exact/bound flags
- Opening noise for game variety

Three difficulty levels: Easy (depth 2), Normal (depth 4), Hard (depth 6).

The AI can also propose and evaluate draw offers based on its position evaluation.

## Play in the browser (no install)

**Gitpod** — prepend `gitpod.io/#` to the repo URL:

```
gitpod.io/#https://github.com/YOUR_USER/facet
```

**GitHub Codespaces** — from the repo page:

> **Code** → **Codespaces** → **Create codespace on main**

Both start the server automatically and open the game in your browser.

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

The UI includes a built-in bug reporter. Describe the issue, click "Download full report", and the JSON file captures:
- Your description
- Full board state (reproducible position)
- Complete move history (client + server event logs)
- AI search info (depth, nodes, evaluation)
- Browser and screen info

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
