"""OCTACHESS — authoritative Python port of docs/octachess_engine.js.

Faithful line-for-line translation so the server can validate & store games. Move
generation order mirrors the JS (dict insertion order preserved) so AI choices match.
Moves/actions are dicts: {"from": key, "to": key, "promo": "Q"|None}. Castling is
detected by the engine (king octagon-slide of two files), promotion via "promo".
"""
import time

N, G = 8, 7
HEAVY = {"R": True, "Q": True}
VAL = {"P": 100, "N": 330, "B": 320, "R": 500, "Q": 900, "K": 20000, "W": 300}
DIFF = {"easy": "easy", "normal": "normal", "hard": "hard"}


# ---- coordinate helpers ---------------------------------------------------
def key_at(x, y):
    if x < 0 or y < 0:
        return None
    ex, ey = x & 1, y & 1
    if ex == 0 and ey == 0:
        c, r = x >> 1, y >> 1
        return "o:%d:%d" % (r, c) if (c < N and r < N) else None
    if ex == 1 and ey == 1:
        gc, gr = (x - 1) >> 1, (y - 1) >> 1
        return "g:%d:%d" % (gr, gc) if (gc < G and gr < G) else None
    return None


def xy_of(k):
    p = k.split(":")
    r, c = int(p[1]), int(p[2])
    return (2 * c, 2 * r) if p[0] == "o" else (2 * c + 1, 2 * r + 1)


def is_gate(k):
    return k[0] == "g"


def cell(t, r, c):
    return "%s:%d:%d" % (t, r, c)


def label(k):
    p = k.split(":")
    r, c = int(p[1]), int(p[2])
    files = "abcdefgh"
    if p[0] == "o":
        return files[c] + str(8 - r)
    return "♢" + files[c] + str(8 - r)


# ---- state ----------------------------------------------------------------
def clone_state(s):
    return {
        "board": dict(s["board"]),
        "turn": s["turn"],
        "castle": {0: dict(s["castle"][0]), 1: dict(s["castle"][1])},
        "half": s["half"], "full": s["full"],
    }


def initial(warden=False):
    b = {}
    back = ["R", "N", "B", "Q", "K", "B", "N", "R"]
    for c in range(8):
        b[cell("o", 0, c)] = {"t": back[c], "s": 1}
        b[cell("o", 1, c)] = {"t": "P", "s": 1}
        b[cell("o", 6, c)] = {"t": "P", "s": 0}
        b[cell("o", 7, c)] = {"t": back[c], "s": 0}
    if warden:
        b.pop(cell("o", 7, 1), None)
        b.pop(cell("o", 0, 6), None)
        b[cell("g", 6, 1)] = {"t": "W", "s": 0}
        b[cell("g", 0, 5)] = {"t": "W", "s": 1}
    return {"board": b, "turn": 0, "castle": {0: {"k": True, "q": True}, 1: {"k": True, "q": True}},
            "half": 0, "full": 1}


DIAG = [(1, 1), (1, -1), (-1, 1), (-1, -1)]
ORTH = [(2, 0), (-2, 0), (0, 2), (0, -2)]
KNIGHT = [(4, 2), (4, -2), (-4, 2), (-4, -2), (2, 4), (2, -4), (-2, 4), (-2, -4)]
WARDEN = [(2, 0), (-2, 0), (0, 2), (0, -2)]


def _slide(board, x, y, dx, dy, side, allow_gate, out):
    nx, ny = x + dx, y + dy
    while True:
        k = key_at(nx, ny)
        if not k:
            break
        occ = board.get(k)
        gate = is_gate(k)
        if occ:
            if occ["s"] != side and not (gate and not allow_gate):
                out.append({"to": k, "cap": True})
            break
        if allow_gate or not gate:
            out.append({"to": k, "cap": False})
        nx += dx; ny += dy


def piece_moves(state, k, attacks_only, out):
    board = state["board"]
    p = board[k]
    side = p["s"]
    x, y = xy_of(k)
    t = p["t"]
    if t == "R":
        for dx, dy in ORTH:
            _slide(board, x, y, dx, dy, side, False, out)
    elif t == "B":
        for dx, dy in DIAG:
            _slide(board, x, y, dx, dy, side, True, out)
    elif t == "Q":
        for dx, dy in ORTH:
            _slide(board, x, y, dx, dy, side, False, out)
        for dx, dy in DIAG:
            _slide(board, x, y, dx, dy, side, False, out)
    elif t == "N":
        for dx, dy in KNIGHT:
            nk = key_at(x + dx, y + dy)
            if not nk:
                continue
            occ = board.get(nk)
            if not occ:
                out.append({"to": nk, "cap": False})
            elif occ["s"] != side:
                out.append({"to": nk, "cap": True})
    elif t == "W":
        for dx, dy in WARDEN:
            nk = key_at(x + dx, y + dy)
            if not nk:
                continue
            occ = board.get(nk)
            if not occ:
                out.append({"to": nk, "cap": False})
            elif occ["s"] != side:
                out.append({"to": nk, "cap": True})
    elif t == "K":
        if is_gate(k):
            for dx, dy in DIAG:
                nk = key_at(x + dx, y + dy)
                if not nk:
                    continue
                occ = board.get(nk)
                if not occ:
                    out.append({"to": nk, "cap": False})
                elif occ["s"] != side:
                    out.append({"to": nk, "cap": True})
        else:
            for dx, dy in ORTH:
                nk = key_at(x + dx, y + dy)
                if not nk:
                    continue
                occ = board.get(nk)
                if not occ:
                    out.append({"to": nk, "cap": False})
                elif occ["s"] != side:
                    out.append({"to": nk, "cap": True})
            for dx, dy in DIAG:
                gk = key_at(x + dx, y + dy)
                if not gk:
                    continue
                gocc = board.get(gk)
                if not gocc:
                    out.append({"to": gk, "cap": False})
                elif gocc["s"] != side:
                    out.append({"to": gk, "cap": True})
                if not gocc:
                    dk = key_at(x + 2 * dx, y + 2 * dy)
                    if not dk:
                        continue
                    occ = board.get(dk)
                    if not occ:
                        out.append({"to": dk, "cap": False})
                    elif occ["s"] != side:
                        out.append({"to": dk, "cap": True})
    elif t == "P":
        dir = -1 if side == 0 else 1
        if is_gate(k):
            for d in (-1, 1):
                nk = key_at(x + d, y + dir)
                if not nk:
                    continue
                occ = board.get(nk)
                if attacks_only:
                    out.append({"to": nk, "cap": bool(occ)})
                    continue
                if not occ:
                    out.append({"to": nk, "cap": False})
                elif occ["s"] != side:
                    out.append({"to": nk, "cap": True})
        else:
            for d in (-1, 1):
                nk = key_at(x + d, y + dir)
                if not nk:
                    continue
                occ = board.get(nk)
                far_k = key_at(x + 2 * d, y + 2 * dir)
                if attacks_only:
                    out.append({"to": nk, "cap": bool(occ)})
                    if not occ and far_k:
                        out.append({"to": far_k, "cap": True})
                    continue
                if occ:
                    if occ["s"] != side:
                        out.append({"to": nk, "cap": True})
                elif far_k:
                    far_occ = board.get(far_k)
                    if far_occ and far_occ["s"] != side:
                        out.append({"to": far_k, "cap": True})
            if not attacks_only:
                nk = key_at(x, y + 2 * dir)
                if nk and nk not in board:
                    out.append({"to": nk, "cap": False})
                    home_r = 6 if side == 0 else 1
                    if (y >> 1) == home_r:
                        nk2 = key_at(x, y + 4 * dir)
                        if nk2 and nk2 not in board:
                            out.append({"to": nk2, "cap": False})


def attacked_by(state, target_key, by_side):
    board = state["board"]
    for k in board:
        if board[k]["s"] != by_side:
            continue
        buf = []
        piece_moves(state, k, True, buf)
        for m in buf:
            if m["to"] == target_key:
                return True
    return False


def king_key(state, side):
    for k in state["board"]:
        p = state["board"][k]
        if p["t"] == "K" and p["s"] == side:
            return k
    return None


def in_check(state, side):
    kk = king_key(state, side)
    return attacked_by(state, kk, side ^ 1) if kk else False


def apply_move(state, m):
    s = clone_state(state)
    b = s["board"]
    side = state["turn"]
    p = b[m["from"]]
    cap = b.get(m["to"])
    del b[m["from"]]
    b[m["to"]] = {"t": m.get("promo") or p["t"], "s": side}
    if m.get("castle"):
        rr = 7 if side == 0 else 0
        if m["castle"] == "k":
            b[cell("o", rr, 5)] = b[cell("o", rr, 7)]; del b[cell("o", rr, 7)]
        else:
            b[cell("o", rr, 3)] = b[cell("o", rr, 0)]; del b[cell("o", rr, 0)]
    if p["t"] == "K":
        s["castle"][side]["k"] = False; s["castle"][side]["q"] = False
    if p["t"] == "R":
        hr = 7 if side == 0 else 0
        if m["from"] == cell("o", hr, 0):
            s["castle"][side]["q"] = False
        if m["from"] == cell("o", hr, 7):
            s["castle"][side]["k"] = False
    er = 0 if side == 0 else 7
    if m["to"] == cell("o", er, 0):
        s["castle"][side ^ 1]["q"] = False
    if m["to"] == cell("o", er, 7):
        s["castle"][side ^ 1]["k"] = False
    s["half"] = 0 if (p["t"] == "P" or cap) else s["half"] + 1
    if side == 1:
        s["full"] += 1
    s["turn"] = side ^ 1
    return s


def castling_moves(state, side, out):
    if in_check(state, side):
        return
    hr = 7 if side == 0 else 0
    b = state["board"]
    k_from = cell("o", hr, 4)
    if k_from not in b or b[k_from]["t"] != "K":
        return
    enemy = side ^ 1
    if (state["castle"][side]["k"] and b.get(cell("o", hr, 7)) and b[cell("o", hr, 7)]["t"] == "R"
            and cell("o", hr, 5) not in b and cell("o", hr, 6) not in b
            and not attacked_by(state, cell("o", hr, 5), enemy) and not attacked_by(state, cell("o", hr, 6), enemy)):
        out.append({"from": k_from, "to": cell("o", hr, 6), "cap": False, "castle": "k"})
    if (state["castle"][side]["q"] and b.get(cell("o", hr, 0)) and b[cell("o", hr, 0)]["t"] == "R"
            and cell("o", hr, 1) not in b and cell("o", hr, 2) not in b and cell("o", hr, 3) not in b
            and not attacked_by(state, cell("o", hr, 3), enemy) and not attacked_by(state, cell("o", hr, 2), enemy)):
        out.append({"from": k_from, "to": cell("o", hr, 2), "cap": False, "castle": "q"})


def legal_moves(state):
    side = state["turn"]
    board = state["board"]
    res = []
    for k in list(board.keys()):
        if board[k]["s"] != side:
            continue
        buf = []
        piece_moves(state, k, False, buf)
        pt = board[k]["t"]
        for mv0 in buf:
            to = mv0["to"]
            if pt == "P" and not is_gate(to):
                rr = int(to.split(":")[1])
                if (side == 0 and rr == 0) or (side == 1 and rr == 7):
                    for promo in ("Q", "R", "B", "N"):
                        pm = {"from": k, "to": to, "cap": mv0["cap"], "piece": pt, "promo": promo}
                        if not in_check(apply_move(state, pm), side):
                            res.append(pm)
                    continue
            mv = {"from": k, "to": to, "cap": mv0["cap"], "piece": pt}
            if not in_check(apply_move(state, mv), side):
                res.append(mv)
    cm = []
    castling_moves(state, side, cm)
    for m in cm:
        if not in_check(apply_move(state, m), side):
            res.append(m)
    return res


def insufficient(b):
    pieces = [b[k]["t"] for k in b if b[k]["t"] != "K"]
    if len(pieces) == 0:
        return True
    if len(pieces) == 1 and pieces[0] in ("N", "B"):
        return True
    return False


def status(state):
    moves = legal_moves(state)
    chk = in_check(state, state["turn"])
    if len(moves) == 0:
        if chk:
            return {"over": True, "result": "black" if state["turn"] == 0 else "white",
                    "reason": "checkmate", "check": True}
        return {"over": True, "result": "draw", "reason": "stalemate", "check": False}
    if state["half"] >= 100:
        return {"over": True, "result": "draw", "reason": "50-move", "check": chk}
    if insufficient(state["board"]):
        return {"over": True, "result": "draw", "reason": "insufficient", "check": chk}
    return {"over": False, "result": None, "reason": None, "check": chk}


# ---- evaluation & AI ------------------------------------------------------
def _central(x, y):
    return 1 - (abs(x - 7) + abs(y - 7)) / 14.0


def evaluate(state):
    b = state["board"]
    sc = 0.0
    for k in b:
        p = b[k]
        x, y = xy_of(k)
        sgn = 1 if p["s"] == 0 else -1
        v = VAL[p["t"]]
        bonus = 0.0
        ce = _central(x, y)
        t = p["t"]
        if t in ("N", "B"):
            bonus += 14 * ce
        if t == "P":
            adv = (14 - y) if p["s"] == 0 else y
            bonus += adv * 1.2 + 6 * ce
            if is_gate(k):
                bonus += 10
        if is_gate(k) and t in ("N", "B"):
            bonus += 12 * ce
        if t == "W":
            bonus += 16 * ce + 4
        if t == "K" and is_gate(k):
            bonus -= 18
        sc += sgn * (v + bonus)
    return sc


def _order(state, moves):
    b = state["board"]
    for m in moves:
        sc = 0.0
        if m.get("cap"):
            victim = b.get(m["to"])
            sc = 1000 + (VAL[victim["t"]] if victim else 0) - VAL[m["piece"]] / 10.0
        if m.get("promo"):
            sc += 800
        m["_o"] = sc
    moves.sort(key=lambda m: m["_o"], reverse=True)
    return moves


def _quiesce(state, alpha, beta, side):
    stand = evaluate(state) * (1 if side == 0 else -1)
    if stand >= beta:
        return beta
    if stand > alpha:
        alpha = stand
    moves = legal_moves(state)
    _order(state, moves)
    for m in moves:
        if not m.get("cap") and not m.get("promo"):
            continue
        sc = -_quiesce(apply_move(state, m), -beta, -alpha, side ^ 1)
        if sc >= beta:
            return beta
        if sc > alpha:
            alpha = sc
    return alpha


def _negamax(state, depth, alpha, beta, side, deadline):
    if time.time() > deadline:
        return {"score": evaluate(state) * (1 if side == 0 else -1), "move": None}
    moves = legal_moves(state)
    if len(moves) == 0:
        if in_check(state, side):
            return {"score": -100000 - depth, "move": None}
        return {"score": 0, "move": None}
    if depth == 0:
        return {"score": _quiesce(state, alpha, beta, side), "move": None}
    _order(state, moves)
    best = float("-inf")
    best_move = moves[0]
    for m in moves:
        r = _negamax(apply_move(state, m), depth - 1, -beta, -alpha, side ^ 1, deadline)
        sc = -r["score"]
        if sc > best:
            best = sc; best_move = m
        if best > alpha:
            alpha = best
        if alpha >= beta:
            break
    return {"score": best, "move": best_move}


def ai_move(state, difficulty="normal", time_ms=None):
    max_depth = 2 if difficulty == "easy" else 5 if difficulty == "hard" else 3
    budget = (time_ms if time_ms is not None
              else (2500 if difficulty == "hard" else 1200 if difficulty == "normal" else 400)) / 1000.0
    deadline = time.time() + budget
    side = state["turn"]
    top = legal_moves(state)
    if len(top) == 0:
        return None
    if difficulty == "easy":
        r0 = _negamax(state, max_depth, float("-inf"), float("inf"), side, deadline)
        return r0["move"] or top[0]
    best_move = None
    for d in range(1, max_depth + 1):
        r = _negamax(state, d, float("-inf"), float("inf"), side, deadline)
        if time.time() > deadline:
            break
        if r["move"]:
            best_move = r["move"]
    return best_move or top[0]


# clean a move dict for storage/transport (drop internal fields)
def clean_move(m):
    out = {"from": m["from"], "to": m["to"]}
    if m.get("promo"):
        out["promo"] = m["promo"]
    if m.get("castle"):
        out["castle"] = m["castle"]
    return out


# ---- server Board wrapper (matches the action-engine interface in service.py) --------------
class Board:
    """Mutable wrapper around the functional state so the server can clone / validate / apply /
    serialize like the other action-engines. Actions are {"from","to","promo"?} dicts."""
    def __init__(self, warden=False):
        self.state = initial(warden)

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

    def _match(self, action):
        if not isinstance(action, dict):
            return None
        fr, to, promo = action.get("from"), action.get("to"), action.get("promo") or None
        for m in legal_moves(self.state):
            if m["from"] == fr and m["to"] == to and (m.get("promo") or None) == promo:
                return m
        return None

    def is_legal(self, action, owner=None):
        if owner is not None and owner != self.state["turn"]:
            return False
        return self._match(action) is not None

    def apply(self, action):
        m = self._match(action)
        if m is None:
            raise ValueError("illegal action")
        self.state = apply_move(self.state, m)

    @property
    def winner(self):
        st = status(self.state)
        if not st["over"]:
            return None
        r = st["result"]
        return "draw" if r == "draw" else (0 if r == "white" else 1)


def serialize(board, draw_agreed=False):
    s = board.state
    st = status(s)
    winner = None
    if draw_agreed:
        winner = "draw"
    elif st["over"]:
        winner = "draw" if st["result"] == "draw" else (0 if st["result"] == "white" else 1)
    return {
        "board": {k: (s["board"][k]["t"] + str(s["board"][k]["s"])) for k in s["board"]},
        "turn": s["turn"], "castle": s["castle"], "half": s["half"], "full": s["full"],
        "check": st["check"], "over": bool(st["over"] or draw_agreed),
        "winner": winner, "reason": st["reason"],
        "legal": [] if (st["over"] or draw_agreed) else [clean_move(m) for m in legal_moves(s)],
    }


def explain_action(board, action, owner):
    fr, to = action.get("from"), action.get("to")
    txt = (label(fr) + "–" + label(to)) if fr and to else ""
    if action.get("promo"):
        txt += "=" + action["promo"]
    if action.get("castle"):
        txt = "O-O" if action["castle"] == "k" else "O-O-O"
    return {"text": txt}
