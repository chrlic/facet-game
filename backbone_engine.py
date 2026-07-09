"""BACKBONE game engine + AI.

A 2-player network-building game on a 9x9 pointy-top hex grid (odd rows
offset right, "odd-r"). See Backbone_Rulebook.md for the original rules and
BACKBONE_FAIRNESS.md for the simulation study behind the changes below.

Defaults implement ruleset v1.1 (simulation-validated: 0% stalemates over
150 games, P1 win ratio 0.451 CI[0.371,0.533]), which changes four things
from the rulebook as printed:
  - cities=SYM_CITIES: two cities moved ((5,7)->(4,7), (3,7)->(2,7)) so the
    board is a true 180-degree hex rotation instead of an offset-coordinate
    reflection (the printed layout gives P2 strictly shorter city distances)
  - target_vp=10 (was 12): 12 VP is unreachable under mutual hacking in
    self-play (100% stalemate rate in simulation); building beats hacking at 10
  - hack_cost=1, hack_limit=1 (was 2, unlimited): the rulebook's own
    "Aggressive" variant, promoted to default — unlimited 2-BW hacks let
    hacking suppress VP faster than it can be rebuilt
  - final_turn=True: if P1 ends a turn at/above target_vp, P2 gets one last
    turn before the game is scored, removing most of the first-move edge
To reproduce the rulebook exactly: Board(cities=CITIES, target_vp=12,
hack_cost=2, hack_limit=None, final_turn=False).

Other documented resolutions of rulebook ambiguities:
  - Disabled markers persist through the victim's whole next turn INCLUDING
    scoring (matches the rulebook's example; its step table is ambiguous),
    and are cleared at the very end of that turn.
  - A 'pass' action exists; four consecutive passes (both players stuck for
    a full round) ends the game on VP, then connected cities, then draw.
  - A Server serves exactly ONE adjacent city, chosen when built.
  - Discarded Firewalls return to the owner's supply.
  - Disabled pieces cannot be rerouted.
  - Rerouting to the same hex is not legal (must be a different hex).
  - The DC link bonus (+2, once) needs >=2 of your non-disabled Datacenters
    in the same network component.

Actions are plain dicts (JSON-safe, one action per recorded move):
  {"a":"build","piece":"router","x":3,"y":2}          (server: +"city":[x,y])
  {"a":"build","piece":"firewall","x":3,"y":2}        (on own piece)
  {"a":"hack","x":5,"y":5}
  {"a":"reroute","fx":1,"fy":1,"tx":2,"ty":2}
  {"a":"pass"}
"""
import random
import time

W = H = 9
CITIES = ((1, 4), (7, 4), (3, 1), (5, 7), (5, 1), (3, 7), (4, 4))
# The rulebook's city set is mirrored in OFFSET coordinates, which is not a
# hex isometry — P2 is strictly closer to most cities. This set keeps the
# rulebook's intent but uses the true 180-degree hex rotation about (4,4):
SYM_CITIES = ((1, 4), (7, 4), (3, 1), (4, 7), (5, 1), (2, 7), (4, 4))
START = ((0, 0), (8, 8))
SERVER_START = ((1, 0), (7, 8))
PIECES = ("router", "switch", "ap", "firewall", "server", "dc")
SUPPLY = {"router": 14, "switch": 8, "ap": 5, "firewall": 6, "server": 6,
          "dc": 4}
COST = {"router": 2, "switch": 1, "ap": 3, "firewall": 2, "server": 3,
        "dc": 6}
TARGET_VP = 12
HAND_LIMIT = 10
INCOME_BASE = 3
HACK_COST = 2
MAX_DISABLED = 6


# ---------------- hex math (odd-r offset, pointy-top) ----------------
def neighbors(x, y):
    if y % 2 == 0:
        d = ((1, 0), (-1, 0), (0, 1), (-1, 1), (0, -1), (-1, -1))
    else:
        d = ((1, 0), (-1, 0), (1, 1), (0, 1), (1, -1), (0, -1))
    return [(x + dx, y + dy) for dx, dy in d]


def in_board(x, y):
    return 0 <= x < W and 0 <= y < H


def to_axial(x, y):
    return x - (y - (y & 1)) // 2, y


def from_axial(q, r):
    return q + (r - (r & 1)) // 2, r


AXIAL_DIRS = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, -1), (-1, 1))


def jump_targets(x, y):
    """(jumped_hex, landing_hex) pairs two steps out in each straight line."""
    q, r = to_axial(x, y)
    out = []
    for dq, dr in AXIAL_DIRS:
        mid = from_axial(q + dq, r + dr)
        far = from_axial(q + 2 * dq, r + 2 * dr)
        if in_board(*far):
            out.append((mid, far))
    return out


def hex_distance(a, b):
    aq, ar = to_axial(*a)
    bq, br = to_axial(*b)
    dq, dr = aq - bq, ar - br
    return (abs(dq) + abs(dr) + abs(dq + dr)) // 2


class Board:
    """Backbone game state. Deterministic; replayable from the action log.

    Rule knobs (defaults = v1.1, see module docstring) also allow
    reconstructing the rulebook as printed or any tested variant:
    recover_before_score follows the rulebook's step table instead of its
    example; hack_limit is the 'Aggressive' variant hook; cities/target_vp/
    hack_cost/p2_bonus_bw/final_turn are all simulation-tunable."""

    def __init__(self, recover_before_score=False, target_vp=10,
                 hack_cost=1, hack_limit=1, p2_bonus_bw=2,
                 cities=None, final_turn=True):
        self.recover_before_score = recover_before_score
        self.target_vp = target_vp
        self.hack_cost = hack_cost
        self.hack_limit = hack_limit
        self.hacks_this_turn = 0
        self.cities = tuple(tuple(c) for c in (cities or SYM_CITIES))
        self.city_set = set(self.cities)
        self.final_turn = final_turn   # P2 gets one equalizing turn
        self.final_pending = False
        self.pieces = {}         # (x,y) -> (owner, kind)
        self.firewalls = set()   # hexes carrying a firewall
        self.disabled = set()    # hexes currently disabled
        self.server_city = {}    # server hex -> city hex it serves
        self.bw = [3, 3 + p2_bonus_bw]  # P2's bonus offsets going second
        self.supply = [dict(SUPPLY), dict(SUPPLY)]
        self.to_move = 0
        self.actions_left = 2
        self.turn_no = 1
        self.pass_streak = 0
        self.winner = None       # None | 0 | 1 | 'draw'
        for p in (0, 1):
            self.pieces[START[p]] = (p, "router")
            self.pieces[SERVER_START[p]] = (p, "server")
            self.supply[p]["router"] -= 1
            self.supply[p]["server"] -= 1
            # the starting server has no adjacent city; serves none
        self._income(0)          # turn step 1 for P1's first turn

    # ---------------- queries ----------------
    def clone(self):
        b = Board.__new__(Board)
        b.cities = self.cities
        b.city_set = self.city_set
        b.final_turn = self.final_turn
        b.final_pending = self.final_pending
        b.recover_before_score = self.recover_before_score
        b.target_vp = self.target_vp
        b.hack_cost = self.hack_cost
        b.hack_limit = self.hack_limit
        b.hacks_this_turn = self.hacks_this_turn
        b.pieces = dict(self.pieces)
        b.firewalls = set(self.firewalls)
        b.disabled = set(self.disabled)
        b.server_city = dict(self.server_city)
        b.bw = list(self.bw)
        b.supply = [dict(self.supply[0]), dict(self.supply[1])]
        b.to_move = self.to_move
        b.actions_left = self.actions_left
        b.turn_no = self.turn_no
        b.pass_streak = self.pass_streak
        b.winner = self.winner
        return b

    def _conn_neighbors(self, h):
        """Hexes whose pieces this piece can link to (incl. AP jumps both ways)."""
        x, y = h
        owner, kind = self.pieces[h]
        out = [n for n in neighbors(x, y) if in_board(*n)]
        if kind == "ap":
            out += [far for _mid, far in jump_targets(x, y)]
        else:
            # a remote AP of ours may reach US over a jump; adjacency is mutual
            for mid, far in jump_targets(x, y):
                p = self.pieces.get(far)
                if p and p[0] == owner and p[1] == "ap":
                    out.append(far)
        return out

    def network(self, owner):
        """Hexes of owner's pieces connected to the start hex.
        Disabled pieces do not connect (and break chains through them)."""
        root = START[owner]
        p = self.pieces.get(root)
        if not p or p[0] != owner or root in self.disabled:
            return set()
        seen = {root}
        stack = [root]
        while stack:
            h = stack.pop()
            for n in self._conn_neighbors(h):
                if n in seen or n in self.disabled:
                    continue
                q = self.pieces.get(n)
                if q and q[0] == owner:
                    seen.add(n)
                    stack.append(n)
        return seen

    def frontier(self, owner, net=None):
        """Empty non-city hexes where owner may place a new piece."""
        net = self.network(owner) if net is None else net
        out = set()
        for h in net:
            x, y = h
            cand = [n for n in neighbors(x, y) if in_board(*n)]
            if self.pieces[h][1] == "ap":
                cand += [far for _mid, far in jump_targets(x, y)]
            for n in cand:
                if n not in self.pieces and n not in self.city_set:
                    out.add(n)
        return out

    def hackable(self, owner, net=None):
        """Enemy pieces adjacent to owner's network (incl. via AP jumps)."""
        net = self.network(owner) if net is None else net
        out = set()
        for h in net:
            x, y = h
            cand = [n for n in neighbors(x, y) if in_board(*n)]
            if self.pieces[h][1] == "ap":
                cand += [far for _mid, far in jump_targets(x, y)]
            for n in cand:
                q = self.pieces.get(n)
                if q and q[0] != owner and n not in self.disabled:
                    out.add(n)
        return out

    def connected_cities(self, owner, net=None):
        net = self.network(owner) if net is None else net
        cities = set()
        for h, city in self.server_city.items():
            if (h in net and h not in self.disabled
                    and self.pieces.get(h, (None,))[0] == owner):
                cities.add(city)
        return cities

    def dc_online(self, h, net=None):
        owner = self.pieces[h][0]
        net = self.network(owner) if net is None else net
        if h not in net or h in self.disabled:
            return False
        routers = sum(1 for n in neighbors(*h)
                      if in_board(*n) and n not in self.disabled
                      and self.pieces.get(n) == (owner, "router"))
        if routers < 2:
            return False
        return any(self.pieces[s][1] == "server" and s not in self.disabled
                   for s in net if self.pieces[s][1] == "server")

    def score(self, owner):
        net = self.network(owner)
        vp = len(self.connected_cities(owner, net))
        dcs_in_net = [h for h, (o, k) in self.pieces.items()
                      if o == owner and k == "dc" and h in net
                      and h not in self.disabled]
        vp += sum(1 for h in dcs_in_net if self.dc_online(h, net))
        if len(dcs_in_net) >= 2:
            vp += 2
        return vp

    # ---------------- legality ----------------
    def _place_ok(self, owner, kind, h, net):
        if h in self.pieces or h in self.city_set or not in_board(*h):
            return False
        if h not in self.frontier(owner, net):
            return False
        if kind == "switch":
            own_adj = sum(1 for n in neighbors(*h)
                          if self.pieces.get(n, (None,))[0] == owner)
            if own_adj < 2:
                return False
        return True

    def legal_actions(self, owner=None):
        """All legal actions for the side to move (owner defaults to it)."""
        if self.winner is not None:
            return []
        owner = self.to_move if owner is None else owner
        acts = [{"a": "pass"}]
        net = self.network(owner)
        bw = self.bw[owner]
        front = self.frontier(owner, net)
        for kind in PIECES:
            if self.supply[owner][kind] < 1 or COST[kind] > bw:
                continue
            if kind == "firewall":
                for h, (o, _k) in self.pieces.items():
                    if o == owner and h not in self.firewalls:
                        acts.append({"a": "build", "piece": "firewall",
                                     "x": h[0], "y": h[1]})
                continue
            for h in front:
                if kind == "switch":
                    own_adj = sum(1 for n in neighbors(*h)
                                  if self.pieces.get(n, (None,))[0] == owner)
                    if own_adj < 2:
                        continue
                if kind == "server":
                    adj_cities = [c for c in neighbors(*h)
                                  if c in self.city_set]
                    if adj_cities:
                        for c in adj_cities:
                            acts.append({"a": "build", "piece": "server",
                                         "x": h[0], "y": h[1],
                                         "city": [c[0], c[1]]})
                        continue
                acts.append({"a": "build", "piece": kind,
                             "x": h[0], "y": h[1]})
        if (bw >= self.hack_cost and len(self.disabled) < MAX_DISABLED
                and (self.hack_limit is None
                     or self.hacks_this_turn < self.hack_limit)):
            for h in self.hackable(owner, net):
                acts.append({"a": "hack", "x": h[0], "y": h[1]})
        for h, (o, kind) in list(self.pieces.items()):
            if o != owner or kind not in ("switch", "ap"):
                continue
            if h in self.disabled or h in START:
                continue
            for t in self._reroute_targets(owner, h):
                acts.append({"a": "reroute", "fx": h[0], "fy": h[1],
                             "tx": t[0], "ty": t[1]})
        return acts

    def _reroute_targets(self, owner, h):
        """Legal destinations for moving the switch/AP at h."""
        kind = self.pieces[h][1]
        before = len(self.network(owner))
        trial = self.clone()
        piece = trial.pieces.pop(h)
        trial.firewalls.discard(h)  # firewall moves with the piece
        out = []
        net = trial.network(owner)
        for t in trial.frontier(owner, net):
            if t == h:
                continue  # rulebook: reroute moves to a DIFFERENT hex
            if kind == "switch":
                own_adj = sum(1 for n in neighbors(*t)
                              if trial.pieces.get(n, (None,))[0] == owner)
                if own_adj < 2:
                    continue
            trial.pieces[t] = piece
            after = len(trial.network(owner))
            if after >= before:
                out.append(t)
            del trial.pieces[t]
        return out

    def is_legal(self, action, owner=None):
        owner = self.to_move if owner is None else owner
        a = action.get("a")
        if self.winner is not None:
            return False
        if a == "pass":
            return True
        net = self.network(owner)
        if a == "build":
            kind = action.get("piece")
            h = (action.get("x"), action.get("y"))
            if kind not in PIECES or self.supply[owner][kind] < 1 \
                    or self.bw[owner] < COST[kind]:
                return False
            if kind == "firewall":
                p = self.pieces.get(h)
                return (p is not None and p[0] == owner
                        and h not in self.firewalls)
            if not self._place_ok(owner, kind, h, net):
                return False
            if kind == "server":
                adj_cities = [c for c in neighbors(*h) if c in self.city_set]
                city = action.get("city")
                if adj_cities:
                    return city is not None and tuple(city) in adj_cities
                return city is None
            return True
        if a == "hack":
            h = (action.get("x"), action.get("y"))
            return (self.bw[owner] >= self.hack_cost
                    and len(self.disabled) < MAX_DISABLED
                    and (self.hack_limit is None
                         or self.hacks_this_turn < self.hack_limit)
                    and h in self.hackable(owner, net))
        if a == "reroute":
            f = (action.get("fx"), action.get("fy"))
            t = (action.get("tx"), action.get("ty"))
            p = self.pieces.get(f)
            if (not p or p[0] != owner or p[1] not in ("switch", "ap")
                    or f in self.disabled or f in START):
                return False
            return t in self._reroute_targets(owner, f)
        return False

    # ---------------- state changes ----------------
    def apply(self, action):
        """Apply one legal action for the side to move (validate first!)."""
        owner = self.to_move
        a = action["a"]
        if a == "pass":
            self.pass_streak += 1
        else:
            self.pass_streak = 0
        if a == "build":
            kind = action["piece"]
            h = (action["x"], action["y"])
            self.bw[owner] -= COST[kind]
            self.supply[owner][kind] -= 1
            if kind == "firewall":
                self.firewalls.add(h)
            else:
                self.pieces[h] = (owner, kind)
                if kind == "server" and action.get("city") is not None:
                    self.server_city[h] = tuple(action["city"])
        elif a == "hack":
            h = (action["x"], action["y"])
            self.bw[owner] -= self.hack_cost
            self.hacks_this_turn += 1
            if h in self.firewalls:
                self.firewalls.discard(h)
                self.supply[self.pieces[h][0]]["firewall"] += 1
            else:
                self.disabled.add(h)
        elif a == "reroute":
            f = (action["fx"], action["fy"])
            t = (action["tx"], action["ty"])
            self.pieces[t] = self.pieces.pop(f)
            if f in self.firewalls:
                self.firewalls.discard(f)
                self.firewalls.add(t)
            if f in self.server_city:  # unreachable (servers don't reroute)
                self.server_city[t] = self.server_city.pop(f)
        self.actions_left -= 1
        if self.actions_left <= 0:
            self._end_turn(owner)

    def _end_turn(self, owner):
        if self.recover_before_score:  # rulebook table order (step 3 then 4)
            self.disabled = {h for h in self.disabled
                             if self.pieces[h][0] != owner}
        # step 4: score (default: our disabled pieces still down — module doc)
        s = self.score(owner)
        if self.final_pending and owner == 1:
            # P1 reached the target last turn; P2 just took the equalizer
            s0 = self.score(0)
            if s > s0:
                self.winner = 1
            elif s == s0:
                c0 = len(self.connected_cities(0))
                c1 = len(self.connected_cities(1))
                self.winner = 1 if c1 > c0 else 0 if c0 > c1 else "draw"
            else:
                self.winner = 0
            return
        if s >= self.target_vp:
            if self.final_turn and owner == 0:
                self.final_pending = True  # P2 gets one last turn
            else:
                self.winner = owner
                return
        if self.pass_streak >= 4:  # both players stuck for a full round
            s0, s1 = self.score(0), self.score(1)
            if s0 != s1:
                self.winner = 0 if s0 > s1 else 1
            else:
                c0 = len(self.connected_cities(0))
                c1 = len(self.connected_cities(1))
                self.winner = 0 if c0 > c1 else 1 if c1 > c0 else "draw"
            return
        # recover our pieces at the very end of our turn
        self.disabled = {h for h in self.disabled
                         if self.pieces[h][0] != owner}
        self.to_move ^= 1
        self.actions_left = 2
        self.hacks_this_turn = 0
        self.turn_no += 1
        self._income(self.to_move)

    def _income(self, owner):
        gain = INCOME_BASE + len(self.connected_cities(owner))
        self.bw[owner] = min(HAND_LIMIT, self.bw[owner] + gain)


# ---------------- AI ----------------
def evaluate(board, owner):
    """Heuristic: VP dominates; then economy, infrastructure progress,
    threats. Positive = good for owner."""
    if board.winner is not None:
        if board.winner == owner:
            return 10_000
        if board.winner == (owner ^ 1):
            return -10_000
        return 0

    def side(o):
        net = board.network(o)
        vp = board.score(o)
        v = vp * 120.0
        v += board.bw[o] * 1.5
        cities = board.connected_cities(o, net)
        v += len(cities) * 10          # cities also pay income
        # progress toward DCs coming online
        servers_ok = any(board.pieces[h][1] == "server"
                         and h not in board.disabled for h in net
                         if board.pieces[h][1] == "server")
        for h, (po, k) in board.pieces.items():
            if po != o:
                continue
            if k == "dc":
                routers = sum(1 for n in neighbors(*h)
                              if board.pieces.get(n) == (o, "router")
                              and n not in board.disabled)
                v += min(routers, 2) * 8
                if h in net:
                    v += 6
                    if servers_ok:
                        v += 6
            if h in board.disabled:
                v -= 9
        # closeness of network to unserved cities (expansion potential)
        for c in board.cities:
            if c in cities:
                continue
            d = min((hex_distance(h, c) for h in net), default=9)
            v += max(0, 5 - d) * 1.2
        v += len(net) * 1.0
        # exposed critical pieces (server/dc without firewall, enemy nearby)
        threat = board.hackable(o ^ 1)
        for h in threat:
            if board.pieces[h][0] == o and h not in board.firewalls:
                v -= 6 if board.pieces[h][1] in ("server", "dc") else 2
        return v

    return side(owner) - side(owner ^ 1)


def _candidate_actions(board, owner, cap=26):
    """Legal actions, pruned and ordered by a cheap 1-action lookahead."""
    acts = board.legal_actions(owner)
    if len(acts) <= 1:
        return acts
    scored = []
    for act in acts:
        nb = board.clone()
        nb.actions_left = 99  # evaluate the action alone, no turn flip
        nb.apply(act)
        scored.append((evaluate(nb, owner), act))
    scored.sort(key=lambda t: -t[0])
    return [a for _s, a in scored[:cap]]


def ai_action(board, time_budget=0.5, width=8, noise=0.0):
    """Pick the next single action for board.to_move: search action pairs
    (this action + best follow-up this turn) within the budget."""
    owner = board.to_move
    deadline = time.time() + time_budget
    cands = _candidate_actions(board, owner)
    if not cands:
        return {"a": "pass"}
    if len(cands) == 1:
        return cands[0]
    best, best_v = cands[0], -1e18
    for act in cands[:width]:
        nb = board.clone()
        nb.apply(act)
        if nb.winner == owner:
            return act
        if nb.to_move == owner and nb.winner is None:
            # evaluate with the best follow-up action of this same turn
            v = -1e18
            for act2 in _candidate_actions(nb, owner, cap=10):
                nb2 = nb.clone()
                nb2.apply(act2)
                v = max(v, evaluate(nb2, owner))
                if time.time() > deadline:
                    break
        else:
            v = evaluate(nb, owner)
        if noise:
            v += random.uniform(-noise, noise)
        if v > best_v:
            best_v, best = v, act
        if time.time() > deadline:
            break
    return best


DIFF = {  # name -> (time_budget, width, noise)
    "easy": (0.15, 3, 25.0),
    "normal": (0.6, 8, 4.0),
    "hard": (1.5, 14, 0.0),
}


def ai_move(board, difficulty="normal"):
    budget, width, noise = DIFF.get(difficulty, DIFF["normal"])
    return ai_action(board, time_budget=budget, width=width, noise=noise)


# ---------------- plain-language move explanations ----------------
KIND_NAMES = {"router": "Router", "switch": "Switch", "ap": "Wireless AP",
              "firewall": "Firewall", "server": "Server", "dc": "Datacenter"}


def _closest_unclaimed_city_dist(board, owner, h):
    owned = board.connected_cities(owner)
    others = [c for c in board.cities if c not in owned]
    if not others:
        return None
    return min(hex_distance(h, c) for c in others)


def _network_split_size(board, victim_owner, hex_to_disable):
    """How many of victim_owner's OTHER pieces would fall out of their
    network if hex_to_disable became disabled right now."""
    before = len(board.network(victim_owner))
    trial = board.clone()
    trial.disabled.add(hex_to_disable)
    after = len(trial.network(victim_owner))
    return max(0, before - after - 1)  # -1 excludes the hacked hex itself


def _is_bridge(board, owner, h):
    """True if this piece is the sole link holding two parts of owner's
    own network together (losing it would split their empire in two)."""
    before = len(board.network(owner))
    trial = board.clone()
    trial.disabled.add(h)
    after = len(trial.network(owner))
    return after < before - 1


def _feeds_a_dc(board, owner, router_hex):
    """True if this router is one of only 2 (i.e. load-bearing) routers
    keeping one of owner's datacenters online."""
    for h, (o, k) in board.pieces.items():
        if o == owner and k == "dc" and router_hex in neighbors(*h):
            cnt = sum(1 for n in neighbors(*h)
                      if board.pieces.get(n) == (owner, "router")
                      and n not in board.disabled)
            if cnt <= 2:
                return True
    return False


def explain_action(board, action, owner):
    """Plain-language explanation of `action`, about to be taken by `owner`
    on `board` (call BEFORE applying it). Returns {"text": str, "aim": str}
    where aim is one of: expand/score/defend/disrupt/consolidate/wait."""
    a = action["a"]
    opp = owner ^ 1
    if a == "pass":
        return {"text": "Nothing productive left to do this action — saving it.",
                "aim": "wait"}
    if a == "hack":
        h = (action["x"], action["y"])
        p = board.pieces.get(h)
        kind = p[1] if p else "piece"
        bits = []
        split = _network_split_size(board, opp, h)
        if split > 0:
            bits.append(f"cutting {split} of their piece"
                        f"{'s' if split != 1 else ''} off from their network")
        if kind == "server" and board.server_city.get(h):
            bits.append("breaking their connection to a City")
        if kind == "dc":
            bits.append("taking a Datacenter offline")
        if kind == "router" and _feeds_a_dc(board, opp, h):
            bits.append("undermining a Datacenter's Router support")
        if not bits:
            bits.append("denying them a piece and some tempo for a turn")
        return {"text": f"Hacked the enemy {KIND_NAMES.get(kind, kind)} — "
                        + "; ".join(bits) + ".",
                "aim": "disrupt"}
    if a == "reroute":
        f = (action["fx"], action["fy"])
        t = (action["tx"], action["ty"])
        kind = board.pieces[f][1]
        d0 = _closest_unclaimed_city_dist(board, owner, f)
        d1 = _closest_unclaimed_city_dist(board, owner, t)
        if d0 is not None and d1 is not None and d1 < d0:
            return {"text": f"Repositioned a {KIND_NAMES[kind]} to reach "
                            "closer toward an unclaimed City.",
                    "aim": "expand"}
        return {"text": f"Repositioned a {KIND_NAMES[kind]} to firm up "
                        "the network's shape.",
                "aim": "consolidate"}
    if a == "build":
        kind = action["piece"]
        h = (action["x"], action["y"])
        if kind == "dc":
            routers = sum(1 for n in neighbors(*h)
                          if board.pieces.get(n) == (owner, "router"))
            if routers >= 2:
                return {"text": "Built a Datacenter — already backed by "
                                "2 Routers, so it comes online immediately "
                                "for +1 AI token.",
                        "aim": "score"}
            return {"text": f"Built a Datacenter — needs {2 - routers} more "
                            "adjacent Router(s) before it starts earning "
                            "AI tokens.",
                    "aim": "expand"}
        if kind == "server":
            if action.get("city") is not None:
                return {"text": "Built a Server to connect a City — "
                                "+1 AI token as long as it stays networked.",
                        "aim": "score"}
            return {"text": "Built a Server to satisfy a nearby "
                            "Datacenter's requirement (no City adjacent here).",
                    "aim": "expand"}
        if kind == "router":
            enemy_near = any(board.pieces.get(n, (None,))[0] == opp
                             for n in neighbors(*h))
            d = _closest_unclaimed_city_dist(board, owner, h)
            if enemy_near:
                return {"text": "Pushed a Router into contested ground, "
                                "within reach of the enemy's pieces.",
                        "aim": "expand"}
            if d is not None and d <= 3:
                return {"text": "Extended a Router toward an unclaimed "
                                "City to set up a Server there.",
                        "aim": "expand"}
            return {"text": "Extended the network with a Router to open "
                            "up more building room.",
                    "aim": "expand"}
        if kind == "switch":
            return {"text": "Filled a gap with a Switch — cheap glue to "
                            "keep the network efficient.",
                    "aim": "consolidate"}
        if kind == "ap":
            return {"text": "Placed a Wireless AP to jump the network "
                            "across a hex it couldn't otherwise cross.",
                    "aim": "expand"}
        if kind == "firewall":
            if _is_bridge(board, owner, h):
                return {"text": "Shielded the piece holding two halves of "
                                "the network together.",
                        "aim": "defend"}
            p = board.pieces.get(h)
            if p and p[1] == "dc":
                return {"text": "Shielded a Datacenter from being hacked "
                                "offline.", "aim": "defend"}
            if board.server_city.get(h):
                return {"text": "Shielded the Server feeding a City "
                                "connection.", "aim": "defend"}
            return {"text": "Placed a Firewall to protect a piece from "
                            "the next hack.", "aim": "defend"}
    return {"text": "Took an action.", "aim": "other"}


# ---------------- serialization ----------------
def serialize(board):
    return {
        "game": "backbone", "W": W, "H": H,
        "cities": [list(c) for c in board.cities],
        "start": [list(START[0]), list(START[1])],
        "pieces": {f"{x},{y}": {"owner": o, "kind": k}
                   for (x, y), (o, k) in board.pieces.items()},
        "firewalls": [f"{x},{y}" for (x, y) in board.firewalls],
        "disabled": [f"{x},{y}" for (x, y) in board.disabled],
        "server_city": {f"{x},{y}": list(c)
                        for (x, y), c in board.server_city.items()},
        "bw": list(board.bw),
        "supply": [dict(board.supply[0]), dict(board.supply[1])],
        "to_move": board.to_move,
        "actions_left": board.actions_left,
        "turn_no": board.turn_no,
        "vp": [board.score(0), board.score(1)],
        "cities_connected": [
            [list(c) for c in board.connected_cities(0)],
            [list(c) for c in board.connected_cities(1)]],
        "network": [
            [list(h) for h in board.network(0)],
            [list(h) for h in board.network(1)]],
        "dc_online": {f"{x},{y}": board.dc_online((x, y))
                      for (x, y), (o, k) in board.pieces.items() if k == "dc"},
        "winner": board.winner,
        "legal": board.legal_actions() if board.winner is None else [],
    }
