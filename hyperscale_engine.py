"""HYPERSCALE — prototype engine (see HYPERSCALE.md).

Deterministic given the players' policies. Two players race to build AI
datacenters from a shared, finite, dynamically-priced market; score is total
AI tokens produced over the game.

A policy is any object with:
    market_choice(game, me) -> resource symbol or None (pass)
    action_choice(game, me) -> ("start", tier) | ("refresh", dc_index) | None
`me` is the player index (0/1).
"""
from math import ceil, floor


def iround(x):
    """Round half up — matches JS Math.round for the (always positive) prices,
    so the Python and JS engines price identically."""
    return int(floor(x + 0.5))

RESOURCES = ["GPU", "HBM", "CPU", "SSD", "NET", "PWR"]
BUILD_RESOURCES = ["GPU", "HBM", "CPU", "SSD", "NET"]  # consumed into a DC
PREMIUM = ["GPU", "HBM", "NET", "PWR"]

BASE_FLOOR = {"GPU": 3, "HBM": 3, "NET": 4, "PWR": 4, "CPU": 1, "SSD": 1}
INIT_RESERVE = {"GPU": 95, "HBM": 70, "NET": 42, "PWR": 80, "CPU": 300, "SSD": 300}
FRONTIER_K = 1.5
PRICE_K = 0.15

# tier -> recipe/spec
TIERS = {
    "rack":   {"GPU": 2,  "HBM": 1,  "CPU": 1, "SSD": 1, "NET": 0,
               "credits": 4,  "draw": 2,  "build_time": 1, "output": 2.4, "revenue": 1},
    "pod":    {"GPU": 6,  "HBM": 4,  "CPU": 2, "SSD": 2, "NET": 2,
               "credits": 10, "draw": 6,  "build_time": 2, "output": 9,  "revenue": 4},
    "campus": {"GPU": 14, "HBM": 10, "CPU": 4, "SSD": 4, "NET": 6,
               "credits": 24, "draw": 14, "build_time": 2, "output": 38, "revenue": 13},
}
TIER_ORDER = ["rack", "pod", "campus"]

OBSOLESCENCE = 0.90
BASE_INCOME = 32
START_CREDITS = 45
START_POWER = 4
MAX_ROUNDS = 16
P2_CREDIT_BONUS = 2   # alternating order + tiny nudge centres the mirror


def obso_factor(age):
    return OBSOLESCENCE ** age


class Market:
    def __init__(self):
        self.reserve = dict(INIT_RESERVE)
        self.bought = {r: 0 for r in RESOURCES}  # this round

    def depletion(self, r):
        return 1 - self.reserve[r] / INIT_RESERVE[r]

    def floor(self, r):
        return BASE_FLOOR[r] * (1 + FRONTIER_K * self.depletion(r))

    def price(self, r):
        return self.floor(r) * (1 + PRICE_K * self.bought[r])

    def available(self, r):
        return self.reserve[r] > 0

    def cost_of(self, r):
        return iround(self.price(r))

    def buy(self, r):
        """Consume one unit; returns its credit cost (caller must pre-check)."""
        c = self.cost_of(r)
        self.reserve[r] -= 1
        self.bought[r] += 1
        return c

    def end_round(self):
        for r in RESOURCES:
            self.bought[r] = 0


class DC:
    __slots__ = ("tier", "progress", "online", "age")

    def __init__(self, tier):
        self.tier = tier
        self.progress = 0
        self.online = False
        self.age = 0

    @property
    def draw(self):
        return TIERS[self.tier]["draw"]

    def output(self):
        return TIERS[self.tier]["output"] * obso_factor(self.age)

    def revenue(self):
        return TIERS[self.tier]["revenue"] * obso_factor(self.age)


class Player:
    def __init__(self):
        self.credits = START_CREDITS
        self.tokens = 0.0            # cumulative AI-token score
        self.power_capacity = START_POWER
        self.inv = {r: 0 for r in BUILD_RESOURCES}
        self.dcs = []               # list[DC]
        self.last_output = 0.0      # tokens produced in the final round (tiebreak)

    # -- helpers --
    def online_dcs(self):
        return [d for d in self.dcs if d.online]

    def committed_draw(self):
        """Power draw of everything online or under construction."""
        return sum(d.draw for d in self.dcs)

    def can_afford_build(self, tier):
        t = TIERS[tier]
        if self.credits < t["credits"]:
            return False
        return all(self.inv[r] >= t[r] for r in BUILD_RESOURCES)

    def refresh_cost(self, tier):
        t = TIERS[tier]
        res = {r: ceil(0.5 * t[r]) for r in BUILD_RESOURCES}
        return res, ceil(0.5 * t["credits"])

    def can_afford_refresh(self, dc):
        res, cr = self.refresh_cost(dc.tier)
        if self.credits < cr:
            return False
        return all(self.inv[r] >= res[r] for r in BUILD_RESOURCES)


class HyperscaleGame:
    def __init__(self, policies, p2_credit_bonus=0):
        self.market = Market()
        self.players = [Player(), Player()]
        self.players[1].credits += p2_credit_bonus
        self.policies = policies    # [policy0, policy1]
        self.round = 0
        self.log = []

    # ---------- per-round phases ----------
    def _advance_and_produce(self, final):
        for pi, p in enumerate(self.players):
            # construction advances; finished DCs come online (age 0)
            for d in p.dcs:
                if not d.online:
                    d.progress += 1
                    if d.progress >= TIERS[d.tier]["build_time"]:
                        d.online = True
                        d.age = 0
            # power resolution: run most token-efficient-per-power first
            online = p.online_dcs()
            online.sort(key=lambda d: d.output() / d.draw, reverse=True)
            cap = p.power_capacity
            produced = 0.0
            for d in online:
                if cap >= d.draw:
                    cap -= d.draw
                    p.tokens += d.output()
                    p.credits += d.revenue()
                    produced += d.output()
                # else: stranded — powered out, produces nothing this round
            p.last_output = produced
            # age everything online (time-based obsolescence)
            for d in online:
                d.age += 1
            # base income
            p.credits += BASE_INCOME

    def _market_phase(self):
        passed = [False, False]
        # who gets the cheaper first pick alternates each round, so neither
        # player keeps a structural buy-first edge on scarce resources
        order = [0, 1] if self.round % 2 == 1 else [1, 0]
        for _ in range(400):
            if all(passed):
                break
            for pi in order:
                if passed[pi]:
                    continue
                r = self.policies[pi].market_choice(self, pi)
                p = self.players[pi]
                if (r is None or not self.market.available(r)
                        or self.market.cost_of(r) > p.credits):
                    passed[pi] = True
                    continue
                cost = self.market.buy(r)
                p.credits -= cost
                if r == "PWR":
                    p.power_capacity += 1
                else:
                    p.inv[r] += 1

    def _action_phase(self):
        passed = [False, False]
        for _ in range(200):
            if all(passed):
                break
            for pi in range(2):
                if passed[pi]:
                    continue
                act = self.policies[pi].action_choice(self, pi)
                p = self.players[pi]
                if act is None:
                    passed[pi] = True
                    continue
                kind = act[0]
                if kind == "start":
                    tier = act[1]
                    if tier in TIERS and p.can_afford_build(tier):
                        t = TIERS[tier]
                        p.credits -= t["credits"]
                        for r in BUILD_RESOURCES:
                            p.inv[r] -= t[r]
                        p.dcs.append(DC(tier))
                    else:
                        passed[pi] = True
                elif kind == "refresh":
                    idx = act[1]
                    if 0 <= idx < len(p.dcs) and p.dcs[idx].online \
                            and p.can_afford_refresh(p.dcs[idx]):
                        d = p.dcs[idx]
                        res, cr = p.refresh_cost(d.tier)
                        p.credits -= cr
                        for r in BUILD_RESOURCES:
                            p.inv[r] -= res[r]
                        d.age = 0
                    else:
                        passed[pi] = True
                else:
                    passed[pi] = True

    def step(self):
        self.round += 1
        final = self.round >= MAX_ROUNDS
        self._advance_and_produce(final)
        self._market_phase()
        self._action_phase()
        self.market.end_round()

    def play(self):
        for _ in range(MAX_ROUNDS):
            self.step()
        return self.result()

    def snapshot(self):
        """Compact per-round state, for cross-engine parity checks."""
        def pl(p):
            return [round(p.tokens, 4), p.credits, p.power_capacity,
                    len(p.dcs), [r for r in BUILD_RESOURCES for _ in [0] if p.inv[r]]
                    and {r: p.inv[r] for r in BUILD_RESOURCES if p.inv[r]} or {}]
        return {
            "round": self.round,
            "players": [pl(self.players[0]), pl(self.players[1])],
            "reserve": {r: self.market.reserve[r] for r in RESOURCES},
        }

    def play_trace(self):
        trace = []
        for _ in range(MAX_ROUNDS):
            self.step()
            trace.append(self.snapshot())
        return {"trace": trace, "result": self.result()}

    def result(self):
        a, b = self.players
        if abs(a.tokens - b.tokens) < 1e-9:
            winner = "draw" if abs(a.last_output - b.last_output) < 1e-9 \
                else (0 if a.last_output > b.last_output else 1)
        else:
            winner = 0 if a.tokens > b.tokens else 1
        return {
            "winner": winner,
            "tokens": [round(a.tokens, 1), round(b.tokens, 1)],
            "final_rate": [round(a.last_output, 1), round(b.last_output, 1)],
            "dcs": [[d.tier for d in a.dcs], [d.tier for d in b.dcs]],
            "power": [a.power_capacity, b.power_capacity],
            "reserve_left": {r: self.market.reserve[r] for r in PREMIUM},
        }


# ------------------------------------------------------------------ AI
class HeuristicAI:
    """One tunable heuristic policy; archetypes are just different params.

    params:
      tiers        : preferred build tiers, most-wanted first
      power_buffer : extra power capacity to keep beyond committed draw
      refresh_at   : refresh an online DC once its obso factor drops below this
      corner       : if >0, also buys premium GPU/HBM to deny when cheap
      price_ceil   : won't pay more than price_ceil * base_floor for a resource
      credit_floor : keep at least this many credits in reserve when buying
      rng          : random.Random for tie-breaks / variety (optional)
    """
    def __init__(self, tiers=("pod", "rack"), power_buffer=4, refresh_at=0.72,
                 corner=0.0, price_ceil=3.0, credit_floor=4, save_threshold=0.5,
                 epsilon=0.0, rng=None):
        self.tiers = list(tiers)
        self.power_buffer = power_buffer
        self.refresh_at = refresh_at
        self.corner = corner
        self.price_ceil = price_ceil
        self.credit_floor = credit_floor
        self.save_threshold = save_threshold  # don't fritter on lower tiers past this
        self.epsilon = epsilon                # exploration, for game-to-game variety
        self.rng = rng

    def _basket_progress(self, p, tier):
        """Fraction of a tier's resource basket we already hold (min over inputs)."""
        t = TIERS[tier]
        fracs = [min(1.0, p.inv[r] / t[r]) for r in BUILD_RESOURCES if t[r] > 0]
        return min(fracs) if fracs else 1.0

    def _target_tier(self, game, me):
        """Buy toward the top-preference tier; accumulation may span rounds."""
        return self.tiers[0]

    def market_choice(self, game, me):
        p = game.players[me]
        m = game.market
        if p.credits <= self.credit_floor:
            return None
        # exploration: occasionally grab a random affordable premium unit, so
        # self-play games diverge instead of mirroring
        if self.rng and self.epsilon and self.rng.random() < self.epsilon:
            opts = [r for r in PREMIUM if m.available(r)
                    and m.cost_of(r) <= p.credits - self.credit_floor]
            if opts:
                return self.rng.choice(opts)
        tier = self._target_tier(game, me)
        t = TIERS[tier]

        # 1) power: cover what's online/building now, and pre-secure the next
        #    build's draw only once its basket is nearly assembled (else a big
        #    campus target makes us buy idle power for many rounds)
        planned_draw = p.committed_draw()
        if self._basket_progress(p, tier) >= 0.6:
            planned_draw += t["draw"]
        if (p.power_capacity < planned_draw + self.power_buffer
                and m.available("PWR")
                and m.cost_of("PWR") <= p.credits - self.credit_floor
                and m.price("PWR") <= BASE_FLOOR["PWR"] * self.price_ceil):
            return "PWR"

        # 2) buy toward a *stockpile* of the target tier — how many copies we
        #    can comfortably afford — so a cash-rich player actually expands
        #    instead of sitting on idle credits
        all_in = (t["credits"] + sum(t[r] * BASE_FLOOR[r] for r in BUILD_RESOURCES)
                  + t["draw"] * BASE_FLOOR["PWR"])
        stock = max(1, min(4, int(p.credits / (all_in + 5))))
        want = {r: t[r] * stock for r in BUILD_RESOURCES}
        order = ["NET", "GPU", "HBM", "CPU", "SSD"]
        shortfalls = [r for r in order if p.inv[r] < want[r] and m.available(r)]
        if self.rng:
            # small chance to reorder for game-to-game variety
            if self.rng.random() < 0.15:
                self.rng.shuffle(shortfalls)
        for r in shortfalls:
            if (m.cost_of(r) <= p.credits - self.credit_floor
                    and m.price(r) <= BASE_FLOOR[r] * self.price_ceil):
                return r

        # 3) market-maker cornering: snap up cheap premium to deny the opponent
        if self.corner > 0:
            for r in ("GPU", "HBM"):
                if (m.available(r) and m.reserve[r] < INIT_RESERVE[r] * 0.6
                        and m.cost_of(r) <= p.credits - self.credit_floor
                        and m.price(r) <= BASE_FLOOR[r] * (1 + self.corner)):
                    return r
        return None

    def action_choice(self, game, me):
        p = game.players[me]

        def worst_refresh(threshold):
            cand = [(i, d) for i, d in enumerate(p.dcs)
                    if d.online and obso_factor(d.age) < threshold
                    and p.can_afford_refresh(d)]
            cand.sort(key=lambda x: TIERS[x[1].tier]["output"], reverse=True)
            return ("refresh", cand[0][0]) if cand else None

        # 1) protect big investments: refresh a *severely* decayed DC first
        sev = worst_refresh(0.5)
        if sev:
            return sev
        # 2) expand: build the most-preferred affordable tier, unless we're
        #    close to affording a more-preferred one (then keep saving)
        affordable = [t for t in self.tiers if p.can_afford_build(t)]
        top = self.tiers[0]
        if affordable and not (affordable[0] != top
                               and self._basket_progress(p, top) >= self.save_threshold):
            return ("start", affordable[0])
        # 3) otherwise top up mildly-decayed DCs
        return worst_refresh(self.refresh_at)
