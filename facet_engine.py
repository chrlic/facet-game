"""
FACET game engine + AI.

Rules (core):
  - A piece's MOVE is granted by the terrain tile it stands on:
        F field  -> king-step (1 in 8 dirs)      R tower -> rook slide
        B spire  -> bishop slide                  N gate  -> knight leap
        T throne -> queen slide (and is an objective)
  - The Monarch ignores terrain: it always moves like a king (1 step).
  - Capture = land on an enemy piece. You may not land on your own.
  - WIN by: (Regicide) capturing the enemy Monarch, OR
            (Coronation) holding ALL throne tiles for a full round, OR
            (Elimination) reducing the enemy to a bare monarch (no agents left).
  - No legal move = draw. Draw also by mutual agreement.

Player 0 = bottom (human by default). Player 1 = top (AI).
"""
import time
import random

ORTH = [(1, 0), (-1, 0), (0, 1), (0, -1)]
DIAG = [(1, 1), (1, -1), (-1, 1), (-1, -1)]
KING = ORTH + DIAG
KNIGHT = [(1, 2), (2, 1), (-1, 2), (-2, 1), (1, -2), (2, -1), (-1, -2), (-2, -1)]
SLIDERS = {'R': ORTH, 'B': DIAG, 'T': KING}

INF = 10**9


def _make_board(rows_top_down, W, H, p0_cells=None, p1_cells=None):
    """Build a Board from row strings.
    p0/p1_cells: list of (x,y) positions. Monarch is the one at x == W//2 on
    the back row (lowest y for P0, highest y for P1). If omitted, fills the
    entire back row."""
    terrain = {}
    for i, row in enumerate(rows_top_down):
        y = H - 1 - i
        for x, ch in enumerate(row):
            terrain[(x, y)] = ch
    mid = W // 2
    if p0_cells is None:
        p0_cells = [(x, 0) for x in range(W)]
    if p1_cells is None:
        p1_cells = [(x, H - 1) for x in range(W)]
    pieces = {}
    p0_back = min(y for _, y in p0_cells)
    p1_back = max(y for _, y in p1_cells)
    for x, y in p0_cells:
        pieces[(x, y)] = (0, x == mid and y == p0_back)
    for x, y in p1_cells:
        pieces[(x, y)] = (1, x == mid and y == p1_back)
    return Board(W, H, terrain, pieces)


BOARDS = {
    # ---- 7x7 ----
    "classic": {
        "name": "Classic 7x7",
        "desc": "The original — two thrones in the centre corridor.",
        "size": [7, 7],
        "rows": [
            "FFFFFFF",
            "FFFFFFF",
            "BFNFNFB",
            "RFTFTFR",
            "BFNFNFB",
            "FFFFFFF",
            "FFFFFFF",
        ],
    },
    "knights": {
        "name": "Knight's Arena 7x7",
        "desc": "Gates everywhere — chaotic leaping battles.",
        "size": [7, 7],
        "rows": [
            "FNFFFNF",
            "NFFFFFN",
            "NFNFNFN",
            "FFTFTFF",
            "NFNFNFN",
            "NFFFFFN",
            "FNFFFNF",
        ],
    },
    # ---- 9x9 ----
    "sprawl": {
        "name": "Sprawl 9x9",
        "desc": "Features scattered wide — long sight lines, two thrones.",
        "size": [9, 9],
        "rows": [
            "FFFFFFFFF",
            "FNFFFFFNF",
            "FFFBFBFFF",
            "FFFFFFFFF",
            "RFFTFTFFR",
            "FFFFFFFFF",
            "FFFBFBFFF",
            "FNFFFFFNF",
            "FFFFFFFFF",
        ],
    },
    "citadel": {
        "name": "Citadel 9x9",
        "desc": "Thrones on the flanks, guarded by a ring of features.",
        "size": [9, 9],
        "rows": [
            "FFFFFFFFF",
            "FFBFFFBFF",
            "FNFFFRNFF",
            "FFFFTFFFF",
            "FFFFFFFFF",
            "FFFFTFFFF",
            "FFNRFFFNF",
            "FFBFFFBFF",
            "FFFFFFFFF",
        ],
    },
    # ---- 7x7 extras ----
    "crossroads": {
        "name": "Crossroads 7x7",
        "desc": "Features at intersections — control the crossroads to dominate.",
        "size": [7, 7],
        "rows": [
            "FFFNFFF",
            "FFBFBFF",
            "FRFFFRF",
            "NFTFTFN",
            "FRFFFRF",
            "FFBFBFF",
            "FFFNFFF",
        ],
    },
    # ---- 8x8 ----
    "standard8": {
        "name": "Standard 8x8",
        "desc": "Chess-sized board — two thrones, balanced terrain.",
        "size": [8, 8],
        "rows": [
            "FFFFFFFF",
            "FFFFFFFF",
            "FBNFFNBF",
            "RFFTFFRF",
            "FRFFTFFR",
            "FBNFFNBF",
            "FFFFFFFF",
            "FFFFFFFF",
        ],
    },
    "diamond8": {
        "name": "Diamond 8x8",
        "desc": "Features form a diamond — thrones at the heart.",
        "size": [8, 8],
        "rows": [
            "FFFFFFFF",
            "FFFNFFFF",
            "FFBFFBFF",
            "FNFTFNFF",
            "FFNFTFNF",
            "FFBFFBFF",
            "FFFFNFFF",
            "FFFFFFFF",
        ],
    },
    "arena9": {
        "name": "Arena 9x9",
        "desc": "Open centre ringed by features — all-out brawl.",
        "size": [9, 9],
        "rows": [
            "FFFFFFFFF",
            "FFFFFFFFF",
            "FFNBRBNFF",
            "FFRFFFRFF",
            "FBFTFTFBF",
            "FFRFFFRFF",
            "FFNBRBNFF",
            "FFFFFFFFF",
            "FFFFFFFFF",
        ],
    },
    "flux9": {
        "name": "Flux 9x9",
        "desc": "Features spiral around the thrones — fluid, shifting play.",
        "size": [9, 9],
        "rows": [
            "FFFFFFFFF",
            "FFNFFFBFF",
            "FFFFRFFFF",
            "FBFFFTFFF",
            "FFFFFFFFF",
            "FFFTFFFBF",
            "FFFFRFFFF",
            "FFBFFFNFF",
            "FFFFFFFFF",
        ],
    },
    "temple9": {
        "name": "Temple 9x9",
        "desc": "Power tiles guard the thrones — fight through to coronation.",
        "size": [9, 9],
        "rows": [
            "FFFFFFFFF",
            "FFFFFFFFF",
            "FFBRFRBFF",
            "FFNFTFNFF",
            "FFFFFFFFF",
            "FFNFTFNFF",
            "FFBRFRBFF",
            "FFFFFFFFF",
            "FFFFFFFFF",
        ],
    },
}

# Tile-promotion variant boards — promoting tiles as contested mid-board prizes
TILE_PROMO_BOARDS = {
    "forge7": {
        "name": "Forge 7x7",
        "desc": "Promotions clustered in the centre — race to claim your power.",
        "size": [7, 7],
        "rows": [
            "FFFFFFF",
            "FFFFFFF",
            "FFRNRFF",
            "FBTFTBF",
            "FFRNRFF",
            "FFFFFFF",
            "FFFFFFF",
        ],
    },
    "gauntlet7": {
        "name": "Gauntlet 7x7",
        "desc": "Promotions line the corridor — fight through to power up.",
        "size": [7, 7],
        "rows": [
            "FFFFFFF",
            "FFRFRFF",
            "FNFFFNF",
            "FBTFTBF",
            "FNFFFNF",
            "FFRFRFF",
            "FFFFFFF",
        ],
    },
    "academy8": {
        "name": "Academy 8x8",
        "desc": "Promotions in a ring — choose your specialization wisely.",
        "size": [8, 8],
        "rows": [
            "FFFFFFFF",
            "FFFFFFFF",
            "FFNFFNFF",
            "FRFTFBRF",
            "FRBFTFRF",
            "FFNFFNFF",
            "FFFFFFFF",
            "FFFFFFFF",
        ],
    },
    "bazaar8": {
        "name": "Bazaar 8x8",
        "desc": "Promotions scattered wide — each path offers different power.",
        "size": [8, 8],
        "rows": [
            "FFFFFFFF",
            "FFNFFBFF",
            "FRFFFFRF",
            "FFFFTFFF",
            "FFFTFFFF",
            "FRFFFFRF",
            "FFBFFNFF",
            "FFFFFFFF",
        ],
    },
    "nexus9": {
        "name": "Nexus 9x9",
        "desc": "Three promotion clusters — secure the nexus points.",
        "size": [9, 9],
        "rows": [
            "FFFFFFFFF",
            "FFFFFFFFF",
            "FFNFFFNFF",
            "FFRFTFRFF",
            "FFBFFFBFF",
            "FFRFTFRFF",
            "FFNFFFNFF",
            "FFFFFFFFF",
            "FFFFFFFFF",
        ],
    },
    "temple9": {
        "name": "Temple 9x9",
        "desc": "Power tiles guard the thrones — promotion is the path to victory.",
        "size": [9, 9],
        "rows": [
            "FFFFFFFFF",
            "FFFFFFFFF",
            "FFBRFRBFF",
            "FFNFTFNFF",
            "FFFFFFFFF",
            "FFNFTFNFF",
            "FFBRFRBFF",
            "FFFFFFFFF",
            "FFFFFFFFF",
        ],
    },
}


def make_board(board_id="classic", modes=None):
    spec = BOARDS.get(board_id) or TILE_PROMO_BOARDS.get(board_id) or BOARDS["classic"]
    W, H = spec["size"]
    rows = [r.replace(" ", "")[:W] for r in spec["rows"]]
    p0 = spec.get("p0")
    p1 = spec.get("p1")
    if p0:
        p0 = [tuple(c) for c in p0]
    if p1:
        p1 = [tuple(c) for c in p1]
    if p0 is None and W == 9 and H == 9:
        p0 = [(x, 0) for x in range(W)] + [(2, 1), (6, 1)]
        p1 = [(x, H-1) for x in range(W)] + [(6, H-2), (2, H-2)]
    board = _make_board(rows, W, H, p0_cells=p0, p1_cells=p1)
    if modes:
        board.modes = set(modes)
        if 'decay' in board.modes:
            board.terrain = dict(board.terrain)
    return board


def canonical_board():
    return make_board("classic")


DECAY_MAP = {'R': 'B', 'B': 'N', 'N': 'F', 'F': 'F', 'T': 'T'}
FOG_RADIUS = 2
FOG_MONARCH_RADIUS = 3

DECAY_BOARDS = {'classic', 'standard8', 'sprawl', 'arena9', 'temple9'}
FOG_BOARDS = {'knights', 'standard8', 'diamond8', 'temple9'}


class Board:
    def __init__(self, W, H, terrain, pieces, to_move=0, throne_held_since=None,
                 modes=None):
        self.W, self.H = W, H
        self.terrain = terrain
        self.pieces = pieces
        self.to_move = to_move
        self.throne_held_since = throne_held_since
        self.modes = modes or set()

    def clone(self):
        t = dict(self.terrain) if 'decay' in self.modes else self.terrain
        b = Board(self.W, self.H, t, dict(self.pieces),
                  self.to_move, self.throne_held_since, set(self.modes))
        if getattr(self, '_partial', False):
            b._partial = True
            b._viewer = self._viewer
        return b

    def key(self):
        base = (frozenset(self.pieces.items()), self.to_move, self.throne_held_since)
        if 'decay' in self.modes:
            return base + (frozenset(self.terrain.items()),)
        return base

    # ---- queries ----
    def monarch_alive(self, owner):
        return any(o == owner and m for (o, m) in self.pieces.values())

    def monarch_cell(self, owner):
        for c, (o, m) in self.pieces.items():
            if o == owner and m:
                return c
        return None

    def thrones(self):
        return [c for c, g in self.terrain.items() if g == 'T']

    def throne_holder(self):
        ts = self.thrones()
        if not ts:
            return None
        owners = set()
        for c in ts:
            occ = self.pieces.get(c)
            if occ is None:
                return None
            owners.add(occ[0])
        return next(iter(owners)) if len(owners) == 1 else None

    def piece_count(self, owner):
        return sum(1 for o, _ in self.pieces.values() if o == owner)

    def winner(self):
        """Returns 0, 1, 'draw', or None (game ongoing)."""
        partial = getattr(self, '_partial', False)
        viewer = getattr(self, '_viewer', None)
        if not self.monarch_alive(0):
            if partial and viewer == 1:
                pass  # might just be hidden
            else:
                return 1
        if not self.monarch_alive(1):
            if partial and viewer == 0:
                pass
            else:
                return 0
        if not partial:
            if self.piece_count(0) == 1:
                return 1
            if self.piece_count(1) == 1:
                return 0
        # coronation: hold all thrones for a full round (opponent had a chance to contest)
        th = self.throne_holder()
        if th is not None:
            if (self.throne_held_since is not None
                    and self.throne_held_since[0] == th
                    and self.throne_held_since[1] >= 3):
                return th
        if not self.legal_moves(self.to_move):
            return 'draw'
        return None

    def _ok_land(self, nx, ny, owner):
        if (nx, ny) not in self.terrain:
            return False
        occ = self.pieces.get((nx, ny))
        return occ is None or occ[0] != owner

    def moves_for(self, cell):
        (x, y) = cell
        o, is_mon = self.pieces[cell]
        glyph = 'F' if is_mon else self.terrain[cell]
        out = []
        if is_mon or glyph == 'F':
            for dx, dy in KING:
                if self._ok_land(x + dx, y + dy, o):
                    out.append((x + dx, y + dy))
        elif glyph == 'N':
            for dx, dy in KNIGHT:
                if self._ok_land(x + dx, y + dy, o):
                    out.append((x + dx, y + dy))
        elif glyph in SLIDERS:
            for dx, dy in SLIDERS[glyph]:
                nx, ny = x + dx, y + dy
                while (nx, ny) in self.terrain:
                    occ = self.pieces.get((nx, ny))
                    if occ is None:
                        out.append((nx, ny))
                    else:
                        if occ[0] != o:
                            out.append((nx, ny))
                        break
                    nx, ny = nx + dx, ny + dy
        return out

    def legal_moves(self, owner):
        mv = []
        for cell, (o, _) in self.pieces.items():
            if o == owner:
                for to in self.moves_for(cell):
                    mv.append((cell, to))
        return mv

    def apply(self, mv):
        fr, to = mv
        if 'decay' in self.modes:
            g = self.terrain.get(fr, 'F')
            self.terrain[fr] = DECAY_MAP.get(g, g)
        self.pieces[to] = self.pieces.pop(fr)
        self.to_move ^= 1
        th = self.throne_holder()
        if th is not None:
            if (self.throne_held_since is not None
                    and self.throne_held_since[0] == th):
                self.throne_held_since = (th, self.throne_held_since[1] + 1)
            else:
                self.throne_held_since = (th, 1)
        else:
            self.throne_held_since = None

    def visible_cells(self, owner):
        """Fog of war: returns set of (x,y) visible to `owner`."""
        vis = set()
        for c, (o, is_mon) in self.pieces.items():
            if o != owner:
                continue
            r = FOG_MONARCH_RADIUS if is_mon else FOG_RADIUS
            cx, cy = c
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    if abs(dx) + abs(dy) <= r:
                        pos = (cx + dx, cy + dy)
                        if pos in self.terrain:
                            vis.add(pos)
        for c in self.thrones():
            vis.add(c)
        return vis

    def fog_view(self, owner):
        """Return a board copy with enemy pieces outside vision removed.
        Sets partial_view flag so winner/eval don't misinterpret missing pieces."""
        if 'fog' not in self.modes:
            return self
        vis = self.visible_cells(owner)
        t = dict(self.terrain) if 'decay' in self.modes else self.terrain
        filtered = {c: p for c, p in self.pieces.items()
                    if p[0] == owner or c in vis}
        m = set(self.modes) - {'fog'}
        b = Board(self.W, self.H, t, filtered,
                  self.to_move, self.throne_held_since, m)
        b._partial = True
        b._viewer = owner
        return b


# ---------------- AI ----------------
def mobility(board, cell):
    return len(board.moves_for(cell))


def evaluate(board, owner):
    """Positive = good for `owner`."""
    partial = getattr(board, '_partial', False)
    viewer = getattr(board, '_viewer', None)
    if not board.monarch_alive(owner):
        if partial and owner != viewer:
            pass  # hidden, not captured
        else:
            return -INF
    if not board.monarch_alive(owner ^ 1):
        if partial and (owner ^ 1) != viewer:
            pass
        else:
            return INF
    if not partial:
        if board.piece_count(owner) == 1:
            return -INF
        if board.piece_count(owner ^ 1) == 1:
            return INF
    th = board.throne_holder()
    if th == owner:
        return INF // 2
    if th == (owner ^ 1):
        return -INF // 2
    score = 0.0
    emc = board.monarch_cell(owner ^ 1)
    mmc = board.monarch_cell(owner)
    ts = board.thrones()
    my_count = board.piece_count(owner)
    opp_count = board.piece_count(owner ^ 1)
    for cell, (o, is_mon) in board.pieces.items():
        val = 1000.0 if is_mon else 3.0 + 0.6 * mobility(board, cell)
        if not is_mon:
            tgt = emc if o == owner else mmc
            if tgt is not None:
                d = abs(cell[0] - tgt[0]) + abs(cell[1] - tgt[1])
                val += max(0, 4 - d) * 0.45
            for t in ts:
                dt = abs(cell[0] - t[0]) + abs(cell[1] - t[1])
                if dt <= 2:
                    val += (3 - dt) * 0.6
        score += val if o == owner else -val
    if not partial:
        score += (my_count - opp_count) * 5.0
        if opp_count == 2:
            score += 15.0
    if my_count == 2:
        score -= 15.0
    return score


def _order(board, moves, killers=(), history=None):
    def k(mv):
        occ = board.pieces.get(mv[1])
        if occ and occ[1]:
            return (0, 0)
        if occ:
            return (1, 0)
        if mv in killers:
            return (2, 0)
        if board.terrain.get(mv[1]) == 'T':
            return (3, 0)
        h = -(history.get(mv, 0)) if history else 0
        return (4, h)
    return sorted(moves, key=k)


# TT flag constants
_EXACT, _LOWER, _UPPER = 0, 1, 2


class Searcher:
    def __init__(self, time_budget=1.0, max_depth=5, noise=0.0):
        self.time_budget = time_budget
        self.max_depth = max_depth
        self.noise = noise  # random eval jitter for variety
        self.deadline = 0
        self.tt = {}
        self.nodes = 0
        self.killers = {}
        self.history = {}

    def _store_killer(self, depth, mv):
        pair = self.killers.get(depth)
        if pair is None:
            self.killers[depth] = [mv, None]
        elif mv != pair[0]:
            pair[1] = pair[0]
            pair[0] = mv

    def search(self, board, owner):
        self.deadline = time.time() + self.time_budget
        best = None
        best_score = -INF
        reached = 0
        self.history.clear()
        moves = _order(board, board.legal_moves(board.to_move))
        if not moves:
            return None, 0, 0
        for depth in range(1, self.max_depth + 1):
            self.tt.clear()
            self.killers.clear()
            cur_best, cur_score = None, -INF
            a = -INF
            try:
                ordered = [best] + [m for m in moves if m != best] if best else moves
                for mv in ordered:
                    nb = board.clone(); nb.apply(mv)
                    v = -self._ab(nb, owner, depth - 1, -INF, -a)
                    if v > cur_score:
                        cur_score, cur_best = v, mv
                    a = max(a, v)
            except TimeoutError:
                break
            best, best_score, reached = cur_best, cur_score, depth
            if best_score >= INF // 2:
                break
        return best, best_score, reached

    def _ab(self, board, owner, depth, a, b):
        if time.time() > self.deadline:
            raise TimeoutError
        self.nodes += 1

        partial = getattr(board, '_partial', False)
        viewer = getattr(board, '_viewer', None)
        if not board.monarch_alive(0):
            if not (partial and 0 != viewer):
                return -INF if owner == 0 else INF
        if not board.monarch_alive(1):
            if not (partial and 1 != viewer):
                return -INF if owner == 1 else INF
        th = board.throne_holder()
        if th is not None and th == board.to_move:
            return (INF // 2) if th == owner else -(INF // 2)
        if depth <= 0:
            return self._quiesce(board, owner, a, b, 0)

        # TT probe with exact/bound info
        key = board.key()
        cached = self.tt.get(key)
        if cached is not None:
            tt_depth, tt_flag, tt_val, tt_best = cached
            if tt_depth >= depth:
                if tt_flag == _EXACT:
                    return tt_val
                if tt_flag == _LOWER and tt_val >= b:
                    return tt_val
                if tt_flag == _UPPER and tt_val <= a:
                    return tt_val

        # null-move pruning: skip our turn — if still >= beta, prune
        R = 2
        if depth >= R + 1 and not self._in_check(board, board.to_move):
            nb = board.clone()
            nb.to_move ^= 1
            v = -self._ab(nb, owner, depth - 1 - R, -b, -b + 1)
            if v >= b:
                return b

        killers = self.killers.get(depth, [])
        moves = _order(board, board.legal_moves(board.to_move),
                       killers=killers, history=self.history)
        if not moves:
            return 0

        best_val = -INF
        best_mv = None
        orig_a = a
        for mv in moves:
            nb = board.clone(); nb.apply(mv)
            v = -self._ab(nb, owner, depth - 1, -b, -a)
            if v > best_val:
                best_val = v
                best_mv = mv
            a = max(a, v)
            if a >= b:
                if not board.pieces.get(mv[1]):
                    self._store_killer(depth, mv)
                    self.history[mv] = self.history.get(mv, 0) + depth * depth
                break

        # TT store
        if best_val <= orig_a:
            flag = _UPPER
        elif best_val >= b:
            flag = _LOWER
        else:
            flag = _EXACT
        self.tt[key] = (depth, flag, best_val, best_mv)
        return best_val

    def _in_check(self, board, side):
        mc = board.monarch_cell(side)
        if mc is None:
            return True
        enemy = side ^ 1
        for cell, (o, _) in board.pieces.items():
            if o == enemy:
                if mc in board.moves_for(cell):
                    return True
        return False

    def _quiesce(self, board, owner, a, b, qdepth):
        partial = getattr(board, '_partial', False)
        viewer = getattr(board, '_viewer', None)
        if not board.monarch_alive(owner ^ 1):
            if not (partial and (owner ^ 1) != viewer):
                return INF
        if not board.monarch_alive(owner):
            if not (partial and owner != viewer):
                return -INF
        stand = evaluate(board, board.to_move)
        if self.noise > 0:
            stand += random.uniform(-self.noise, self.noise)
        if stand >= b:
            return stand
        if stand > a:
            a = stand
        if qdepth >= 4:
            return stand
        caps = [m for m in board.legal_moves(board.to_move)
                if board.pieces.get(m[1]) is not None]
        caps = _order(board, caps)
        best = stand
        for mv in caps:
            if time.time() > self.deadline:
                raise TimeoutError
            nb = board.clone(); nb.apply(mv)
            v = -self._quiesce(nb, owner, -b, -a, qdepth + 1)
            if v > best:
                best = v
            a = max(a, v)
            if a >= b:
                break
        return best


def ai_move(board, time_budget=1.0, max_depth=5):
    view = board.fog_view(board.to_move)
    total_pieces = len(view.pieces)
    noise = 1.5 if total_pieces >= 12 else 0.5 if total_pieces >= 8 else 0.0
    s = Searcher(time_budget=time_budget, max_depth=max_depth, noise=noise)
    mv, score, depth = s.search(view, view.to_move)
    return mv, {"score": round(score, 1), "depth": depth, "nodes": s.nodes}


def ai_evaluate_draw(board, side, time_budget=0.5, max_depth=4):
    view = board.fog_view(side)
    s = Searcher(time_budget=time_budget, max_depth=max_depth, noise=0.0)
    _, score, _ = s.search(view, side)
    if score <= -5.0:
        return True, "Position looks difficult — draw accepted."
    if abs(score) < 2.0:
        return True, "Position is roughly equal — draw accepted."
    return False, f"AI declines the draw (eval {score:+.1f} in its favour)."


def ai_wants_draw(board, side, time_budget=0.5, max_depth=4):
    view = board.fog_view(side)
    s = Searcher(time_budget=time_budget, max_depth=max_depth, noise=0.0)
    _, score, _ = s.search(view, side)
    return score <= -8.0
