"""HYPERSCALE (spatial + market) engine — authoritative Python port of
docs/hyperscale_engine.js, for server-side PvP / AI games. Kept faithful to the
JS so the two agree move-for-move (see sim_hyperscale_parity.py).

Power is scarce and board-fixed (a central corridor both players fight over, plus
tiny home stations). A datacenter earns only when a ROAD links it to your HQ and
it's adjacent/power-line connected to a station with spare capacity. Servers are
bought one at a time from a shared, finite, dynamically-priced market. You may
sabotage an adjacent enemy road/power-line once per day. Most AI tokens after 24
days wins."""
import math

HS_W, HS_H = 9, 9
HS_HQ = ["0,0", "8,8"]
HS_STATIONS = {"4,3": 5, "4,4": 6, "4,5": 5, "2,2": 2, "6,6": 2}
HS_STATION_KEYS = list(HS_STATIONS.keys())
HS_TECH = ["GPU", "HBM", "CPU"]
HS_SERVER = {"GPU": 2, "HBM": 1, "CPU": 1}
HS_BASE_PRICE = {"GPU": 3, "HBM": 3, "CPU": 1}
HS_RESERVE0 = {"GPU": 44, "HBM": 24, "CPU": 60}
HS_PRICE_K = 2.0
HS_COST = {"road": 1, "powerline": 2, "dc": 4}
HS_SABOTAGE_COST = 3
HS_MAX_SERVERS = 4
HS_BUY_LOT = 4
HS_POWER_COST, HS_MAN_RATE, HS_REV_RATE = 1.0, 0.15, 4.0
HS_INCOME_BASE, HS_START_CAPITAL, HS_ACTIONS, HS_MAX_DAYS = 8, 24, 3, 24
HS_P2_BONUS = 0
HS_POWER_KINDS = {"powerline", "dc"}
HS_ROAD_KINDS = {"road", "dc"}


def _iround(x):
    """floor(x + 0.5) — matches JS Math.round for the non-negative values here."""
    return int(math.floor(x + 0.5))


def hs_key(x, y):
    return "%d,%d" % (x, y)


def hs_neigh(x, y):
    d = ([[1, 0], [-1, 0], [0, 1], [-1, 1], [0, -1], [-1, -1]] if y % 2 == 0
         else [[1, 0], [-1, 0], [1, 1], [0, 1], [1, -1], [0, -1]])
    return [[x + dx, y + dy] for dx, dy in d]


def hs_in(x, y):
    return 0 <= x < HS_W and 0 <= y < HS_H


def hs_adj(k):
    x, y = map(int, k.split(","))
    return [hs_key(nx, ny) for nx, ny in hs_neigh(x, y) if hs_in(nx, ny)]


def hs_dist(a, b):
    def ax(x, y):
        return [x - ((y - (y & 1)) >> 1), y]
    x1, y1 = map(int, a.split(","))
    x2, y2 = map(int, b.split(","))
    aq, ar = ax(x1, y1)
    bq, br = ax(x2, y2)
    dq, dr = aq - bq, ar - br
    return (abs(dq) + abs(dr) + abs(dq + dr)) >> 1


class Board:
    def __init__(self):
        self.pieces = {}
        self.dc_servers = {}
        self.reserve = dict(HS_RESERVE0)
        self.stock = [{"GPU": 0, "HBM": 0, "CPU": 0}, {"GPU": 0, "HBM": 0, "CPU": 0}]
        self.capital = [HS_START_CAPITAL, HS_START_CAPITAL + HS_P2_BONUS]
        self.tokens = [0, 0]
        self.produced_last = [0, 0]
        self.earned = [0, 0]
        self.spent = [0, 0]
        self.dc_produced = {}
        self.dayLog = []
        self.to_move = 0
        self.actions_left = HS_ACTIONS
        self.day = 1
        self.winner = None
        self.sab_used = False
        self._begin_day(0)

    def clone(self):
        b = Board.__new__(Board)
        b.pieces = {k: dict(v) for k, v in self.pieces.items()}
        b.dc_servers = dict(self.dc_servers)
        b.reserve = dict(self.reserve)
        b.stock = [dict(self.stock[0]), dict(self.stock[1])]
        b.capital = list(self.capital)
        b.tokens = list(self.tokens)
        b.produced_last = list(self.produced_last)
        b.earned = list(self.earned)
        b.spent = list(self.spent)
        b.dc_produced = dict(self.dc_produced)
        b.dayLog = [dict(d) for d in self.dayLog]
        b.to_move = self.to_move
        b.actions_left = self.actions_left
        b.day = self.day
        b.winner = self.winner
        b.sab_used = self.sab_used
        return b

    def price(self, r):
        depl = 1 - self.reserve[r] / HS_RESERVE0[r]
        return _iround(HS_BASE_PRICE[r] * (1 + HS_PRICE_K * depl))

    def serverCost(self, owner=None):
        if owner is None:
            owner = self.to_move
        return sum(max(0, HS_SERVER[r] - self.stock[owner][r]) * self.price(r) for r in HS_TECH)

    def canBuyServer(self, owner=None):
        if owner is None:
            owner = self.to_move
        return all(self.stock[owner][r] + self.reserve[r] >= HS_SERVER[r] for r in HS_TECH)

    def servers(self, h):
        return self.dc_servers.get(h, 0)

    def _power_components(self, owner):
        nodes = set(h for h, p in self.pieces.items()
                    if p["owner"] == owner and p["kind"] in HS_POWER_KINDS)
        seen, comps = set(), []
        for s in nodes:
            if s in seen:
                continue
            comp, st = set(), [s]
            seen.add(s)
            while st:
                h = st.pop()
                comp.add(h)
                for n in hs_adj(h):
                    if n in nodes and n not in seen:
                        seen.add(n)
                        st.append(n)
            comps.append(comp)
        return comps

    def _cluster_stations(self, comp):
        st = set()
        for h in comp:
            for n in hs_adj(h):
                if n in HS_STATIONS:
                    st.add(n)
        return list(st)

    def _has_station(self, comp):
        return len(self._cluster_stations(comp)) > 0

    def _road_dist(self, owner):
        nodes = set([HS_HQ[owner]])
        for h, p in self.pieces.items():
            if p["owner"] == owner and p["kind"] in HS_ROAD_KINDS:
                nodes.add(h)
        dist = {HS_HQ[owner]: 0}
        q = [HS_HQ[owner]]
        i = 0
        while i < len(q):
            h = q[i]; i += 1
            for n in hs_adj(h):
                if n in nodes and n not in dist:
                    dist[n] = dist[h] + 1
                    q.append(n)
        return dist

    def _reachable_stations(self, owner, h):
        for c in self._power_components(owner):
            if h in c:
                return self._cluster_stations(c)
        return []

    def _allocate(self):
        remaining = {s: HS_STATIONS[s] for s in HS_STATION_KEYS}
        cands = []
        for owner in (0, 1):
            rr = self._road_dist(owner)
            for h, p in self.pieces.items():
                if p["owner"] != owner or p["kind"] != "dc" or self.servers(h) <= 0 or h not in rr:
                    continue
                reach = self._reachable_stations(owner, h)
                if reach:
                    cands.append((self.servers(h), owner, h, reach))
        cands.sort(key=lambda c: (-c[0], c[2]))
        powered = {0: {}, 1: {}}
        sources = {0: {}, 1: {}}
        for srv, owner, h, reach in cands:
            need, got, src = srv, 0, {}
            for s in sorted(reach, key=lambda s: (-remaining[s], s)):
                if need <= 0:
                    break
                take = min(need, remaining[s])
                if take > 0:
                    remaining[s] -= take
                    need -= take
                    got += take
                    src[s] = take
            if got > 0:
                powered[owner][h] = got
                sources[owner][h] = src
        return powered, remaining, sources

    def _empty(self, h):
        x, y = map(int, h.split(","))
        return hs_in(x, y) and h not in self.pieces and h not in HS_HQ and h not in HS_STATIONS

    def dc_status(self, h):
        o = self.pieces[h]["owner"]
        srv = self.servers(h)
        rd = self._road_dist(o)
        dist = rd.get(h)
        reach = self._reachable_stations(o, h)
        if srv == 0:
            return {"state": "no_servers", "servers": 0, "output": 0,
                    "dist": dist if dist is not None else hs_dist(h, HS_HQ[o]), "reach": reach, "sources": {}}
        if dist is None:
            return {"state": "no_road", "servers": srv, "output": 0,
                    "dist": hs_dist(h, HS_HQ[o]), "reach": reach, "sources": {}}
        powered, _, sources = self._allocate()
        pw = powered[o].get(h, 0)
        if pw > 0:
            return {"state": "producing", "servers": srv, "output": pw, "powerCapped": pw < srv,
                    "dist": dist, "reach": reach, "sources": sources[o].get(h, {}),
                    "opex": _iround((pw * HS_POWER_COST + pw * dist * HS_MAN_RATE) * 10) / 10}
        return {"state": "unpowered" if reach else "no_power_line", "servers": srv, "output": 0,
                "dist": dist, "reach": reach, "sources": {}}

    def _begin_day(self, owner):
        rd = self._road_dist(owner)
        powered, _, _ = self._allocate()
        pw = powered[owner]
        out, opex, perDC = 0, 0.0, {}
        for h, p in pw.items():
            out += p
            opex += p * HS_POWER_COST + p * rd.get(h, 0) * HS_MAN_RATE
            self.dc_produced[h] = self.dc_produced.get(h, 0) + p
            perDC[h] = p
        self.tokens[owner] += out
        self.produced_last[owner] = out
        self.earned[owner] += HS_INCOME_BASE + HS_REV_RATE * out
        self.spent[owner] += opex
        self.capital[owner] += HS_INCOME_BASE + HS_REV_RATE * out - opex
        self.dayLog.append({"day": self.day, "owner": owner, "out": out, "perDC": perDC,
                            "income": HS_INCOME_BASE, "revenue": HS_REV_RATE * out,
                            "opex": _iround(opex * 10) / 10})
        self.actions_left = HS_ACTIONS
        self.sab_used = False

    def is_legal(self, action, owner=None):
        if owner is None:
            owner = self.to_move
        a = action.get("a")
        if self.winner is not None or self.actions_left <= 0:
            return a == "pass"
        if a == "pass":
            return True
        if a == "build":
            piece = action.get("piece")
            return (piece in HS_COST and self.capital[owner] >= HS_COST[piece]
                    and self._empty(hs_key(action["x"], action["y"])))
        if a == "install":
            k = hs_key(action["x"], action["y"])
            p = self.pieces.get(k)
            return bool(p and p["owner"] == owner and p["kind"] == "dc" and self.servers(k) < HS_MAX_SERVERS
                        and self.canBuyServer(owner) and self.capital[owner] >= self.serverCost(owner))
        if a == "buy":
            r = action.get("res")
            return r in HS_TECH and self.reserve[r] > 0 and self.capital[owner] >= self.price(r)
        if a == "sabotage":
            k = hs_key(action["x"], action["y"])
            p = self.pieces.get(k)
            return bool(not self.sab_used and p and p["owner"] != owner and p["kind"] in ("road", "powerline")
                        and any(self.pieces.get(n) and self.pieces[n]["owner"] == owner for n in hs_adj(k))
                        and self.capital[owner] >= HS_SABOTAGE_COST)
        return False

    def apply(self, action):
        owner = self.to_move
        a = action.get("a")
        if a == "pass":
            self.actions_left = 0
        elif a == "build":
            k = hs_key(action["x"], action["y"])
            self.capital[owner] -= HS_COST[action["piece"]]
            self.spent[owner] += HS_COST[action["piece"]]
            self.pieces[k] = {"owner": owner, "kind": action["piece"]}
            if action["piece"] == "dc":
                self.dc_servers[k] = 0
            self.actions_left -= 1
        elif a == "install":
            k = hs_key(action["x"], action["y"])
            for r in HS_TECH:
                need = HS_SERVER[r]
                from_stock = min(need, self.stock[owner][r])
                self.stock[owner][r] -= from_stock
                need -= from_stock
                self.capital[owner] -= need * self.price(r)
                self.spent[owner] += need * self.price(r)
                self.reserve[r] -= need
            self.dc_servers[k] += 1
            self.actions_left -= 1
        elif a == "buy":
            r = action["res"]
            n = 0
            while n < HS_BUY_LOT and self.reserve[r] > 0 and self.capital[owner] >= self.price(r):
                self.capital[owner] -= self.price(r)
                self.spent[owner] += self.price(r)
                self.reserve[r] -= 1
                self.stock[owner][r] += 1
                n += 1
            self.actions_left -= 1
        elif a == "sabotage":
            self.pieces.pop(hs_key(action["x"], action["y"]), None)
            self.capital[owner] -= HS_SABOTAGE_COST
            self.spent[owner] += HS_SABOTAGE_COST
            self.sab_used = True
            self.actions_left -= 1
        if self.actions_left <= 0:
            self._end_day()

    def _end_day(self):
        self.to_move ^= 1
        self.day += 1
        if self.day > HS_MAX_DAYS:
            a, b = self.tokens
            self.winner = 0 if a > b else (1 if b > a else "draw")
        else:
            self._begin_day(self.to_move)


# ---------------------------------------------------------------- functional AI
def hs_ai_move(board, owner):
    cap = board.capital[owner]
    HQ = HS_HQ[owner]
    oppHQ = HS_HQ[1 - owner]
    rd = board._road_dist(owner)
    rr = set(rd.keys())
    empties = [hs_key(x, y) for y in range(HS_H) for x in range(HS_W) if board._empty(hs_key(x, y))]
    if not empties:
        return {"a": "pass"}

    def P(h):
        x, y = map(int, h.split(","))
        return {"x": x, "y": y}

    powered, remaining, _ = board._allocate()
    open_st = [s for s in HS_STATION_KEYS if remaining[s] > 0]

    def road_adj(h):
        return any(n in rr for n in hs_adj(h))

    def station_adj_open(h):
        return any(n in HS_STATIONS and remaining[n] > 0 for n in hs_adj(h))

    def rdor9(h):
        v = rd.get(h)
        return v if v else 9

    dcs = [h for h, p in board.pieces.items() if p["owner"] == owner and p["kind"] == "dc"]
    comps = board._power_components(owner)
    connected_pow = set()
    for comp in comps:
        if board._has_station(comp):
            connected_pow |= comp

    def power_room(h):
        return any(remaining[s] > 0 for s in board._reachable_stations(owner, h))

    growable = sorted([h for h in dcs if h in rr and h in connected_pow
                       and board.servers(h) < HS_MAX_SERVERS and power_room(h)],
                      key=rdor9)

    sc = board.serverCost(owner)
    # 1) fill a productive DC
    if board.canBuyServer(owner) and cap >= sc and growable:
        return dict(a="install", **P(growable[0]))

    # 1c) reconnect a DC stranded by a sabotage
    stranded_road = [h for h in dcs if board.servers(h) > 0 and h not in rd]
    if stranded_road and cap >= HS_COST["road"]:
        def road_bridge(e):
            ns = hs_adj(e)
            return (any(n in rr for n in ns)
                    and any(board.pieces.get(n) and board.pieces[n]["owner"] == owner
                            and board.pieces[n]["kind"] in HS_ROAD_KINDS and n not in rr for n in ns))
        br = sorted([e for e in empties if road_bridge(e)], key=lambda e: hs_dist(e, HQ))
        if br:
            return dict(a="build", piece="road", **P(br[0]))
    stranded_pow = [h for h in dcs if board.servers(h) > 0 and h in rd and not board._reachable_stations(owner, h)]
    if stranded_pow and cap >= HS_COST["powerline"]:
        for h in stranded_pow:
            cluster = next((c for c in comps if h in c), None)
            if not cluster:
                continue
            br = [e for e in empties if any(n in cluster for n in hs_adj(e)) and any(n in HS_STATIONS for n in hs_adj(e))]
            if br:
                return dict(a="build", piece="powerline", **P(br[0]))

    # 1b) defensive stockpiling
    if growable:
        for r in HS_TECH:
            if (board.reserve[r] > 0 and board.reserve[r] <= HS_BUY_LOT * 2
                    and board.stock[owner][r] < HS_SERVER[r] * 2 and cap >= board.price(r) * 2):
                return {"a": "buy", "res": r}

    # 1d) sabotage an adjacent enemy connector that denies the most enemy power
    if not board.sab_used and cap >= HS_SABOTAGE_COST:
        opp = 1 - owner

        def enemy_pow():
            return sum(board._allocate()[0][opp].values())
        base = enemy_pow()
        best, best_val = None, 0
        for k in list(board.pieces.keys()):
            p = board.pieces[k]
            if p["owner"] != opp or p["kind"] not in ("road", "powerline"):
                continue
            if not any(board.pieces.get(n) and board.pieces[n]["owner"] == owner for n in hs_adj(k)):
                continue
            saved = board.pieces.pop(k)
            val = base - enemy_pow()
            board.pieces[k] = saved
            if val > best_val:
                best_val, best = val, k
        if best and best_val >= 3:
            return dict(a="sabotage", **P(best))

    def spot_val(h):
        v = -99.0
        for n in hs_adj(h):
            if n in HS_STATIONS and remaining[n] > 0:
                v = max(v, remaining[n] - hs_dist(h, HQ) * 0.3)
        return v

    # 2) claim a new DC next to an open station
    if not growable and cap >= HS_COST["dc"]:
        spots = sorted([h for h in empties if road_adj(h) and station_adj_open(h)],
                       key=lambda h: (-spot_val(h), hs_dist(h, HQ)))
        if spots:
            return dict(a="build", piece="dc", **P(spots[0]))

    # 2b) extend a power line from a stuck DC toward the best open on-side station
    if cap >= HS_COST["powerline"]:
        stuck = [h for h in dcs if h in rr and
                 (powered[owner].get(h, 0) < board.servers(h) or (board.servers(h) < HS_MAX_SERVERS and not power_room(h)))]
        for h in stuck:
            cluster = next((c for c in comps if h in c), None)
            if not cluster:
                continue
            reached = set(board._reachable_stations(owner, h))
            far = [s for s in HS_STATION_KEYS if remaining[s] > 0 and s not in reached
                   and hs_dist(s, HQ) <= hs_dist(s, oppHQ)]
            if not far:
                continue
            tgt = sorted(far, key=lambda s: -remaining[s])[0]
            net_min = min(hs_dist(x, tgt) for x in cluster)
            steps = sorted([e for e in empties if any(n in cluster for n in hs_adj(e)) and hs_dist(e, tgt) < net_min],
                           key=lambda e: hs_dist(e, tgt))
            if steps:
                return dict(a="build", piece="powerline", **P(steps[0]))

    # 3) extend a road toward an open, on-side station we can't yet reach
    if cap >= HS_COST["road"]:
        def reaches(s):
            return any((board.pieces.get(n) and board.pieces[n]["owner"] == owner)
                       or (board._empty(n) and road_adj(n)) for n in hs_adj(s))
        wanted = [s for s in open_st if not reaches(s) and hs_dist(s, HQ) <= hs_dist(s, oppHQ)]
        if wanted:
            target = sorted(wanted, key=lambda s: -remaining[s])[0]
            cands = sorted([h for h in empties if road_adj(h)],
                           key=lambda h: (hs_dist(h, target), hs_dist(h, HQ)))
            if cands:
                return dict(a="build", piece="road", **P(cands[0]))
    return {"a": "pass"}


DIFF = {"easy": 0, "normal": 1, "hard": 2}


def ai_move(board, difficulty="normal"):
    """Single-pass heuristic; difficulty is accepted for interface parity."""
    return hs_ai_move(board, board.to_move)


def explain_action(board, action, owner):
    """Short human-readable rationale for an AI action (matches the JS version)."""
    a = action.get("a")
    x, y, res, piece = action.get("x"), action.get("y"), action.get("res"), action.get("piece")
    if a == "install":
        return {"aim": "score", "text": "Adding a server at (%d,%d) — more powered servers means more tokens." % (x, y)}
    if a == "buy":
        return {"aim": "consolidate", "text": "Stockpiling %s from the market before prices climb." % res}
    if a == "sabotage":
        return {"aim": "disrupt", "text": "Sabotaging your piece at (%d,%d) to cut power to your datacenters." % (x, y)}
    if a == "pass":
        return {"aim": "wait", "text": "Nothing worth doing — ending the day."}
    if a == "build":
        if piece == "dc":
            return {"aim": "expand", "text": "Claiming a datacenter at (%d,%d) next to an open station." % (x, y)}
        if piece == "powerline":
            return {"aim": "expand", "text": "Running a power line at (%d,%d) to reach more power." % (x, y)}
        return {"aim": "expand", "text": "Extending a road to (%d,%d) toward power." % (x, y)}
    return {"aim": "wait", "text": "…"}


def serialize(board):
    """Normalized board state (for the server to persist / send to the client)."""
    return {
        "day": board.day, "max_days": HS_MAX_DAYS, "to_move": board.to_move,
        "actions_left": board.actions_left, "winner": board.winner, "sab_used": board.sab_used,
        "tokens": list(board.tokens), "capital": [round(c * 10) / 10 for c in board.capital],
        "reserve": dict(board.reserve), "stock": [dict(board.stock[0]), dict(board.stock[1])],
        "pieces": {k: dict(v) for k, v in board.pieces.items()},
        "dc_servers": dict(board.dc_servers),
    }
