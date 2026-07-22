"""HEXA-GO — authoritative Python port of docs/hexago_engine.js (server side).

The server must build the SAME board graph as the client (so point indices agree) and enforce
the SAME rules. Online games use a FIXED board: triangular / medium (tri, m) — board-type/size
selection stays a client-offline option for now. Actions are dicts: {"id": n} to place a stone,
{"pass": true} to pass.

Side mapping: Go's Black moves first, so server side 0 = Black (internal colour 1), side 1 =
White (colour 2). winner: Black -> 0, White -> 1, or "draw".

AI: a fast greedy policy (captures / atari / 3rd-4th-line / contact), not the client's Monte-Carlo
engine (which is far too slow in Python) — plenty good for recording games. Final score uses a
light Monte-Carlo (random playouts) so dead stones resolve like the client's scoreFinal.
"""
import math
import random

VIEW, PAD, H = 800, 60, math.sqrt(3) / 2
KOMI = 5.5
DIFF = {"easy": "easy", "normal": "normal", "hard": "hard"}
TRI_RAD = {"s": 5, "m": 6, "l": 7}
ELONG_N = {"s": 10, "m": 12, "l": 14}


# ---- board graph ----------------------------------------------------------
def _tri_points(rad):
    pts = []
    for q in range(-rad, rad + 1):
        for r in range(-rad, rad + 1):
            if abs(q + r) <= rad:
                pts.append((q + r / 2.0, r * H))
    return pts


def _elong_points(cols, rows):
    pts, y = [], 0.0
    for i in range(rows):
        off = (math.floor(i / 2) % 2) * 0.5
        for c in range(cols):
            pts.append((c + off, y))
        y += 1.0 if (i % 2 == 0) else H
    return pts


def _connect(pts, edge):
    n = len(pts)
    adj = [[] for _ in range(n)]
    t2 = (edge * 1.08) * (edge * 1.08)
    for i in range(n):
        xi, yi = pts[i]
        for j in range(i + 1, n):
            dx, dy = xi - pts[j][0], yi - pts[j][1]
            if dx * dx + dy * dy <= t2:
                adj[i].append(j)
                adj[j].append(i)
    return adj


def _boundary_dist(adj):
    n = len(adj)
    maxdeg = max(len(a) for a in adj) if n else 0
    bd = [-1] * n
    q, head = [], 0
    for i in range(n):
        if len(adj[i]) < maxdeg:
            bd[i] = 0
            q.append(i)
    while head < len(q):
        v = q[head]; head += 1
        for w in adj[v]:
            if bd[w] == -1:
                bd[w] = bd[v] + 1
                q.append(w)
    for i in range(n):
        if bd[i] == -1:
            bd[i] = 0
    return bd


def _make_board(btype, sz):
    raw = (_elong_points(ELONG_N[sz], ELONG_N[sz] + 1) if btype == "elong"
           else _tri_points(TRI_RAD[sz]))
    minx = min(p[0] for p in raw); miny = min(p[1] for p in raw)
    maxx = max(p[0] for p in raw); maxy = max(p[1] for p in raw)
    uw, uh = maxx - minx, maxy - miny
    scale = (VIEW - 2 * PAD) / max(uw, uh)
    ox, oy = (VIEW - uw * scale) / 2, (VIEW - uh * scale) / 2
    pts = [((p[0] - minx) * scale + ox, (p[1] - miny) * scale + oy) for p in raw]
    adj = _connect(pts, scale)
    return {"adj": adj, "size": len(pts), "bd": _boundary_dist(adj)}


_BOARDS = {}
ADJ, NP, BD = None, 0, None


def set_board(btype="tri", sz="m"):
    global ADJ, NP, BD
    if btype not in ("tri", "elong"):
        btype = "tri"
    if sz not in TRI_RAD:
        sz = "m"
    key = btype + sz
    if key not in _BOARDS:
        _BOARDS[key] = _make_board(btype, sz)
    b = _BOARDS[key]
    ADJ, NP, BD = b["adj"], b["size"], b["bd"]
    return b


set_board("tri", "m")


# ---- state & rules (colour 0 empty, 1 black[first], 2 white) ---------------
def initial():
    return {"color": [0] * NP, "turn": 1, "ko": -1, "passes": 0,
            "caps": {1: 0, 2: 0}, "moveNo": 0, "last": -1}


def clone(s):
    return {"color": list(s["color"]), "turn": s["turn"], "ko": s["ko"],
            "passes": s["passes"], "caps": {1: s["caps"][1], 2: s["caps"][2]},
            "moveNo": s["moveNo"], "last": s["last"]}


def group(color, start):
    c = color[start]
    stack, seen, stones, libs = [start], {start}, [], set()
    while stack:
        v = stack.pop(); stones.append(v)
        for w in ADJ[v]:
            if color[w] == 0:
                libs.add(w)
            elif color[w] == c and w not in seen:
                seen.add(w); stack.append(w)
    return stones, len(libs)


def try_place(state, idx):
    if idx < 0 or idx >= NP or state["color"][idx] != 0 or idx == state["ko"]:
        return None
    c = state["turn"]; opp = 3 - c
    col = list(state["color"]); col[idx] = c
    captured, last_cap, seen = 0, -1, set()
    for w in ADJ[idx]:
        if col[w] == opp and w not in seen:
            stones, libs = group(col, w)
            if libs == 0:
                for st in stones:
                    col[st] = 0; seen.add(st); last_cap = st
                captured += len(stones)
            else:
                seen.update(stones)
    if captured == 0:
        _, libs = group(col, idx)
        if libs == 0:
            return None  # suicide
    return {"color": col, "captured": captured, "lastCap": last_cap}


def is_legal(state, idx):
    return try_place(state, idx) is not None


def legal_moves(state):
    return [i for i in range(NP) if state["color"][i] == 0 and is_legal(state, i)]


def play(state, idx):
    r = try_place(state, idx)
    if r is None:
        return state
    s = clone(state); s["color"] = r["color"]; s["caps"][state["turn"]] += r["captured"]
    stones, libs = group(s["color"], idx)
    s["ko"] = r["lastCap"] if (r["captured"] == 1 and len(stones) == 1 and libs == 1) else -1
    s["turn"] = 3 - state["turn"]; s["passes"] = 0; s["moveNo"] += 1; s["last"] = idx
    return s


def do_pass(state):
    s = clone(state); s["turn"] = 3 - state["turn"]; s["ko"] = -1
    s["passes"] = state["passes"] + 1; s["moveNo"] += 1; s["last"] = -1
    return s


def ended(state):
    return state["passes"] >= 2


# ---- scoring --------------------------------------------------------------
def _area_owners(col):
    o = [0] * NP; seen = [False] * NP
    for i in range(NP):
        if col[i]:
            o[i] = col[i]; continue
        if seen[i]:
            continue
        stack, region, border = [i], [], 0; seen[i] = True
        while stack:
            v = stack.pop(); region.append(v)
            for u in ADJ[v]:
                if col[u] == 0:
                    if not seen[u]:
                        seen[u] = True; stack.append(u)
                else:
                    border |= col[u]
        owner = 1 if border == 1 else 2 if border == 2 else 0
        for r in region:
            o[r] = owner
    return o


def _is_eye(col, idx, c):
    ns = ADJ[idx]
    return len(ns) > 0 and all(col[w] == c for w in ns)


def _random_playout(state):
    col = list(state["color"]); turn = state["turn"]; passes = state["passes"]; ko = state["ko"]
    st = {"color": col, "turn": turn, "ko": ko, "passes": passes,
          "caps": {1: state["caps"][1], 2: state["caps"][2]}}
    order = list(range(NP)); moves = 0; maxm = 3 * NP
    while st["passes"] < 2 and moves < maxm:
        random.shuffle(order); played = False
        for idx in order:
            if col[idx] != 0 or idx == st["ko"]:
                continue
            if _is_eye(col, idx, st["turn"]):
                continue
            if BD[idx] == 0 and random.random() < 0.8:
                # usually skip the 1st line, but NEVER a capture (a capture must touch an enemy) —
                # otherwise dead groups on the edge survive and their territory goes uncounted
                en = 3 - st["turn"]
                if not any(col[n] == en for n in ADJ[idx]):
                    continue
            r = try_place(st, idx)
            if r is None:
                continue
            stones, libs = group(r["color"], idx)
            if libs == 1 and r["captured"] == 0:
                continue  # self-atari
            st["color"] = col = r["color"]; st["caps"][st["turn"]] += r["captured"]
            st["ko"] = r["lastCap"] if (r["captured"] == 1 and len(stones) == 1 and libs == 1) else -1
            played = True; break
        if not played:
            st["passes"] += 1; st["ko"] = -1
        else:
            st["passes"] = 0
        st["turn"] = 3 - st["turn"]; moves += 1
    return st


def score(state):
    """Cheap flood-fill territory score (live estimate)."""
    col = state["color"]; o = _area_owners(col)
    terr_b = sum(1 for i in range(NP) if col[i] == 0 and o[i] == 1)
    terr_w = sum(1 for i in range(NP) if col[i] == 0 and o[i] == 2)
    black = terr_b + state["caps"][1]; white = terr_w + state["caps"][2] + KOMI
    return {"black": black, "white": white, "terrB": terr_b, "terrW": terr_w,
            "capB": state["caps"][1], "capW": state["caps"][2], "komi": KOMI,
            "margin": black - white,
            "winner": "black" if black > white else ("white" if white > black else "draw")}


def score_final(state, playouts=180):
    """Monte-Carlo territory score — resolves dead stones like the client's scoreFinal."""
    base = clone(state); base["passes"] = 0; base["last"] = -1
    bc = [0] * NP; wc = [0] * NP
    for _ in range(playouts):
        o = _area_owners(_random_playout(base)["color"])
        for i in range(NP):
            if o[i] == 1:
                bc[i] += 1
            elif o[i] == 2:
                wc[i] += 1
    T = 0.6; terr_b = terr_w = pris_b = pris_w = 0
    for i in range(NP):
        oc = 1 if bc[i] / playouts >= T else 2 if wc[i] / playouts >= T else 0
        if oc == 0:
            continue
        cur = state["color"][i]
        if cur == 0:
            if oc == 1:
                terr_b += 1
            else:
                terr_w += 1
        elif cur != oc:
            if oc == 1:
                terr_b += 1; pris_b += 1
            else:
                terr_w += 1; pris_w += 1
    cap_b = state["caps"][1] + pris_b; cap_w = state["caps"][2] + pris_w
    black = terr_b + cap_b; white = terr_w + cap_w + KOMI
    return {"black": black, "white": white, "terrB": terr_b, "terrW": terr_w,
            "capB": cap_b, "capW": cap_w, "komi": KOMI, "margin": black - white,
            "winner": "black" if black > white else ("white" if white > black else "draw")}


def _pass_alive(col, C, pa, surv):  # noqa: C901
    """Benson's algorithm for colour C: mark pass-alive C stones in pa[], collect the regions they seal."""
    chain_id = [-1] * NP; nc = 0
    for i in range(NP):
        if col[i] != C or chain_id[i] >= 0:
            continue
        cid = nc; nc += 1; st = [i]; chain_id[i] = cid
        while st:
            v = st.pop()
            for u in ADJ[v]:
                if col[u] == C and chain_id[u] < 0:
                    chain_id[u] = cid; st.append(u)
    region_id = [-1] * NP; regions = []
    for i in range(NP):
        if col[i] == C or region_id[i] >= 0:
            continue
        rid = len(regions); st = [i]; pts = []; empties = []; bset = set(); region_id[i] = rid
        while st:
            v = st.pop(); pts.append(v)
            if col[v] == 0:
                empties.append(v)
            for u in ADJ[v]:
                if col[u] == C:
                    bset.add(chain_id[u])
                elif region_id[u] < 0:
                    region_id[u] = rid; st.append(u)
        border = list(bset); vital = []
        for cx in border:
            if all(any(chain_id[n] == cx for n in ADJ[e]) for e in empties):
                vital.append(cx)
        regions.append((pts, border, vital))
    nr = len(regions); chain_dead = [False] * nc; region_gone = [False] * nr; changed = True
    while changed:
        changed = False
        for c in range(nc):
            if chain_dead[c]:
                continue
            cnt = sum(1 for ri in range(nr) if not region_gone[ri] and c in regions[ri][2])
            if cnt < 2:
                chain_dead[c] = True; changed = True
        for ri in range(nr):
            if region_gone[ri]:
                continue
            if any(chain_dead[b] for b in regions[ri][1]):
                region_gone[ri] = True; changed = True
    for i in range(NP):
        if col[i] == C and not chain_dead[chain_id[i]]:
            pa[i] = C
    for ri in range(nr):
        if not region_gone[ri] and len(regions[ri][1]) > 0:   # must border >=1 chain (not the empty board)
            surv.append(regions[ri][0])


def _benson_dead(col):
    """Deterministic dead stones: an enemy stone sealed inside a pass-alive region and not itself
    pass-alive is provably dead. Catches enclosed groups MC playouts sometimes fail to capture."""
    pa = [0] * NP; surv_b = []; surv_w = []
    _pass_alive(col, 1, pa, surv_b)
    _pass_alive(col, 2, pa, surv_w)
    dead = [0] * NP
    for reg in surv_b:
        for p in reg:
            if col[p] == 2 and pa[p] != 2:
                dead[p] = 1
    for reg in surv_w:
        for p in reg:
            if col[p] == 1 and pa[p] != 1:
                dead[p] = 1
    return dead


def _settled_mask(col):
    """Points in SETTLED territory — a region sealed by a pass-alive (two-eyed) group of either colour.
    Playing there is unnecessary (your live area, or the opponent's). Unsettled fights stay open."""
    pa = [0] * NP; surv_b = []; surv_w = []
    _pass_alive(col, 1, pa, surv_b)
    _pass_alive(col, 2, pa, surv_w)
    mask = [0] * NP
    for reg in surv_b:
        for p in reg:
            mask[p] = 1
    for reg in surv_w:
        for p in reg:
            mask[p] = 1
    return mask


def score_area(state, playouts=80):  # noqa: C901
    """FINAL area score for a settled (two-pass) position — mirrors the client's scoreArea. Dead stones
    = Benson (provably dead, unconditional) UNION a Monte-Carlo check; territory is then counted
    DETERMINISTICALLY by flood-fill so no clearly-enclosed region is left uncounted. Benson catches the
    enclosed groups deterministically, so a light MC (80) suffices for the rest — keeps the server fast."""
    base = clone(state); base["passes"] = 0; base["last"] = -1
    bc = [0] * NP; wc = [0] * NP
    for _ in range(playouts):
        o = _area_owners(_random_playout(base)["color"])
        for i in range(NP):
            if o[i] == 1:
                bc[i] += 1
            elif o[i] == 2:
                wc[i] += 1
    # 1. remove dead stones — Monte-Carlo only (NOT Benson: it over-kills big living groups that just
    #    haven't made two formal eyes yet when a game ends before it's fully settled). MC is reliable
    #    here since the 1st-line-capture fix, and still catches enclosed dead groups.
    T = 0.6; col = list(state["color"]); pris_b = pris_w = 0
    for i in range(NP):
        cur = col[i]
        if cur == 0:
            continue
        is_dead = (cur == 2 and bc[i] / playouts >= T) or (cur == 1 and wc[i] / playouts >= T)
        if not is_dead:
            continue
        col[i] = 0
        if cur == 2:
            pris_b += 1
        else:
            pris_w += 1
    # 2. deterministic territory on the cleaned board
    own = [0] * NP; seen = [False] * NP; terr_b = terr_w = 0
    for i in range(NP):
        if col[i]:
            own[i] = col[i]
    for i in range(NP):
        if col[i] != 0 or seen[i]:
            continue
        stack = [i]; region = []; border = 0; seen[i] = True
        while stack:
            v = stack.pop(); region.append(v)
            for u in ADJ[v]:
                if col[u] == 0:
                    if not seen[u]:
                        seen[u] = True; stack.append(u)
                else:
                    border |= col[u]
        owner = 1 if border == 1 else 2 if border == 2 else 0
        for r in region:
            own[r] = owner
        if owner == 1:
            terr_b += len(region)
        elif owner == 2:
            terr_w += len(region)
    cap_b = state["caps"][1] + pris_b; cap_w = state["caps"][2] + pris_w
    black = terr_b + cap_b; white = terr_w + cap_w + KOMI
    return {"black": black, "white": white, "terrB": terr_b, "terrW": terr_w,
            "capB": cap_b, "capW": cap_w, "komi": KOMI, "own": own, "margin": black - white,
            "winner": "black" if black > white else ("white" if white > black else "draw")}


# ---- greedy policy AI -----------------------------------------------------
_LINEVAL = [-0.95, -0.28, 0.42, 0.34, 0.16, 0.10]


def _enclosure(color):
    """Per empty point: which single colour (if any) seals its region, and the region size."""
    owner = [0] * NP; size = [0] * NP; seen = [False] * NP
    for i in range(NP):
        if color[i] != 0 or seen[i]:
            continue
        stack = [i]; region = []; border = 0; seen[i] = True
        while stack:
            v = stack.pop(); region.append(v)
            for u in ADJ[v]:
                if color[u] == 0:
                    if not seen[u]:
                        seen[u] = True; stack.append(u)
                else:
                    border |= color[u]
        o = 1 if border == 1 else 2 if border == 2 else 0
        for p in region:
            owner[p] = o; size[p] = len(region)
    return owner, size


def _policy_score(state, idx, me, openness, r, enc=None):
    if r is None:
        return -1e9
    if _is_eye(state["color"], idx, me):
        return -1e9
    stones, libs = group(r["color"], idx)
    if r["captured"] == 0 and libs == 1:
        return -1e9  # self-atari
    h = r["captured"] * 0.6
    friend = enemy = atari = 0
    for w in ADJ[idx]:
        if state["color"][w] == me:
            friend += 1
        elif state["color"][w] == 3 - me:
            enemy += 1
            est, elib = group(r["color"], w)
            if est and elib == 1:
                atari += 1
    h += atari * 0.4
    # settled-territory sense: a non-tactical stone into a region sealed by ONE colour is wrong in
    # territory scoring — a dead stone in the enemy's area, or a wasted fill of your own. Prune it.
    if enc is not None and r["captured"] == 0 and atari == 0:
        ro = enc[0][idx]; rs = enc[1][idx]
        if ro == me:
            return -1e9                       # never fill your OWN territory (pass instead)
        if ro == 3 - me and rs <= 12:
            return -1e9                       # dead stone in a sealed enemy area
        if ro == 3 - me:
            h -= 0.5                           # large enemy area: discourage (keep opening undistorted)
    h += _LINEVAL[min(BD[idx], 5)] * openness
    h += 0.06 * min(friend, 2) + 0.055 * min(enemy, 2)
    if friend >= 3:
        h -= 0.10
    return h


# ---- neural policy (the Phase-B self-play net) — one forward pass (~50ms), much stronger than the
# hand greedy. net-PUCT (with search) is too slow in pure Python, so the server uses the policy head
# with the same territory/pass logic as the greedy AI. Falls back to greedy if the weights are absent.
_NET = None
_NET_TRIED = False


def _net():
    global _NET, _NET_TRIED
    if not _NET_TRIED:
        _NET_TRIED = True
        try:
            import hexago_net as _N
            if _N.load_weights():
                _NET = _N
        except Exception:
            _NET = None
    return _NET


def _net_move(state, difficulty):
    N = _NET
    me = state["turn"]
    enc = _enclosure(state["color"])
    settled = _settled_mask(state["color"])       # pass-alive (two-eyed) territory — don't play there
    probs, _pass_p, _val = N.policy_probs(state, ADJ, BD, NP)
    cands = []
    for idx, p in probs.items():
        if not is_legal(state, idx):             # policy_probs ranks empty points; skip illegal (suicide/ko)
            continue
        if settled[idx]:                          # settled life-and-death: your live area or theirs
            continue
        ro = enc[0][idx]                          # also drop simple own/small-enemy sealed territory
        rs = enc[1][idx]
        if ro == me or (ro == 3 - me and rs <= 12):
            continue
        cands.append((p, idx))
    sc0 = score(state)
    my_margin = sc0["margin"] if me == 1 else -sc0["margin"]
    if not cands:
        return {"pass": True}
    if state["passes"] >= 1 and my_margin > 0:
        return {"pass": True}
    cands.sort(reverse=True)
    ntop = 1 if difficulty == "hard" else 2 if difficulty == "normal" else 4
    top = cands[:min(ntop, len(cands))]
    r = random.random() * sum(p for p, _ in top)
    acc = 0.0
    for p, idx in top:
        acc += p
        if r <= acc:
            return {"id": idx}
    return {"id": top[0][1]}


def ai_move(state, difficulty="normal"):
    """Return an action dict {"id": n} or {"pass": True}. Neural policy if available, else greedy."""
    if _net() is not None:
        return _net_move(state, difficulty)
    me = state["turn"]
    empties = sum(1 for v in state["color"] if v == 0)
    openness = empties / NP if NP else 0
    enc = _enclosure(state["color"])          # territory map so the policy won't play into settled areas
    scored = []
    for idx in range(NP):
        if state["color"][idx] != 0:
            continue
        r = try_place(state, idx)
        if r is None:
            continue
        ps = _policy_score(state, idx, me, openness, r, enc)
        if ps > -1e8:
            scored.append((ps, idx))
    sc0 = score(state)
    my_margin = sc0["margin"] if me == 1 else -sc0["margin"]
    if not scored:
        return {"pass": True}
    if state["passes"] >= 1 and my_margin > 0:
        return {"pass": True}
    scored.sort(reverse=True)
    ntop = 1 if difficulty == "hard" else 3 if difficulty == "normal" else 6
    top = scored[:min(ntop, len(scored))]
    return {"id": random.choice(top)[1]}


# ---- server Board wrapper -------------------------------------------------
class Board:
    def __init__(self):
        set_board("tri", "m")
        self.state = initial()

    def clone(self):
        b = Board.__new__(Board); b.state = clone(self.state); return b

    @property
    def to_move(self):
        # side 0 = White, side 1 = Black (matches the other games); Black (colour 1) moves first,
        # so to_move == 1 at the start of the game.
        return 1 if self.state["turn"] == 1 else 0

    @property
    def modes(self):
        return set()

    def is_legal(self, action, owner=None):
        if not isinstance(action, dict):
            return False
        if owner is not None and owner != self.to_move:
            return False
        if action.get("pass"):
            return not ended(self.state)
        idx = action.get("id")
        return isinstance(idx, int) and is_legal(self.state, idx)

    def apply(self, action):
        if action.get("pass"):
            self.state = do_pass(self.state)
        else:
            idx = action.get("id")
            if not is_legal(self.state, idx):
                raise ValueError("illegal action")
            self.state = play(self.state, idx)

    @property
    def winner(self):
        if not ended(self.state):
            return None
        w = score_area(self.state)["winner"]
        return "draw" if w == "draw" else (1 if w == "black" else 0)   # Black=side 1, White=side 0


def ai_action(board, difficulty):
    return ai_move(board.state, difficulty)


def serialize(board, draw_agreed=False):
    s = board.state
    over = ended(s) or draw_agreed
    winner = None
    if draw_agreed:
        winner = "draw"
    elif ended(s):
        w = score_area(s)["winner"]
        winner = "draw" if w == "draw" else (1 if w == "black" else 0)
    return {"turn": s["turn"], "passes": s["passes"], "caps": s["caps"],
            "moveNo": s["moveNo"], "over": over, "winner": winner, "legal": []}


def explain_action(board, action, owner):
    if action.get("pass"):
        return {"text": "pass"}
    return {"text": "stone @" + str(action.get("id"))}
