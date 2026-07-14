# HYPERSCALE — spatial + market design (confirmed model)

*The game fuses the visible hex board with the technology market. Built on
BACKBONE's hex + network machinery. Numbers are first guesses, to be tuned by a
balance sim.*

## The chain to earn a token (confirmed with the designer)

A datacenter's **output is purely the technology installed in it, run in the
right proportions, and powered.** To make one earn you must:

1. **Claim a field** (any empty hex) — costs capital. Claimed hexes are your
   territory *and* your power-line segments.
2. **Build a power line** — a connected chain of your claimed hexes from the
   datacenter to a **power station** that still has spare capacity. No line to a
   powered station ⇒ the DC is dark.
3. **Procure technology** on the open market (GPU / HBM / compute…), whose
   **prices are visible at all times** and climb as they're bought (competition).
4. **Install it in the right proportions** — output is limited by your scarcest
   component (Liebig): mis-balancing strands hardware. *(part of the strategy)*
5. It then **produces** each turn — and you pay **operating cost every turn**:
   - **Power** — a constant cost per unit of running compute *(constant for now;
     structured so it can become a market price later)*.
   - **Manning (HR)** — a cost that **grows with the datacenter's distance from
     your city** (your start corner = your HR source). Build far from home and
     it runs, but it bleeds capital.

So the map is a tug-of-war: **HR pulls you toward your corner**, **power pulls
you toward the shared mid-board stations**, and the **market + proportions** are
the economic layer on top.

## Board

- **9×9 hex** (odd-r, BACKBONE geometry), two players.
- **Cities (HR)** — each player's start corner: `(0,0)` P0, `(8,8)` P1.
- **Two Power Stations** — neutral, mid-board and 180°-symmetric at `(4,3)` and
  `(4,5)`, each **8 power capacity**, shared: whoever runs a line to one draws
  from it until it's full.
- Everything else is open, claimable land.

## Economy & numbers (v0.1, to tune)

| Thing | Value |
|---|---|
| Start capital | 12 · income **+4/turn** + revenue |
| **Claim a field** | 1 capital (also a power-line hex) |
| **Build datacenter** (empty) | 4 capital, on a claimed hex |
| **Build power station** | 8 capital, on a claimed hex, +8 capacity |
| **Tech market** | GPU, HBM, CPU · base price 3 / 3 / 1 · price climbs as the finite reserve depletes (`× (1 + 1.5·depletion)`) |
| **Install** | buy 1 unit of a resource at market price and slot it into a chosen DC |
| **Output** | balanced compute = `min(GPU/2, HBM/1, CPU/1)` → 1 token/turn each; draws 1 power each |
| **Opex/turn** | power `= output × 1` + manning `= output × dist_to_city × 0.25` |
| **Revenue/turn** | `output × 3` capital (so a nearby DC profits; a distant one may not) |

Score = **cumulative AI tokens over 24 turns**; most wins.

## Turn structure

Each turn a player: collects income, pays opex, produces (adds output to score),
then takes **3 actions** — *claim / build DC / install tech / build station*.
Installing (a market buy) is an action, so hardware, land and power all compete
for the same turn budget.

## Legibility (the point)

The board shows the two cities, the two shared stations (with capacity used /
free), each player's claimed territory and power lines, and every datacenter's
state — installed tech, output, powered vs dark, and its per-turn opex — plus a
persistent market panel with live GPU/HBM/CPU prices and the AI's moves.

## Build plan (staged)

1. `hyperscale_spatial_engine.py` — rebuild for this model (claims, lines, tech,
   install/proportions, power stations, opex, produce). *(this stage)*
2. Heuristic AI + a balance sanity sim.
3. `docs/hyperscale.html` — rebuild the board + a persistent market panel.
4. JS port + parity, then server/PvP.
