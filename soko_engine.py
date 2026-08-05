"""SOKO-SENSEI — server-side engine (a faithful port of docs/glyph_engine.js).

A competitive 2-player Sokoban duel: two pawns shove crates through a symmetric maze onto shared goals;
first to claim a majority of goals wins. Moves are actions {"dir": 0-4} (0-3 = up/down/left/right, 4 = PASS).

Public surface matches the other action-engines (octachess/hexago) so service.py can drive it:
  Board(board_id): .to_move .modes .clone() .is_legal(action, owner) .apply(action) .winner
  initial(board_id), legal_moves(state), apply_move(state, action), status(state)
  serialize(board, draw_agreed=False), ai_move(state, difficulty, time_ms=None), DIFF, explain_action(...)
"""
import random

DIRS = [(0, -1), (0, 1), (-1, 0), (1, 0)]   # up, down, left, right
PASS = 4
REP_WINDOW = 8
DIFF = {"easy": "easy", "normal": "normal", "hard": "hard"}
_DEPTH = {"easy": 4, "normal": 6, "hard": 8}    # min search depth; boards may bump it via aiDepth


def _k(x, y):
    return "%d,%d" % (x, y)


def _ek(x, y, nx, ny):
    if x < nx or y < ny:
        return "%d,%d:%d,%d" % (x, y, nx, ny)
    return "%d,%d:%d,%d" % (nx, ny, x, y)


def passable(sc, x, y, d):
    nx, ny = x + DIRS[d][0], y + DIRS[d][1]
    if nx < 0 or ny < 0 or nx >= sc["W"] or ny >= sc["H"]:
        return False
    if _k(nx, ny) in sc["walls"]:
        return False
    if sc["edges"] and _ek(x, y, nx, ny) in sc["edges"]:
        return False
    return True


# ---- scenarios (180°-symmetric mazes) --------------------------------------------------------------

def _mk_edges(W, H, segs):
    emap, render = {}, []

    def add(ax, ay, bx, by):
        key = _ek(ax, ay, bx, by)
        if key not in emap:
            emap[key] = 1
            render.append([ax, ay, bx, by])
    for t, x, y in segs:
        if t == "v":
            add(x - 1, y, x, y)
            add(W - 1 - x, H - 1 - y, W - x, H - 1 - y)
        else:
            add(x, y - 1, x, y)
            add(W - 1 - x, H - 1 - y, W - 1 - x, H - y)
    return emap, render


def _push_field(sc, gx, gy):
    """Backward BFS of push-distance from a goal over box cells (pawn-room aware, other boxes ignored)."""
    W, H, walls = sc["W"], sc["H"], sc["walls"]
    d = {_k(gx, gy): 0}
    q = [(gx, gy)]
    hd = 0
    while hd < len(q):
        cx, cy = q[hd]
        hd += 1
        cd = d[_k(cx, cy)]
        for i in range(4):
            px, py = cx - DIRS[i][0], cy - DIRS[i][1]
            bx, by = px - DIRS[i][0], py - DIRS[i][1]
            if px < 0 or py < 0 or px >= W or py >= H or _k(px, py) in walls:
                continue
            if bx < 0 or by < 0 or bx >= W or by >= H or _k(bx, by) in walls:
                continue
            if not passable(sc, px, py, i) or not passable(sc, bx, by, i):
                continue
            pk = _k(px, py)
            if pk in d:
                continue
            d[pk] = cd + 1
            q.append((px, py))
    return d


def build(name, grid, slots, crates, pawns, edge_segs=None, ai_depth=6, any_glyph=False):
    H, W = len(grid), len(grid[0])
    walls = {}
    for y in range(H):
        for x in range(W):
            if grid[y][x] == "#":
                walls[_k(x, y)] = 1
    edges = render = None
    if edge_segs is not None:
        edges, render = _mk_edges(W, H, edge_segs)
    sc = {
        "name": name, "W": W, "H": H, "walls": walls,
        "edges": edges, "edgeRender": render or [],
        "aiDepth": ai_depth or 6, "anyGlyph": bool(any_glyph),
        "slots": [{"x": s[0], "y": s[1], "g": s[2]} for s in slots],
        "crates0": [{"x": c[0], "y": c[1], "g": c[2]} for c in crates],
        "pawns0": [{"x": p[0], "y": p[1]} for p in pawns],
    }
    sc["pdist"] = [_push_field(sc, s["x"], s["y"]) for s in sc["slots"]]
    return sc


_F = ["...........", "...........", "...........", "...........", "...........",
      "...........", "...........", "...........", "..........."]

_S = [[4, 4, 0], [5, 4, 1], [6, 4, 0]]
_CD = [[3, 3, 0], [7, 5, 0], [3, 5, 0], [7, 3, 0], [5, 2, 1], [5, 6, 1], [2, 4, 2], [8, 4, 2]]
_P = [[1, 4], [9, 4]]
_VS = [[2, 4, 0], [5, 4, 1], [8, 4, 0]]
_VC = [[1, 3, 0], [9, 5, 0], [1, 5, 0], [9, 3, 0], [5, 2, 1], [5, 6, 1], [4, 4, 2], [6, 4, 2]]
_VP = [[0, 4], [10, 4]]
_DS = [[3, 2, 0], [5, 4, 1], [7, 6, 0]]
_DC = [[2, 3, 0], [8, 5, 0], [4, 3, 0], [6, 5, 0], [5, 2, 1], [5, 6, 1], [1, 4, 2], [9, 4, 2]]
_DP = [[1, 1], [9, 7]]
_LC = [[2, 2, 0], [8, 6, 0], [2, 6, 0], [8, 2, 0], [5, 1, 1], [5, 7, 1], [3, 4, 2], [7, 4, 2]]
_HS = [[3, 4, 0], [5, 4, 1], [7, 4, 0]]
_HC = [[1, 2, 0], [9, 6, 0], [1, 6, 0], [9, 2, 0], [5, 2, 1], [5, 6, 1], [4, 4, 2], [6, 4, 2]]
_HP = [[0, 4], [10, 4]]
_KG = ["###########", "#######..##", "####.....##", "######...##", "##...#....#", "#.........#",
       "#....#...##", "##...######", "##.....####", "##..#######", "###########"]
_KS = [[7, 2, 0], [3, 8, 0], [5, 5, 1]]
_KC = [[7, 4, 0], [3, 6, 0], [4, 5, 1], [6, 5, 1]]
_KP = [[1, 5], [9, 5]]
_TG = ["###########", "#.....#####", "#.....#####", "#.....#####", "#........##", "##.......##",
       "##........#", "#####.....#", "#####.....#", "#####.....#", "###########"]
_TS = [[3, 2, 0], [7, 8, 0], [5, 5, 1]]
_TC = [[3, 4, 0], [7, 6, 0], [3, 5, 1], [7, 5, 1]]
_TP = [[1, 4], [9, 6]]
_5G = ["###########", "#........##", "#.........#", "#.........#", "#...#.....#", "#.........#",
       "#.....#...#", "#.........#", "#.........#", "##........#", "###########"]
_5S = [[8, 1, 0], [2, 9, 0], [7, 2, 0], [3, 8, 0], [8, 2, 0], [2, 8, 0], [7, 7, 0], [3, 3, 0], [6, 8, 0], [4, 2, 0]]
_5C = [[5, 2, 0], [5, 8, 0], [4, 3, 0], [6, 7, 0], [2, 4, 0], [8, 6, 0], [6, 5, 0], [4, 5, 0], [4, 7, 0], [6, 3, 0]]
_5P = [[6, 8], [4, 2]]
_LVG = ["###########", "#.#..######", "#....######", "#........##", "#........##", "##...#...##",
        "##........#", "##........#", "######....#", "######..#.#", "###########"]
_LVS = [[2, 2, 0], [8, 8, 0], [3, 2, 0], [7, 8, 0], [8, 3, 0], [2, 7, 0], [4, 7, 0], [6, 3, 0]]
_LVC = [[4, 2, 0], [6, 8, 0], [3, 3, 0], [7, 7, 0], [7, 4, 0], [3, 6, 0], [8, 5, 0], [2, 5, 0]]
_LVP = [[6, 7], [4, 3]]
_UG = ["###########", "#......#..#", "#.........#", "#......#..#", "#..#......#", "#..#.#.#..#",
       "#......#..#", "#..#......#", "#.........#", "#..#......#", "###########"]
_US = [[2, 3, 0], [8, 7, 0], [1, 4, 0], [9, 6, 0], [2, 5, 0], [8, 5, 0]]
_UC = [[8, 2, 0], [2, 8, 0], [8, 3, 0], [2, 7, 0], [8, 8, 0], [2, 2, 0]]
_UP = [[1, 9], [9, 1]]
_SWG = ["#############", "#############", "#..##########", "#......#...##", "#..........##", "#......##...#",
        "#...........#", "#...##......#", "##..........#", "##...#......#", "##########..#",
        "#############", "#############"]
_SWS = [[6, 4, 0], [6, 8, 0], [8, 4, 0], [4, 8, 0], [10, 4, 0], [2, 8, 0], [2, 5, 0], [10, 7, 0], [2, 6, 0], [10, 6, 0], [2, 7, 0], [10, 5, 0]]
_SWC = [[5, 3, 0], [7, 9, 0], [5, 4, 0], [7, 8, 0], [9, 5, 0], [3, 7, 0], [9, 6, 0], [3, 6, 0], [8, 7, 0], [4, 5, 0], [9, 7, 0], [3, 5, 0]]
_SWP = [[9, 8], [3, 4]]

MAZES = [
    build("Cloister", _F, _S, _CD, _P, []),
    build("Twin Vaults", _F, _VS, _VC, _VP,
          [["v", 4, 3], ["v", 4, 5], ["v", 4, 4], ["h", 3, 4], ["h", 7, 4]]),
    build("Diagonal", _F, _DS, _DC, _DP,
          [["h", 3, 1], ["v", 5, 1], ["v", 5, 2], ["h", 7, 5]]),
    build("Hook", _KG, _KS, _KC, _KP, None, 7),
    build("Steps", _TG, _TS, _TC, _TP),
    build("Warehouse", _UG, _US, _UC, _UP, None, 7, True),
    build("Waterfall", _LVG, _LVS, _LVC, _LVP, None, 7, True),
    build("Five", _5G, _5S, _5C, _5P, None, 7, True),
    build("Sweet", _SWG, _SWS, _SWC, _SWP, None, 7, True),
    build("Long Haul ★", _F, _S, _LC, _P, [], 7),
    build("Chicane ★", _F, _HS, _HC, _HP, [["v", 4, 3], ["v", 4, 5]], 7),
]
BOARD_INDEX = {sc["name"]: i for i, sc in enumerate(MAZES)}


def board_index(board_id):
    if isinstance(board_id, int):
        return board_id % len(MAZES)
    if board_id in BOARD_INDEX:
        return BOARD_INDEX[board_id]
    try:
        return int(board_id) % len(MAZES)
    except (ValueError, TypeError):
        return 0


# ---- state ----------------------------------------------------------------------------------------

def key_of(s):
    p = s["pawns"]
    a = "%d,%d/%d,%d|" % (p[0][0], p[0][1], p[1][0], p[1][1])
    for c in s["crates"]:
        a += "%d,%d;" % (c[0], c[1])
    return a + "|" + ",".join(str(o) for o in s["owner"])


def new_game(board_id):
    mi = board_index(board_id)
    sc = MAZES[mi]
    s = {
        "mi": mi,
        "crates": [[c["x"], c["y"], c["g"]] for c in sc["crates0"]],
        "pawns": [[p["x"], p["y"]] for p in sc["pawns0"]],
        "owner": [-1] * len(sc["slots"]),
        "passes": 0, "turn": 0, "moves": 0, "hist": [],
    }
    s["hist"].append(key_of(s))
    return s


def _sc(s):
    return MAZES[s["mi"]]


def clone_state(s):
    return {
        "mi": s["mi"],
        "crates": [c[:] for c in s["crates"]],
        "pawns": [p[:] for p in s["pawns"]],
        "owner": s["owner"][:],
        "passes": s["passes"], "turn": s["turn"], "moves": s["moves"],
        "hist": s["hist"][:],   # copied (the server replays; each state owns its window)
    }


def remember(s):
    s["hist"].append(key_of(s))
    if len(s["hist"]) > REP_WINDOW:
        s["hist"].pop(0)


def majority(s):
    return (len(_sc(s)["slots"]) >> 1) + 1


def crate_at(s, x, y):
    for i, c in enumerate(s["crates"]):
        if c[0] == x and c[1] == y:
            return i
    return -1


def pawn_at(s, x, y):
    for i in range(2):
        if s["pawns"][i][0] == x and s["pawns"][i][1] == y:
            return i
    return -1


def slot_at(s, x, y):
    sl = _sc(s)["slots"]
    for i, o in enumerate(sl):
        if o["x"] == x and o["y"] == y:
            return i
    return -1


def blocked(s, x, y):
    sc = _sc(s)
    return x < 0 or y < 0 or x >= sc["W"] or y >= sc["H"] or _k(x, y) in sc["walls"]


def claimer_of(s, ci):
    c = s["crates"][ci]
    sl = slot_at(s, c[0], c[1])
    sc = _sc(s)
    if sl >= 0 and s["owner"][sl] >= 0 and (sc["anyGlyph"] or sc["slots"][sl]["g"] == c[2]):
        return s["owner"][sl]
    return -1


def frozen(s, ci):
    return claimer_of(s, ci) >= 0


def locked(s, ci, pl):
    o = claimer_of(s, ci)
    return o >= 0 and o != pl


def can_move(s, player, d):
    sc = _sc(s)
    p = s["pawns"][player]
    if not passable(sc, p[0], p[1], d):
        return False
    cx, cy = p[0] + DIRS[d][0], p[1] + DIRS[d][1]
    if pawn_at(s, cx, cy) >= 0:
        return False
    if crate_at(s, cx, cy) < 0:
        return True
    while True:
        ci = crate_at(s, cx, cy)
        if ci < 0:
            return True
        if locked(s, ci, player):
            return False
        if not passable(sc, cx, cy, d):
            return False
        cx, cy = cx + DIRS[d][0], cy + DIRS[d][1]
        if pawn_at(s, cx, cy) >= 0:
            return False


def legal_dirs(s, player):
    return [d for d in range(4) if can_move(s, player, d)]


def repeats(s, player, d):
    if d == PASS or not s["hist"]:
        return False
    c = clone_state(s)
    apply_dir(c, player, d)
    return key_of(c) in s["hist"]


def fresh_dirs(s, player):
    return [d for d in legal_dirs(s, player) if not repeats(s, player, d)]


def apply_dir(s, player, d):
    """Mutate s by playing direction d (0-3) or PASS for `player`. Returns claimed slot index or -1."""
    if d == PASS:
        s["passes"] += 1
        s["moves"] += 1
        return -1
    s["passes"] = 0
    sc = _sc(s)
    p = s["pawns"][player]
    nx, ny = p[0] + DIRS[d][0], p[1] + DIRS[d][1]
    chain, cx, cy = [], nx, ny
    while True:
        ci = crate_at(s, cx, cy)
        if ci < 0:
            break
        chain.append(ci)
        cx, cy = cx + DIRS[d][0], cy + DIRS[d][1]
    claimed = -1
    for ci in reversed(chain):
        c = s["crates"][ci]
        frm = slot_at(s, c[0], c[1])
        if frm >= 0 and s["owner"][frm] == player and (sc["anyGlyph"] or sc["slots"][frm]["g"] == c[2]):
            s["owner"][frm] = -1
        c[0] += DIRS[d][0]
        c[1] += DIRS[d][1]
        to = slot_at(s, c[0], c[1])
        if to >= 0 and s["owner"][to] < 0 and (sc["anyGlyph"] or sc["slots"][to]["g"] == c[2]):
            s["owner"][to] = player
            if claimed < 0:
                claimed = to
    s["pawns"][player][0] = nx
    s["pawns"][player][1] = ny
    s["moves"] += 1
    return claimed


def owned(s, player):
    return sum(1 for o in s["owner"] if o == player)


def all_claimed(s):
    return all(o >= 0 for o in s["owner"])


MOVE_CAP = 300   # hard backstop so a server game always terminates (two players can otherwise wander forever)


def over(s):
    m = majority(s)
    return (owned(s, 0) >= m or owned(s, 1) >= m or all_claimed(s)
            or s["passes"] >= 2 or s["moves"] >= MOVE_CAP)


def winner(s):
    m = majority(s)
    if owned(s, 0) >= m:
        return 0
    if owned(s, 1) >= m:
        return 1
    if s["passes"] >= 2 or all_claimed(s) or s["moves"] >= MOVE_CAP:
        o0, o1 = owned(s, 0), owned(s, 1)
        return 0 if o0 > o1 else (1 if o1 > o0 else -1)
    return -1


# ---- AI: planner (push-solver) + shallow alpha-beta fallback --------------------------------------

def _flood_reach(sc, sx, sy, blk):
    d = {_k(sx, sy): 1}
    q = [(sx, sy)]
    hd = 0
    while hd < len(q):
        cx, cy = q[hd]
        hd += 1
        for i in range(4):
            if not passable(sc, cx, cy, i):
                continue
            nx, ny = cx + DIRS[i][0], cy + DIRS[i][1]
            nk = _k(nx, ny)
            if nk in blk or nk in d:
                continue
            d[nk] = 1
            q.append((nx, ny))
    return d


def _with_key(obj, x, y):
    o = dict(obj)
    o[_k(x, y)] = 1
    return o


def _rep_of(reg):
    m = None
    for kk in reg:
        if m is None or kk < m:
            m = kk
    return m


def _pawn_field(s, player):
    sc = _sc(s)
    obst = {_k(c[0], c[1]): 1 for c in s["crates"]}
    o = s["pawns"][1 - player]
    obst[_k(o[0], o[1])] = 1
    p = s["pawns"][player]
    d = {_k(p[0], p[1]): 0}
    q = [(p[0], p[1])]
    hd = 0
    while hd < len(q):
        cx, cy = q[hd]
        hd += 1
        for j in range(4):
            if not passable(sc, cx, cy, j):
                continue
            nx, ny = cx + DIRS[j][0], cy + DIRS[j][1]
            nk = _k(nx, ny)
            if nk in obst or nk in d:
                continue
            d[nk] = d[_k(cx, cy)] + 1
            q.append((nx, ny))
    return d


def _push_solve(s, player, bi, gx, gy):
    sc = _sc(s)
    obst = {}
    for i, c in enumerate(s["crates"]):
        if i != bi:
            obst[_k(c[0], c[1])] = 1
    op = s["pawns"][1 - player]
    obst[_k(op[0], op[1])] = 1
    b0 = s["crates"][bi]
    p0 = s["pawns"][player]
    if b0[0] == gx and b0[1] == gy:
        return None
    reg0 = _flood_reach(sc, p0[0], p0[1], _with_key(obst, b0[0], b0[1]))
    q = [{"bx": b0[0], "by": b0[1], "reg": reg0, "push": 0, "first": None}]
    hd = 0
    seen = {"%d,%d:%s" % (b0[0], b0[1], _rep_of(reg0)): 1}
    cap = 700
    while hd < len(q):
        if hd > cap:
            return None
        st = q[hd]
        hd += 1
        for d in range(4):
            nbx, nby = st["bx"] + DIRS[d][0], st["by"] + DIRS[d][1]
            if not passable(sc, st["bx"], st["by"], d) or _k(nbx, nby) in obst:
                continue
            fx, fy = st["bx"] - DIRS[d][0], st["by"] - DIRS[d][1]
            if _k(fx, fy) not in st["reg"] or not passable(sc, fx, fy, d):
                continue
            first = st["first"] or {"from": (fx, fy), "dir": d}
            if nbx == gx and nby == gy:
                return {"pushes": st["push"] + 1, "from": first["from"], "dir": first["dir"]}
            nreg = _flood_reach(sc, st["bx"], st["by"], _with_key(obst, nbx, nby))
            key = "%d,%d:%s" % (nbx, nby, _rep_of(nreg))
            if key in seen:
                continue
            seen[key] = 1
            q.append({"bx": nbx, "by": nby, "reg": nreg, "push": st["push"] + 1, "first": first})
    return None


def _dist_field(s, tx, ty, player):
    sc = _sc(s)
    obst = {_k(c[0], c[1]): 1 for c in s["crates"]}
    op = s["pawns"][1 - player]
    obst[_k(op[0], op[1])] = 1
    d = {_k(tx, ty): 0}
    q = [(tx, ty)]
    hd = 0
    while hd < len(q):
        cx, cy = q[hd]
        hd += 1
        for j in range(4):
            if not passable(sc, cx, cy, j):
                continue
            nx, ny = cx + DIRS[j][0], cy + DIRS[j][1]
            nk = _k(nx, ny)
            if (nk in obst and not (nx == tx and ny == ty)) or nk in d:
                continue
            d[nk] = d[_k(cx, cy)] + 1
            q.append((nx, ny))
    return d


def _claim_plan(s, player):
    sc = _sc(s)
    slots, any_g = sc["slots"], sc["anyGlyph"]
    p = s["pawns"][player]
    best = None
    for gi, g in enumerate(slots):
        if s["owner"][gi] >= 0:
            continue
        for bi, c in enumerate(s["crates"]):
            if (not any_g and c[2] != g["g"]) or frozen(s, bi):
                continue
            sol = _push_solve(s, player, bi, g["x"], g["y"])
            if not sol:
                continue
            at_from = (p[0] == sol["from"][0] and p[1] == sol["from"][1])
            if at_from:
                walk = 0
            else:
                walk = _dist_field(s, sol["from"][0], sol["from"][1], player).get(_k(p[0], p[1]))
            if walk is None:
                continue
            cost = sol["pushes"] * 4 + walk       # pushes weigh more than walking
            if best is None or cost < best["cost"]:
                best = {"cost": cost, "sol": sol, "gi": gi}
    if best is None:
        return None
    sol = best["sol"]
    mv = -1
    if p[0] == sol["from"][0] and p[1] == sol["from"][1]:
        mv = sol["dir"]
    else:
        df = _dist_field(s, sol["from"][0], sol["from"][1], player)
        bd = 10 ** 9
        for d2 in range(4):
            if not can_move(s, player, d2):
                continue
            nx, ny = p[0] + DIRS[d2][0], p[1] + DIRS[d2][1]
            dd = df.get(_k(nx, ny))
            if dd is not None and dd < bd and crate_at(s, nx, ny) < 0:
                bd = dd
                mv = d2
    if mv < 0:
        return None
    return {"cost": best["cost"], "move": mv, "gi": best["gi"]}


def _step_to_push(s, player, frm, direction):
    p = s["pawns"][player]
    if p[0] == frm[0] and p[1] == frm[1]:
        return direction
    df = _dist_field(s, frm[0], frm[1], player)
    bd, mv = 10 ** 9, -1
    for d in range(4):
        if not can_move(s, player, d):
            continue
        nx, ny = p[0] + DIRS[d][0], p[1] + DIRS[d][1]
        dd = df.get(_k(nx, ny))
        if dd is not None and dd < bd and crate_at(s, nx, ny) < 0:
            bd = dd
            mv = d
    return mv


def _clear_plan(s, player):
    sc = _sc(s)
    p0 = s["pawns"][player]
    stat = {}
    op = s["pawns"][1 - player]
    stat[_k(op[0], op[1])] = 1
    mpos = []
    for i, c in enumerate(s["crates"]):
        if locked(s, i, player):
            stat[_k(c[0], c[1])] = 1
        else:
            mpos.append((c[0], c[1]))
    if not mpos:
        return None
    goal_open = {}
    any_open = False
    for gi, g in enumerate(sc["slots"]):
        if s["owner"][gi] < 0:
            goal_open[_k(g["x"], g["y"])] = 1
            any_open = True
    if not any_open:
        return None

    def occ(pos):
        return {_k(a[0], a[1]): 1 for a in pos}

    def region(pos, px, py):
        o = occ(pos)
        o.update(stat)
        r = _flood_reach(sc, px, py, o)
        return r, _rep_of(r)

    def pkey(pos):
        return ";".join(sorted("%d,%d" % (a[0], a[1]) for a in pos))
    r0, rep0 = region(mpos, p0[0], p0[1])
    q = [{"pos": mpos, "reg": r0, "first": None}]
    hd = 0
    seen = {pkey(mpos) + "|" + rep0: 1}
    cap = 5000
    while hd < len(q):
        if hd > cap:
            return None
        st = q[hd]
        hd += 1
        oc = occ(st["pos"])
        for j in range(len(st["pos"])):
            bx, by = st["pos"][j]
            for d in range(4):
                if not passable(sc, bx, by, d):
                    continue
                nbx, nby = bx + DIRS[d][0], by + DIRS[d][1]
                nk = _k(nbx, nby)
                if nk in oc or nk in stat:
                    continue
                fx, fy = bx - DIRS[d][0], by - DIRS[d][1]
                if _k(fx, fy) not in st["reg"] or not passable(sc, fx, fy, d):
                    continue
                first = st["first"] or {"from": (fx, fy), "dir": d}
                if nk in goal_open:
                    return {"from": first["from"], "dir": first["dir"]}
                npos = list(st["pos"])
                npos[j] = (nbx, nby)
                nreg, nrep = region(npos, bx, by)
                nkey = pkey(npos) + "|" + nrep
                if nkey in seen:
                    continue
                seen[nkey] = 1
                q.append({"pos": npos, "reg": nreg, "first": first})
    return None


def _slot_work(s, player, i, field):
    sc = _sc(s)
    pd = sc["pdist"][i]
    slots, any_g = sc["slots"], sc["anyGlyph"]
    best, box = 99, -1
    for ci, c in enumerate(s["crates"]):
        if (not any_g and c[2] != slots[i]["g"]) or frozen(s, ci):
            continue
        dd = pd.get(_k(c[0], c[1]))
        if dd is not None and dd < best:
            best, box = dd, ci
    if box < 0:
        return 22, 20
    if best == 0:
        return 0, 0
    c = s["crates"][box]
    pw = 20
    for di in range(4):
        nx, ny = c[0] + DIRS[di][0], c[1] + DIRS[di][1]
        if pd.get(_k(nx, ny)) != best - 1 or not passable(sc, c[0], c[1], di):
            continue
        bx, by = c[0] - DIRS[di][0], c[1] - DIRS[di][1]
        if blocked(s, bx, by) or crate_at(s, bx, by) >= 0:
            continue
        w = 0 if (s["pawns"][player][0] == bx and s["pawns"][player][1] == by) else field.get(_k(bx, by))
        if w is not None and w < pw:
            pw = w
    return best, pw


def _progress(s, player):
    field = _pawn_field(s, player)
    slots = _sc(s)["slots"]
    sum_pd, best_claim = 0, 60
    for i in range(len(slots)):
        if s["owner"][i] >= 0:
            continue
        pd, pw = _slot_work(s, player, i, field)
        sum_pd += min(pd, 20)
        claim = 2 * pd + pw
        if claim < best_claim:
            best_claim = claim
    return -(4 * sum_pd + 16 * min(best_claim, 40))


def _eval(s, me):
    if over(s):
        w = winner(s)
        return 10 ** 6 if w == me else (-10 ** 6 if w == 1 - me else 0)
    return 600 * (owned(s, me) - owned(s, 1 - me)) + _progress(s, me) - 0.9 * _progress(s, 1 - me)


def _ab(s, player, me, depth, alpha, beta):
    if over(s) or depth == 0:
        return _eval(s, me)
    moves = legal_dirs(s, player)
    if not moves:
        return _eval(s, me)
    if player == me:
        best = -1e9
        for mv in moves:
            c = clone_state(s)
            apply_dir(c, player, mv)
            best = max(best, _ab(c, 1 - player, me, depth - 1, alpha, beta))
            alpha = max(alpha, best)
            if beta <= alpha:
                break
        return best
    worst = 1e9
    for mv in moves:
        c = clone_state(s)
        apply_dir(c, player, mv)
        worst = min(worst, _ab(c, 1 - player, me, depth - 1, alpha, beta))
        beta = min(beta, worst)
        if beta <= alpha:
            break
    return worst


def ai_dir(s, player, depth=None):
    """Choose a direction (0-3) or PASS for `player` — the full planner from glyph_engine.js."""
    if depth is None:
        depth = max(_sc(s)["aiDepth"], 6)
    opp = 1 - player
    order = fresh_dirs(s, player)
    if not order:
        return PASS
    mine = _claim_plan(s, player)
    theirs = _claim_plan(s, opp)
    if theirs and (mine is None or theirs["cost"] + 3 < mine["cost"]):
        g = _sc(s)["slots"][theirs["gi"]]
        p = s["pawns"][player]
        if crate_at(s, g["x"], g["y"]) < 0:
            df = _dist_field(s, g["x"], g["y"], player)
            bd, mv = 10 ** 9, -1
            for d in range(4):
                if not can_move(s, player, d):
                    continue
                nx, ny = p[0] + DIRS[d][0], p[1] + DIRS[d][1]
                dd = df.get(_k(nx, ny))
                if dd is not None and dd < bd and crate_at(s, nx, ny) < 0:
                    bd, mv = dd, d
            if mv >= 0 and bd < 30 and mv in order:
                return mv
    if mine and mine["move"] in order:
        return mine["move"]
    if not mine:
        cp = _clear_plan(s, player)
        if cp:
            cm = _step_to_push(s, player, cp["from"], cp["dir"])
            if cm >= 0 and cm in order:
                return cm
        return PASS
    ordr = order[:]
    random.shuffle(ordr)
    best, pick = -1e9, ordr[0]
    for mv in ordr:
        c = clone_state(s)
        apply_dir(c, player, mv)
        v = _ab(c, opp, player, depth - 1, -1e9, 1e9)
        if v > best:
            best, pick = v, mv
    return pick


# ---- server interface -----------------------------------------------------------------------------

def initial(board_id):
    return new_game(board_id)


def legal_moves(state):
    """Legal ACTIONS for the side to move: each non-repeating step, plus PASS (always allowed)."""
    player = state["turn"]
    acts = [{"dir": d} for d in fresh_dirs(state, player)]
    acts.append({"dir": PASS})
    return acts


def _match(state, action):
    if not isinstance(action, dict):
        return None
    d = action.get("dir")
    if d is None:
        return None
    for m in legal_moves(state):
        if m["dir"] == d:
            return m
    return None


def apply_move(state, action):
    m = _match(state, action)
    if m is None:
        raise ValueError("illegal action")
    s = clone_state(state)
    apply_dir(s, s["turn"], m["dir"])
    remember(s)
    if winner(s) < 0:                 # game continues -> pass the turn
        s["turn"] = 1 - s["turn"]
    return s


def status(state):
    w = winner(state)
    ov = over(state)
    if not ov:
        return {"over": False, "result": None}
    result = "draw" if w < 0 else ("white" if w == 0 else "black")
    return {"over": True, "result": result}


class Board:
    """Mutable wrapper so the server can clone / validate / apply / serialize like the other action-engines.
    Actions are {"dir": 0-4} dicts."""

    def __init__(self, board_id=0):
        self.state = initial(board_id)

    def clone(self):
        b = Board.__new__(Board)
        b.state = clone_state(self.state)
        return b

    @property
    def to_move(self):
        return self.state["turn"]

    @property
    def modes(self):
        return set()

    def is_legal(self, action, owner=None):
        if owner is not None and owner != self.state["turn"]:
            return False
        return _match(self.state, action) is not None

    def apply(self, action):
        self.state = apply_move(self.state, action)

    @property
    def winner(self):
        w = winner(self.state)
        if not over(self.state):
            return None
        return "draw" if w < 0 else w


def serialize(board, draw_agreed=False):
    s = board.state
    sc = _sc(s)
    w = winner(s)
    ov = over(s) or draw_agreed
    win = None
    if draw_agreed:
        win = "draw"
    elif over(s):
        win = "draw" if w < 0 else w
    return {
        "board_index": s["mi"], "board_name": sc["name"],
        "W": sc["W"], "H": sc["H"],
        "walls": list(sc["walls"].keys()),
        "edges": sc["edgeRender"],
        "anyGlyph": sc["anyGlyph"],
        "slots": [[o["x"], o["y"], o["g"]] for o in sc["slots"]],
        "crates": [[c[0], c[1], c[2]] for c in s["crates"]],
        "pawns": [[p[0], p[1]] for p in s["pawns"]],
        "owner": s["owner"][:],
        "turn": s["turn"], "passes": s["passes"], "moves": s["moves"],
        "need": majority(s), "goals": len(sc["slots"]),
        "over": bool(ov), "winner": win,
        "legal": [] if ov else [m["dir"] for m in legal_moves(s)],
    }


def ai_move(state, difficulty="normal", time_ms=None):
    depth = max(_DEPTH.get(difficulty, 6), _sc(state)["aiDepth"])
    d = ai_dir(state, state["turn"], depth)
    return {"dir": d}


def ai_action(board, difficulty="normal"):
    """AI action for the Board wrapper (matches hexago_engine.ai_action(board, difficulty))."""
    return ai_move(board.state, difficulty)


def explain_action(board, action, owner):
    names = {0: "up", 1: "down", 2: "left", 3: "right", PASS: "pass"}
    return {"text": names.get(action.get("dir"), "?")}


def boards():
    """Board catalogue for the client's board picker (online games)."""
    out = {}
    for i, sc in enumerate(MAZES):
        out[str(i)] = {"name": sc["name"], "size": "%dx%d" % (sc["W"], sc["H"]),
                       "goals": len(sc["slots"]), "generic": sc["anyGlyph"],
                       "expert": "★" in sc["name"]}
    return out
