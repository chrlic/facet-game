"""HYPERSCALE (spatial + market) — prototype engine. See HYPERSCALE_SPATIAL.md.

Each turn is a DAY: you take a few build/market actions, and your powered
datacenters produce. To earn, a datacenter must be built on a claimed hex,
power-line connected (through the owner's claimed hexes) to a station that has
spare capacity, and hold technology in balanced proportions. Output = balanced
compute; every day you pay power + manning (manning grows with distance from
your city). The two mid-board stations are SHARED — both players draw from them
until they're full, then you build your own. Most tokens after MAX_DAYS wins.
"""
W = H = 9
CITY = ((0, 0), (8, 8))                 # each player's HR source (start corner)
NEUTRAL_STATIONS = ((4, 3), (4, 5))     # shared power, drawn by both players
STATION_CAP = 8

TECH = ("GPU", "HBM", "CPU")
RATIO = {"GPU": 2, "HBM": 1, "CPU": 1}  # per unit of balanced compute
BASE_PRICE = {"GPU": 3, "HBM": 3, "CPU": 1}
RESERVE0 = {"GPU": 90, "HBM": 70, "CPU": 200}
PRICE_K = 1.5

LINE, DC, STATION = "line", "dc", "station"
COST = {LINE: 1, DC: 4, STATION: 8}
POWER_COST = 1.0            # capital/day per unit of running compute
MAN_RATE = 0.25            # capital/day per compute-unit per hex from city
REV_RATE = 3.0            # capital/day per unit of output
INCOME_BASE = 4
START_CAPITAL = 12
ACTIONS = 3
MAX_DAYS = 24


def neighbors(x, y):
    d = ((1, 0), (-1, 0), (0, 1), (-1, 1), (0, -1), (-1, -1)) if y % 2 == 0 \
        else ((1, 0), (-1, 0), (1, 1), (0, 1), (1, -1), (0, -1))
    return [(x + dx, y + dy) for dx, dy in d]


def in_board(x, y):
    return 0 <= x < W and 0 <= y < H


def _ax(x, y):
    return x - (y - (y & 1)) // 2, y


def hex_dist(a, b):
    aq, ar = _ax(*a); bq, br = _ax(*b)
    dq, dr = aq - bq, ar - br
    return (abs(dq) + abs(dr) + abs(dq + dr)) // 2


class Board:
    def __init__(self):
        self.pieces = {}                  # hex -> (owner, kind) for line/dc/station
        self.dc_tech = {}                 # dc hex -> {GPU,HBM,CPU}
        self.reserve = dict(RESERVE0)
        self.capital = [START_CAPITAL, START_CAPITAL]
        self.tokens = [0.0, 0.0]
        self.produced_last = [0, 0]
        self.to_move = 0
        self.actions_left = ACTIONS
        self.day = 1
        self.winner = None
        self._begin_day(0)

    # ---- market ----
    def price(self, r):
        depl = 1 - self.reserve[r] / RESERVE0[r]
        return round(BASE_PRICE[r] * (1 + PRICE_K * depl))

    # ---- connectivity: owner's pieces + any neutral station adjacent to them ----
    def _nodes(self, owner):
        own = {h for h, (o, k) in self.pieces.items() if o == owner}
        neu = {s for s in NEUTRAL_STATIONS if any(n in own for n in neighbors(*s))}
        return own | neu

    def _is_station(self, h, owner):
        return h in NEUTRAL_STATIONS or self.pieces.get(h) == (owner, STATION)

    def _components(self, owner):
        nodes = self._nodes(owner)
        seen, comps = set(), []
        for start in nodes:
            if start in seen:
                continue
            comp, stack = set(), [start]
            seen.add(start)
            while stack:
                h = stack.pop(); comp.add(h)
                for n in neighbors(*h):
                    if n in nodes and n not in seen:
                        seen.add(n); stack.append(n)
            comps.append(comp)
        return comps

    def dc_output(self, h):
        t = self.dc_tech.get(h)
        return min(t[r] // RATIO[r] for r in TECH) if t else 0

    def _allocate(self):
        """Global shared-capacity power allocation -> {owner: set of earning DCs}.
        Highest-output datacenters get powered first from the stations they can
        reach; shared stations are one pool that both players draw from."""
        remaining = {s: STATION_CAP for s in NEUTRAL_STATIONS}
        for h, (o, k) in self.pieces.items():
            if k == STATION:
                remaining[h] = STATION_CAP
        cands = []
        for owner in (0, 1):
            for comp in self._components(owner):
                stations = [h for h in comp if self._is_station(h, owner)]
                if not stations:
                    continue
                for h in comp:
                    p = self.pieces.get(h)
                    if p and p[0] == owner and p[1] == DC and self.dc_output(h) > 0:
                        cands.append((self.dc_output(h), owner, h, stations))
        cands.sort(key=lambda c: (-c[0], c[1], c[2]))
        prod = {0: set(), 1: set()}
        for out, owner, h, stations in cands:
            for s in stations:
                if remaining.get(s, 0) >= out:
                    remaining[s] -= out; prod[owner].add(h); break
        return prod

    def producing(self, owner):
        return self._allocate()[owner]

    def manning(self, h, owner):
        return self.dc_output(h) * hex_dist(h, CITY[owner]) * MAN_RATE

    def dc_status(self, h):
        o = self.pieces[h][0]
        out = self.dc_output(h)
        if out == 0:
            return {"state": "no_tech", "output": 0}
        if h in self.producing(o):
            return {"state": "producing", "output": out,
                    "opex": round(out * POWER_COST + self.manning(h, o), 1),
                    "dist": hex_dist(h, CITY[o])}
        comp = next((c for c in self._components(o) if h in c), set())
        has_station = any(self._is_station(x, o) for x in comp)
        return {"state": "unpowered" if has_station else "no_power_line",
                "output": out, "dist": hex_dist(h, CITY[o])}

    # ---- day flow ----
    def _begin_day(self, owner):
        run = self.producing(owner)
        out = sum(self.dc_output(h) for h in run)
        opex = sum(self.dc_output(h) * POWER_COST + self.manning(h, owner) for h in run)
        self.tokens[owner] += out
        self.produced_last[owner] = out
        self.capital[owner] += INCOME_BASE + REV_RATE * out - opex
        self.actions_left = ACTIONS

    def _empty(self, h):
        return (in_board(*h) and h not in self.pieces
                and h not in CITY and h not in NEUTRAL_STATIONS)

    def is_legal(self, action, owner=None):
        owner = self.to_move if owner is None else owner
        if self.winner is not None or self.actions_left <= 0:
            return action.get("a") == "pass"
        a = action.get("a")
        if a == "pass":
            return True
        if a == "build":
            kind = action.get("piece"); h = (action.get("x"), action.get("y"))
            return kind in COST and self.capital[owner] >= COST[kind] and self._empty(h)
        if a == "install":
            h = (action.get("x"), action.get("y")); r = action.get("res")
            return (self.pieces.get(h) == (owner, DC) and r in TECH
                    and self.reserve[r] > 0 and self.capital[owner] >= self.price(r))
        return False

    def legal_actions(self, owner=None):
        owner = self.to_move if owner is None else owner
        if self.winner is not None:
            return []
        acts = [{"a": "pass"}]
        cap = self.capital[owner]
        empties = [(x, y) for y in range(H) for x in range(W) if self._empty((x, y))]
        for kind in (LINE, DC, STATION):
            if COST[kind] <= cap:
                for (x, y) in empties:
                    acts.append({"a": "build", "piece": kind, "x": x, "y": y})
        for h, (o, k) in self.pieces.items():
            if o == owner and k == DC:
                for r in TECH:
                    if self.reserve[r] > 0 and cap >= self.price(r):
                        acts.append({"a": "install", "x": h[0], "y": h[1], "res": r})
        return acts

    def apply(self, action):
        owner = self.to_move
        a = action.get("a")
        if a == "pass":
            self.actions_left = 0
        elif a == "build":
            kind = action["piece"]; h = (action["x"], action["y"])
            self.capital[owner] -= COST[kind]
            self.pieces[h] = (owner, kind)
            if kind == DC:
                self.dc_tech[h] = {r: 0 for r in TECH}
            self.actions_left -= 1
        elif a == "install":
            h = (action["x"], action["y"]); r = action["res"]
            self.capital[owner] -= self.price(r)
            self.reserve[r] -= 1
            self.dc_tech[h][r] += 1
            self.actions_left -= 1
        if self.actions_left <= 0:
            self._end_day()

    def _end_day(self):
        self.to_move ^= 1
        self.day += 1
        if self.day > MAX_DAYS:
            a, b = self.tokens
            self.winner = 0 if a > b else (1 if b > a else "draw")
        else:
            self._begin_day(self.to_move)


# ---------------------------------------------------------------- simple AI
def _reachable_from(board, owner, h, extra=None):
    """Is h in a component (with the added node `extra`) that holds a station?"""
    nodes = board._nodes(owner) | ({extra} if extra else set()) | {h}
    seen, stack = {h}, [h]
    while stack:
        c = stack.pop()
        if board._is_station(c, owner):
            return True
        for n in neighbors(*c):
            if n in nodes and n not in seen:
                seen.add(n); stack.append(n)
    return False


def ai_move(board, owner):
    cap = board.capital[owner]
    comps = board._components(owner)
    comp_of = lambda h: next((c for c in comps if h in c), None)
    has_stn = lambda c: bool(c) and any(board._is_station(h, owner) for h in c)
    my_dcs = [h for h, (o, k) in board.pieces.items() if o == owner and k == DC]
    nodes = board._nodes(owner)
    adj = lambda h: any(n in nodes for n in neighbors(*h))
    empties = [(x, y) for y in range(H) for x in range(W) if board._empty((x, y))]
    if not empties:
        return {"a": "pass"}

    # 1) balance a connected datacenter's tech (grow its output)
    conn = [h for h in my_dcs if has_stn(comp_of(h))]
    conn.sort(key=lambda h: hex_dist(h, CITY[owner]))
    for h in conn:
        t = board.dc_tech[h]
        for r in sorted(TECH, key=lambda r: t[r] / RATIO[r]):
            if board.reserve[r] > 0 and cap >= board.price(r):
                return {"a": "install", "x": h[0], "y": h[1], "res": r}

    # 2) build a datacenter that will reach a station, closest to the city
    if cap >= COST[DC]:
        cands = [h for h in empties if adj(h) and _reachable_from(board, owner, h)]
        cands.sort(key=lambda h: hex_dist(h, CITY[owner]))
        if cands:
            h = cands[0]; return {"a": "build", "piece": DC, "x": h[0], "y": h[1]}

    reachable = any(has_stn(c) for c in comps)
    # 3) no station yet: reach a shared station with a line, else build own
    if not reachable:
        if cap >= COST[LINE]:
            cands = [h for h in empties if (adj(h) or not nodes)]
            cands.sort(key=lambda h: min(hex_dist(h, s) for s in NEUTRAL_STATIONS))
            if cands:
                h = cands[0]; return {"a": "build", "piece": LINE, "x": h[0], "y": h[1]}
        if cap >= COST[STATION]:
            cands = [h for h in empties if adj(h)] or empties
            cands.sort(key=lambda h: hex_dist(h, CITY[owner]))
            h = cands[0]; return {"a": "build", "piece": STATION, "x": h[0], "y": h[1]}

    # 4) enough demand for more power? add our own station near the city
    if cap >= COST[STATION] and len(conn) >= 2:
        cands = [h for h in empties if adj(h)]
        if cands:
            cands.sort(key=lambda h: hex_dist(h, CITY[owner]))
            h = cands[0]; return {"a": "build", "piece": STATION, "x": h[0], "y": h[1]}

    # 5) expand toward a station / seed near the city
    if cap >= COST[LINE]:
        cands = [h for h in empties if adj(h)] or empties
        cands.sort(key=lambda h: min(hex_dist(h, s) for s in NEUTRAL_STATIONS)
                   if nodes else hex_dist(h, CITY[owner]))
        h = cands[0]; return {"a": "build", "piece": LINE, "x": h[0], "y": h[1]}
    return {"a": "pass"}


def play(policies=None):
    policies = policies or [ai_move, ai_move]
    b = Board()
    guard = 0
    while b.winner is None and guard < 5000:
        guard += 1
        act = policies[b.to_move](b, b.to_move)
        if not b.is_legal(act):
            act = {"a": "pass"}
        b.apply(act)
    return b
