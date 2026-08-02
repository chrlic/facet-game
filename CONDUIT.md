# CONDUIT — design doc (prototype stage)

A two-player systems-strategy game whose beating heart is the **max-flow / min-cut theorem**.
Fiber-backhaul theme. You build a capacitated link network from your point-of-presence to shared
internet exchanges; each tick the game routes the **maximum flow** you can deliver and pays you for the
throughput. Your delivered bandwidth **equals your network's minimum cut**, so the whole game is:
*widen my own bottleneck, and find & sever the opponent's.*

Same family as BACKBONE / HYPERSCALE (hex board, corner sources, a contested centre, build + interdict,
cumulative revenue), but a genuinely new core: **flow through a network you build, capped by min-cut,
attacked at the bottleneck.** Kept lean — no parts market — so it sits toward the elegant/abstract end.

---

## Why hex CELLS (degree 6), not honeycomb vertices (degree 3)

Nodes are hex **cells** (6 neighbours); links are built on the **edges between adjacent cells** and carry
a capacity. This matters: a degree-3 node (honeycomb vertex) can never pass two independent paths through
itself — flow conservation with 3 incident edges forces a single-edge bottleneck at *every* junction, so
min-cuts would be trivially narrow everywhere and redundancy would be impossible. Degree 6 lets a transit
cell carry up to three edge-disjoint paths, so the **fat-trunk vs. redundant-mesh** decision — the core of
the game — actually exists. (Degree 4 is the minimum viable; 6 is comfortably rich.)

---

## Components

- **Board:** a hexagonal region of hex cells (prototype radius 3 = 37 cells; shippable ~5 = 91).
  180°-rotationally symmetric so neither side has a geometric edge.
- **PoP (source):** each player owns one, in opposite corners.
- **Exchanges (sinks):** a handful of cells with a **demand** (units of bandwidth they'll buy) and a
  **price** (revenue per delivered unit). Placed symmetrically; the highest-demand exchanges sit central
  and contested — the "fight for the centre."
- **Links (fiber):** built on an edge between two adjacent cells, with an integer **capacity** (1,
  upgradeable to 2, 3…). Capacity = how much bandwidth the link carries; drawn as thickness. Each player
  has their **own** links (you can't route through the opponent's fiber), but links **occupy the physical
  edge**, so building blocks the opponent from using that edge — spatial denial layered on the flow math.

---

## A turn (alternating)

1. **Revenue posts:** last tick's delivered throughput pays out (see Contention & scoring). Income =
   a small base + a fraction of your delivered throughput → getting online early **compounds**, like
   HYPERSCALE's cumulative tokens.
2. **Up to 3 actions**, each one of:
   - **Lay fiber** — build a capacity-1 link on an empty edge adjacent to your network. *(cost $B)*
   - **Upgrade** — +1 capacity on one of your links. *(cost $U, rising per tier)*
   - **Interdict** — throttle an opponent link that is **adjacent to your network** (you must push into
     their space to attack). Drops that link's capacity by 1 for a few ticks, then it self-heals.
     *(cost $I, once per turn)*
3. **Flow resolves** (below), throughput is recorded, day advances.

Game length: fixed number of ticks (prototype 24). Highest **cumulative revenue** wins.

---

## The flow model (the core)

Each tick, for each player independently:

1. **Reach to each exchange.** Compute max-flow from your PoP to exchange *s* alone (single sink,
   uncapped) → `f(s)`. This is how hard you can push bandwidth at *s* — your "reach strength."
2. **Contention split.** Each exchange *s* with demand `D_s` splits its demand between the players in
   proportion to reach: you win `D_s · f_you(s) / (f_you(s) + f_opp(s))` (integer, remainder to the
   stronger). Out-build the opponent's capacity to an exchange and you take the larger share; ignore it
   and they take it all. *(This is the competition — no shared fiber, just shared demand.)*
3. **Delivered throughput.** Build the flow graph super-source → your PoP → your links (capacities) →
   each exchange → super-sink (cap = your contended share `D_s^you`), and compute **max-flow**. That is
   your delivered bandwidth this tick. Note it is automatically capped by your network's own **min-cut**,
   so overbuilding reach you can't actually carry earns nothing — and a single throttle at your min-cut
   can collapse it.

Revenue = Σ over exchanges of (delivered units · price).

**Why this is deep and legible.** Your whole position reduces to one question — *where is my min-cut?* —
and it's the same question inverted for offense: *where is theirs?* The max-flow value literally equals the
min-cut, so the game teaches the theorem by being played.

---

## The signature UI (for the eventual build)

Live, on the board:
- **Your own min-cut as a glowing "danger line"** — the exact links that, if cut, drop your throughput.
  You defend by making that line ≥ 2 links wide (redundancy), so no single interdiction kills you.
- When you pick up the **interdict** tool, glow the **opponent's** min-cut — the cheapest place to hurt
  them. Attacking anywhere else is wasted tempo.
- Animated flow along links; thickness = capacity; contested exchanges show the split.

This is the CONDUIT equivalent of FACET's tile-watermarks / HYPERSCALE's power donuts: **the board teaches
you the math.**

---

## Strategy (the three tensions, all one theorem)

1. **Widen your min-cut.** Delivery is capped by your narrowest cut. One fat trunk (cap 3) is cheapest per
   unit but dies to a single well-placed throttle; two cap-2 paths cost more and deliver less per dollar
   but survive a cut. **Redundancy vs. efficiency.**
2. **Reach vs. safety.** Central exchanges are high-demand but short-run and interdictable; far exchanges
   are safe but costly to reach and lower value. Where you commit capacity is the positional game.
3. **Attack the bottleneck.** The only interdiction worth an action is on the opponent's current min-cut
   edge; they respond with redundancy, so it's a moving target (the network-interdiction problem, live).

---

## AI (a selling point vs. HEXA-GO)

No neural net needed. Max-flow is polynomial, so the AI **evaluates positions exactly** (compute both
players' delivered throughput) and scores every candidate action by its marginal effect on
`myThroughput − oppThroughput` — including finding the opponent's min-cut for interdiction directly from the
residual graph. A shallow greedy/1-ply search already plays a principled game; a small alpha-beta on top is
plenty. Honest, fast, and unbeatable at its own math.

---

## Balance knobs

Board radius; number/placement/demand/price of exchanges; link cost `$B`, upgrade curve `$U`, interdict
cost `$I` and throttle depth/duration; base income vs. revenue-share; action budget per turn; game length.
Symmetric board keeps first/second-mover fair (tune second-mover income if needed). Everything is
self-play testable with the max-flow AI (see `conduit_engine.py`).

---

## Prototype findings (`conduit_engine.py`, max-flow AI self-play)

Ran on the small board (radius 3 = 37 cells, degree 6, 5 exchanges, 20 ticks) with a principled
greedy max-flow AI (evaluates every move by its real effect on delivered `mine − theirs`, plus a small
path-progress shaping term so it lays fiber before any flow exists). Results:

- **The core is computable and non-degenerate.** Throughput grows organically (≈1 → 3 units/tick as
  networks build), games are **decisive but close** (≈25% victory margin — not a coin flip, not a
  blowout), and end-state min-cuts land at **2–3 wide** — i.e. players really are building redundancy,
  so the fat-trunk-vs-mesh choice is live rather than everyone pinned to fragile 1-cuts. The degree-6
  board is doing its job.
- **There is a structural *second-mover (reaction) advantage*** — first-mover win-rate ≈ **0.28**. And
  critically, **handing the first mover extra starting credit made it *worse* (≈0.15)**: resources don't
  fix it. Committing first and visibly lets the reactor contest exactly your exchanges (contention split)
  and interdict your freshly-built min-cut. This is real design signal, not noise.
  → **Fix is structural, not economic — and validated in-sim.** Switching to **simultaneous turns** (both
  submit moves against the same pre-tick state, resolve together, first decider wins any contested edge)
  moves the first-mover win-rate **0.28 → 0.40** — most of the gap closed by removing the reaction channel,
  exactly as predicted. A small first-mover *tempo* bonus (an extra action on turn 1) would close the rest.
  So the intended production rule is **simultaneous turns**, and it's a clean, testable knob.

## Open questions to settle in prototyping

- Is proportional contention the right sink-split, or winner-take-a-fixed-share? (Prototype uses
  proportional-by-reach — computable and legible.)
- Interdict as capacity-throttle (chosen) vs. hard cut? Throttle keeps it a tempo weapon, not a knockout
  (BACKBONE lesson).
- Does the spatial-blocking layer add enough, or is separate-networks + shared-demand already rich? (Sim
  will tell — if blocking is doing nothing, drop it and keep it purely economic.)
- Right board size so min-cuts are usually 2–3 wide (interesting) rather than 1 (fragile) or huge (no
  interdiction pressure).
