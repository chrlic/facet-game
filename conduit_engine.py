"""CONDUIT — prototype engine + max-flow evaluator + self-play balance sim.

A fiber-backhaul flow game on a DEGREE-6 hex-cell board. Each player builds their own capacitated link
network from a corner PoP to shared exchanges (sinks); each tick the game computes the MAX-FLOW each
player can deliver (capped by their own min-cut) and pays for throughput. See CONDUIT.md for the design.

The point of this file: prove the core is (a) computable, (b) non-degenerate, (c) roughly fair, using a
principled max-flow AI in self-play. Run:  python3 conduit_engine.py [nGames] [radius] [ticks]
"""
import sys, random, collections

A, B = 0, 1                      # players
DIRS = [(1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)]   # hex axial neighbours (degree 6)


# ----------------------------------------------------------------------------- board
def gen_board(R):
    cells = [(q, r) for q in range(-R, R + 1) for r in range(-R, R + 1) if abs(q + r) <= R]
    cellset = set(cells)
    adj = {c: [(c[0] + d[0], c[1] + d[1]) for d in DIRS if (c[0] + d[0], c[1] + d[1]) in cellset] for c in cells}
    return cells, cellset, adj


def make_scenario(R):
    """Symmetric fiber scenario: two opposite-corner PoPs, exchanges placed in 180deg-symmetric pairs
    plus a high-demand centre. Negating axial coords is a 180deg rotation, so the map is fair."""
    cells, cellset, adj = gen_board(R)
    srcA = (-R, R); srcB = (R, -R)                      # player 0 (you) bottom-left, matching the other games
    # exchanges: (cell, demand, price). centre is the fat contested one; two symmetric mid pairs.
    raw = [((0, 0), 4, 3)]
    for cell, dem, price in [((R - 1, -1), 3, 3), ((1, R - 2), 2, 4)]:
        raw.append((cell, dem, price))
        raw.append(((-cell[0], -cell[1]), dem, price))   # its 180deg mirror
    sinks = [(c, d, p) for (c, d, p) in raw if c in cellset]
    return dict(cells=cells, cellset=cellset, adj=adj, src=[srcA, srcB], sinks=sinks)


# ----------------------------------------------------------------------------- Dinic max-flow
class Dinic:
    def __init__(self, n):
        self.n = n; self.g = [[] for _ in range(n)]
    def add(self, u, v, c):                              # directed arc u->v cap c (+ 0-cap reverse)
        self.g[u].append([v, c, len(self.g[v])])
        self.g[v].append([u, 0, len(self.g[u]) - 1])
    def _bfs(self, s, t):
        self.lv = [-1] * self.n; self.lv[s] = 0; q = collections.deque([s])
        while q:
            u = q.popleft()
            for v, c, _ in self.g[u]:
                if c > 0 and self.lv[v] < 0:
                    self.lv[v] = self.lv[u] + 1; q.append(v)
        return self.lv[t] >= 0
    def _dfs(self, u, t, f):
        if u == t: return f
        while self.it[u] < len(self.g[u]):
            e = self.g[u][self.it[u]]
            v, c, rev = e
            if c > 0 and self.lv[v] == self.lv[u] + 1:
                d = self._dfs(v, t, min(f, c))
                if d > 0:
                    e[1] -= d; self.g[v][rev][1] += d; return d
            self.it[u] += 1
        return 0
    def maxflow(self, s, t):
        flow = 0
        while self._bfs(s, t):
            self.it = [0] * self.n
            while True:
                f = self._dfs(s, t, float("inf"))
                if not f: break
                flow += f
        return flow
    def min_cut_reachable(self, s):                     # residual-reachable set from s => source side of a min-cut
        seen = [False] * self.n; seen[s] = True; q = collections.deque([s])
        while q:
            u = q.popleft()
            for v, c, _ in self.g[u]:
                if c > 0 and not seen[v]: seen[v] = True; q.append(v)
        return seen


def _build_graph(links, cells, extra_nodes=0):
    idx = {c: i for i, c in enumerate(cells)}
    d = Dinic(len(cells) + extra_nodes)
    for (u, v), cap in links.items():                   # undirected fiber => an arc each way at full cap
        d.add(idx[u], idx[v], cap); d.add(idx[v], idx[u], cap)
    return d, idx


def flow_to_one(links, source, sink, cells):
    """Max reach from `source` to a single `sink` in this player's network (uncapped sink)."""
    if source == sink: return 0
    d, idx = _build_graph(links, cells)
    return d.maxflow(idx[source], idx[sink])


def delivered(links, source, sink_caps, cells):
    """Max-flow from source to a super-sink, each exchange feeding it at its contended share.
    Returns (throughput, dinic, idx, T) so callers can pull the min-cut if they want."""
    d, idx = _build_graph(links, cells, extra_nodes=1)
    T = len(cells)                                      # super-sink index
    any_cap = False
    for s, cap in sink_caps.items():
        if cap > 0: d.add(idx[s], T, cap); any_cap = True
    if source not in idx or not any_cap: return 0, d, idx, T
    return d.maxflow(idx[source], T), d, idx, T


# ----------------------------------------------------------------------------- game state + flow resolve
class Game:
    def __init__(self, sc, ticks=24):
        self.sc = sc; self.ticks = ticks
        self.links = [dict(), dict()]                   # per player: {(u,v) sorted : capacity}
        self.credit = [12, 12]                          # equal start; measure the natural move-order edge first
        self.revenue = [0, 0]                           # cumulative score
        self.throttle = {}                              # (player,(u,v)) -> ticks remaining
        self.tick = 0

    # ---- flow resolution: contended shares, then each player's delivered max-flow ----
    def resolve(self):
        sc = self.sc
        eff = [self._effective_links(p) for p in (A, B)]
        reach = [{}, {}]
        for (cell, dem, price) in sc["sinks"]:
            for p in (A, B):
                reach[p][cell] = flow_to_one(eff[p], sc["src"][p], cell, sc["cells"])
        capA, capB = {}, {}
        for (cell, dem, price) in sc["sinks"]:
            a, b = reach[A][cell], reach[B][cell]; tot = a + b
            if tot == 0: capA[cell] = capB[cell] = 0; continue
            ca = dem * a // tot; cb = dem * b // tot
            rem = dem - ca - cb                          # give the leftover unit to the stronger reach
            if rem:
                if a >= b: ca += rem
                else: cb += rem
            capA[cell], capB[cell] = ca, cb
        thr = [0, 0]
        for p, caps in ((A, capA), (B, capB)):
            t, *_ = delivered(eff[p], sc["src"][p], caps, sc["cells"])
            thr[p] = t
        return thr, (capA, capB)

    def _effective_links(self, p):
        """This player's links with active throttles applied (interdiction lowers capacity)."""
        out = dict(self.links[p])
        for (pl, e), _ in self.throttle.items():
            if pl == p and e in out: out[e] = max(0, out[e] - 1)
        return out

    # ---- helpers ----
    def _touch(self, p):                                # cells the player's network reaches (for adjacency rules)
        s = {self.sc["src"][p]}
        for (u, v) in self.links[p]: s.add(u); s.add(v)
        return s

    def legal_builds(self, p):
        touched = self._touch(p); occupied = set(self.links[A]) | set(self.links[B])
        out = []
        for c in touched:
            for nb in self.sc["adj"][c]:
                e = tuple(sorted((c, nb)))
                if e not in occupied: out.append(e)
        return list(set(out))

    def legal_upgrades(self, p):
        return [e for e, cap in self.links[p].items() if cap < 3]

    def legal_interdicts(self, p):
        opp = 1 - p; touched = self._touch(p); out = []
        for e, cap in self.links[opp].items():
            if cap > 0 and (e[0] in touched or e[1] in touched) and (opp, e) not in self.throttle:
                out.append(e)
        return out

    COST = dict(build=3, upgrade=2, interdict=3)

    def apply(self, p, mv):
        kind, e = mv
        c = self.COST[kind]
        if self.credit[p] < c: return False
        if kind == "build":
            if e in self.links[A] or e in self.links[B]: return False
            self.links[p][e] = 1
        elif kind == "upgrade":
            if e not in self.links[p] or self.links[p][e] >= 3: return False
            self.links[p][e] += 1
        elif kind == "interdict":
            self.throttle[(1 - p, e)] = 3               # heals after 3 ticks
        self.credit[p] -= c
        return True

    def clone(self):
        g = Game.__new__(Game); g.sc = self.sc; g.ticks = self.ticks
        g.links = [dict(self.links[0]), dict(self.links[1])]; g.credit = list(self.credit)
        g.revenue = list(self.revenue); g.throttle = dict(self.throttle); g.tick = self.tick
        return g

    def tick_income(self, thr):
        for p in (A, B):
            self.revenue[p] += thr[p]                    # cumulative score = total delivered bandwidth
            self.credit[p] += 4 + thr[p]                 # base + revenue reinvested
        # decay throttles
        for k in list(self.throttle):
            self.throttle[k] -= 1
            if self.throttle[k] <= 0: del self.throttle[k]


# ----------------------------------------------------------------------------- max-flow AI (greedy 1-ply)
def reach_potential(g, p):
    """Shaping term: -Σ hop-distance from the player's network to each exchange, through edges not
    blocked by the opponent. Gives the greedy AI a gradient to LAY PATHS before any flow exists
    (a single link delivers 0 throughput, so without this the AI never starts)."""
    touched = g._touch(p); opp_edges = set(g.links[1 - p])
    dist = {c: 0 for c in touched}; q = collections.deque(touched)
    while q:
        u = q.popleft()
        for nb in g.sc["adj"][u]:
            if tuple(sorted((u, nb))) in opp_edges: continue     # can't build/route through enemy fiber
            if nb not in dist: dist[nb] = dist[u] + 1; q.append(nb)
    return -sum(dist.get(cell, 12) for (cell, dem, price) in g.sc["sinks"])


def ai_take_turn(g, p, rng):
    """Spend the action budget greedily: each action, pick the legal move maximising
    (myThroughput - oppThroughput) + a small path-progress shaping term, both from a real max-flow
    resolve. Throughput dominates once connected; shaping only breaks the zero-gradient early."""
    budget = 3; SHAPE = 0.2
    while budget > 0 and g.credit[p] >= min(g.COST.values()):
        base_thr, _ = g.resolve()
        base = (base_thr[p] - base_thr[1 - p]) + SHAPE * reach_potential(g, p)
        cands = ([("build", e) for e in g.legal_builds(p) if g.credit[p] >= g.COST["build"]] +
                 [("upgrade", e) for e in g.legal_upgrades(p) if g.credit[p] >= g.COST["upgrade"]] +
                 [("interdict", e) for e in g.legal_interdicts(p) if g.credit[p] >= g.COST["interdict"]])
        if not cands: break
        rng.shuffle(cands)                               # break ties randomly for variety
        best, best_gain = None, 1e-9                     # require a strictly positive marginal gain
        for mv in cands:
            snap = [dict(g.links[0]), dict(g.links[1])]; snap_thr = dict(g.throttle); snap_cred = list(g.credit)
            if not g.apply(p, mv):
                g.links = snap; g.throttle = snap_thr; g.credit = snap_cred; continue
            t, _ = g.resolve()
            gain = (t[p] - t[1 - p]) + SHAPE * reach_potential(g, p) - base
            if mv[0] == "interdict": gain -= 0.25        # an interdict must clearly beat building
            g.links = snap; g.throttle = snap_thr; g.credit = snap_cred      # restore
            if gain > best_gain: best_gain, best = gain, mv
        if best is None: break
        g.apply(p, best); budget -= 1


# ----------------------------------------------------------------------------- self-play balance sim
def play_game(sc, ticks, rng, swap=False, first_bonus=0, simultaneous=False):
    g = Game(sc, ticks)
    first = B if swap else A                             # who moves first this game
    g.credit[first] += first_bonus                       # compensation knob for the reaction advantage
    order = [first, 1 - first]
    thr_hist = []
    for _ in range(ticks):
        if simultaneous:
            # both decide against the SAME pre-tick state (no reaction), then apply together;
            # `first` wins any edge both tried to build.
            ga = g.clone(); ai_take_turn(ga, order[0], rng)
            gb = g.clone(); ai_take_turn(gb, order[1], rng)
            p0, p1 = order
            l0, l1 = ga.links[p0], gb.links[p1]
            for e in set(l0) & set(l1):                  # edge conflict -> p0 (the "first" decider) keeps it
                if e not in g.links[p0] and e not in g.links[p1]: del l1[e]
            g.links[p0] = l0; g.links[p1] = l1
            g.credit[p0] = ga.credit[p0]; g.credit[p1] = gb.credit[p1]
            g.throttle = {**ga.throttle, **gb.throttle}
        else:
            for p in order:
                ai_take_turn(g, p, rng)
        thr, _ = g.resolve()
        g.tick_income(thr); g.tick += 1
        thr_hist.append(tuple(thr))
    return g, thr_hist


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    R = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    ticks = int(sys.argv[3]) if len(sys.argv) > 3 else 20
    sc = make_scenario(R)
    print(f"CONDUIT sim: R={R} ({len(sc['cells'])} cells, deg-6), {len(sc['sinks'])} exchanges, "
          f"{ticks} ticks, {n} games")
    fb = int(sys.argv[4]) if len(sys.argv) > 4 else 0   # first-mover credit compensation (balance knob)
    rng = random.Random(7)
    firstwins = 0; margins = []; finals = []; mincuts = []
    for i in range(n):
        swap = (i % 2 == 1)                              # alternate who is "first" to isolate first-mover edge
        sim = "sim" in sys.argv                          # pass 'sim' to test simultaneous-turn resolution
        g, hist = play_game(sc, ticks, rng, swap=swap, first_bonus=fb, simultaneous=sim)
        first = B if swap else A
        rf, rs = g.revenue[first], g.revenue[1 - first]
        if rf > rs: firstwins += 1
        margins.append(abs(g.revenue[0] - g.revenue[1]))
        finals.append(tuple(g.revenue))
        # measure a network's min-cut width at game end (how fragile are the built nets?)
        for p in (A, B):
            _, cap = g.resolve()
            t, d, idx, T = delivered(g._effective_links(p), sc["src"][p], cap[p], sc["cells"])
            mincuts.append(t)
    import statistics as st
    print(f"  first-mover win-rate : {firstwins}/{n} = {firstwins/n:.2f}   (0.5 = fair)")
    print(f"  avg victory margin   : {st.mean(margins):.1f} bandwidth-units cumulative")
    print(f"  avg final revenue    : {st.mean(a for a,_ in finals):.0f} vs {st.mean(b for _,b in finals):.0f}")
    print(f"  delivered/tick spread: min {min(mincuts)}  median {int(st.median(mincuts))}  max {max(mincuts)}"
          f"   (want a spread, not all pinned at 1 or all huge)")
    # show one sample game's throughput trajectory
    g, hist = play_game(sc, ticks, rng)
    print("  sample throughput/tick (A,B):", " ".join(f"{a},{b}" for a, b in hist))


if __name__ == "__main__":
    main()
