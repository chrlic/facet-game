# HYPERSCALE

*A two-player economic strategy game about racing to build AI compute during a
finite boom — where the real fight is over the supply chain, not the buildings.*

> **Status: design draft v0.1.** Numbers below are the *initial* parameters the
> prototype engine implements; they are expected to move once the AI-vs-AI
> balance simulation (`sim_hyperscale.py`) reports win rates and degeneracy —
> exactly as BACKBONE was tuned (see `BACKBONE_FAIRNESS.md`).

---

## 1. The pitch

You are a hyperscaler. Over ~14 rounds (the "boom era") you buy scarce hardware
on a shared open market, assemble it into datacenters of increasing size, keep
them **powered** and **current**, and produce **AI tokens**. The most tokens
produced over the whole game wins. There is no dice — all scarcity emerges from
the two players' choices, so it is a game of reading demand, timing, and denial.

## 2. The two load-bearing rules

Everything else is tuning. These two rules are what make it strategic rather
than a "biggest pile wins" euro:

1. **Power is a hard cap, not a cost.** Compute only produces if you can power
   it. Power capacity is a separate, chunky investment that lags how fast you
   can buy GPUs — so **owning compute you can't turn on** (stranded capacity) is
   a real, painful, and *inflictable* position. Realized output =
   `min(what you built, what you can power)`.

2. **The market fights your balance.** Every datacenter needs a full basket of
   inputs (GPU + memory + network + …). Your opponent wants the same scarce
   pieces, and buying more of anything in one round drives its price up. So you
   are never accumulating a pile — you are assembling a *balanced basket under
   live competition*, and denying your opponent theirs.

## 3. Resources

Six resources, in two tiers. This split decides where the conflict happens.

| Resource | Symbol | Tier | Role |
|---|---|---|---|
| GPU | `GPU` | premium | the compute that produces tokens |
| HBM memory | `HBM` | premium | feeds the GPUs (real-world bottleneck) |
| Network fabric | `NET` | premium | interconnect — makes *scale* pay off |
| Power capacity | `PWR` | premium | the hard cap; permanent standing capacity |
| CPU | `CPU` | commodity | orchestration; cheap, plentiful |
| SSD | `SSD` | commodity | storage; cheap, plentiful |

- **GPU / HBM / CPU / SSD / NET** are *consumed* into a datacenter when you build
  or refresh it — they become part of the building.
- **PWR** is different: units you buy become **permanent power capacity** that
  never depletes. Running datacenters *draw* power against your capacity.

Late-game bidding wars naturally concentrate on the four premium resources,
which keeps the endgame readable.

## 4. The market (deterministic)

Each resource `r` has a base floor price, a lifetime **reserve** (the finite
frontier), and within-round **demand pressure**.

```
depletion[r] = 1 − reserve[r] / initial_reserve[r]          # 0 → 1 as it's mined out
floor[r]     = base_floor[r] × (1 + FRONTIER_K × depletion[r])   # frontier creep
price(r)     = floor[r] × (1 + PRICE_K × bought_this_round[r])    # cornering cost
```

- **Buy one unit** of `r`: costs `round(price(r))` credits; requires
  `reserve[r] > 0`. Then `reserve[r] −= 1`, `bought_this_round[r] += 1`.
  (Buying `PWR` adds to your power capacity instead of your inventory.)
- **Within a round**, each successive unit of the same resource costs more
  (`PRICE_K`) — so cornering to deny your opponent is *possible but self-limiting*.
- **Between rounds**, `bought_this_round` resets to 0 (prices relax), but
  `floor[r]` has crept up permanently as the reserve depleted (frontier tightens).
- **Reserve hits 0** → that resource is gone. Shortage. No one can buy it at any
  price. This is the endgame's teeth.

**Market phase:** players **alternate buying single units** (seeing prices move
live, draft-style) until both pass. This is where the reads and denial happen.

**Initial market parameters**

| `r` | base_floor | initial_reserve |
|---|---|---|
| GPU | 3 | 95 |
| HBM | 3 | 70 |
| NET | 4 | 42 |
| PWR | 4 | 80 |
| CPU | 1 | 300 |
| SSD | 1 | 300 |

`FRONTIER_K = 1.5` · `PRICE_K = 0.15` *(reserves tuned down from the first
draft so the premium frontier actually reaches ~60–70% consumed by the end —
see §14)*

## 5. Datacenters — sizes, and why scale is rewarded but gated

Built from fixed recipes (you must supply the whole basket). Bigger tiers give
**super-linear output per GPU** (economies of scale / interconnect) but demand
disproportionately more **NET** and **PWR** — the two hardest resources — so the
temptation to scale channels you straight into the contested part of the market.

*(numbers below are the sim-tuned v0.1 values — see §14)*

| Tier | GPU | HBM | CPU | SSD | NET | Credits | Power draw | Build time | Output/rd | Revenue/rd | Out/GPU |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **Rack** (S) | 2 | 1 | 1 | 1 | 0 | 4 | 2 | 1 rd | 2.4 | 1 | 1.20 |
| **Pod** (M) | 6 | 4 | 2 | 2 | 2 | 10 | 6 | 2 rd | 9 | 4 | 1.50 |
| **Campus** (L) | 14 | 10 | 4 | 4 | 6 | 24 | 14 | 2 rd | 38 | 13 | 2.71 |

- **Build:** pay the credits + resources from inventory up front. The DC is under
  construction for `build_time` rounds (producing nothing), then comes **online**.
- **Rack** is cheap, fast, resilient, and touches the contested market barely
  (no NET). **Campus** is a dominant engine *if it lands and you can power it*,
  ruinous if you can't.

## 6. Power & activation

At the start of each round, after construction advances:

- Sum the **power draw** of all online datacenters. If it exceeds your
  **power capacity**, datacenters are shut off (lowest output-per-power first)
  until you're within capacity. Shut-off DCs produce **nothing** that round.
- You choose to run the rest. This is the binding-constraint rule in practice:
  you can build a Campus, but a Campus you can't power is 24 tokens/round of dead
  weight — and power capacity is slow to grow, so you must plan it *ahead*.

## 7. Obsolescence — the anti-coasting treadmill

Hardware ages. Each online datacenter has an **age** = rounds since it came
online or was last refreshed.

```
output_this_round = base_output[tier] × OBSOLESCENCE ^ age        # OBSOLESCENCE = 0.90
```

A fresh DC (age 0) runs at 100%; left alone it decays ~10%/round (halves in ~7
rounds). **Refresh** (an action) resets a DC's age to 0 for a fraction of its
recipe:

```
refresh cost = ⌈0.5 × recipe resources⌉ + ⌈0.5 × recipe credits⌉
```

You cannot bank a lead as idle score — you must keep re-buying hardware to keep
the factory running. This is what prevents the rich-get-richer fizzle.

## 8. Round structure

1. **Advance & activate.** Construction progresses; finished DCs come online.
   Resolve power (§6). Increment each online DC's age.
2. **Produce.** Each *running* DC adds `output` to your **AI-token score** and
   `revenue` to your credits (both scaled by obsolescence).
3. **Income.** Each player collects **base income** (32 credits).
4. **Market phase.** Alternate single buys until both pass (§4). **Who buys
   first alternates each round**, so neither player keeps a structural
   buy-first edge on scarce resources (this fully neutralised first-mover
   advantage in sim — §14).
5. **Build/Refresh phase.** Alternate actions until both pass: *start* a
   Rack/Pod/Campus, *refresh* a DC, or pass. (Buying PWR happens in the market
   phase.)

Starting position: **45 credits, power capacity 4, no datacenters.** P2 gets a
small **+2 credit** opening nudge. Game length: **16 rounds.**

## 9. The endgame — a three-act arc

Because obsolescence forbids coasting and the reserve tightens over time, the
game has a natural shape:

1. **Buildout (rds ~1–6):** resources cheap; race to get output flowing;
   tempo and compounding revenue matter most.
2. **The Crunch (rds ~7–12):** both players scale toward Pods/Campuses; premium
   prices spike and reserves visibly shrink. This is where games are won —
   cornering GPU/HBM/NET, forcing stranded capacity, timing the big builds.
3. **Consolidation (rds ~13–16):** the frontier dries up and early hardware is
   depreciating. You live off what you built and can still afford to refresh.
   The balanced, well-powered, disciplined operator beats the over-extended one.

**Crucially, scarcity bites the leader hardest** — a bigger operation needs more
of the tightening premium resources just to *maintain* itself, so the leader's
refreshes compete with the leader's growth. This is a natural rubber-band that
keeps the trailing player in contention without any artificial catch-up.

**Ending & scoring.** Fixed 16 rounds (or when all four premium reserves are
exhausted). **Score = total AI tokens produced over the whole game** — literally
output-over-time. Tiebreak: **final-round output rate** (strongest engine still
running when the music stops).

## 10. Why it stays engaging — the strategy archetypes

No line should dominate; the simulation exists to verify this. Intended viable
strategies:

- **Swarm / tempo** — many Racks, output early, resilient, barely touches the
  contested market. Diversified and hard to disrupt, but caps out low.
- **Hyperscale gambit** — hoard credits, land one or two Campuses, dominate the
  back half. Market-heavy, high-variance — catastrophic if denied NET or power
  at the wrong moment.
- **Market maker** — build modestly but *corner* GPU/HBM to strangle the
  opponent and profit from their desperation. Win by making *their* engine
  inefficient, not by building the biggest one.
- **Balanced operator** — steady, efficient, refresh-disciplined; wins the war
  of attrition in Act 3.

The interaction is entirely economic — the shared market *is* the combat, the
way BACKBONE's hack is — but sharper, because every unit your opponent buys is a
unit you can't have, at a price you watch move.

## 11. Deliberate anti-degeneracy mechanics

Lessons from the BACKBONE balance audit (self-play degenerating into a single
race; hack-lock stalemates) informed these guards up front:

- **Binding-constraint output (power cap)** makes greedy accumulation actively
  bad — you can't just buy the most stuff.
- **Rising marginal prices** make cornering self-limiting — no free denial.
- **Obsolescence treadmill** forbids build-once-and-coast.
- **Frontier tightening that scales with your own size** rubber-bands the leader.

## 12. Open questions for the simulation to answer

- Are all four archetypes within a fair win band, or does one dominate?
- Is the Campus ever worth it, or does tempo/Pod-spam strictly win? (Tune
  Campus out/GPU, NET intensity, power draw.)
- Does the game reach a satisfying Act-3 crunch, or do reserves last too long /
  run out too early? (Tune reserves, `FRONTIER_K`.)
- Is there a first-player advantage from buying first each round? (May need P2 a
  small credit bonus, as BACKBONE gives P2 +2 BW.)
- Obsolescence rate: does 0.90 make refresh compelling without being oppressive?

## 13. Fit with the project & implementation status

Ships as the **third game** on the existing server beside FACET and BACKBONE:
shared accounts, lobby, and per-game ratings (ratings are now independent per
game — see the per-game-ratings note).

**Built so far (playable offline vs AI):**
- `hyperscale_engine.py` — deterministic engine + tunable `HeuristicAI`.
- `sim_hyperscale.py` — the balance simulation (§14).
- `docs/hyperscale_engine.js` — JS port, **verified byte-for-byte identical to
  the Python engine** round-by-round over a full game (parity harness), plus a
  `HyperscaleMatch` interactive controller (alternating single buys/actions vs
  the AI) and a UI serializer.
- `docs/hyperscale.html` — a functional single-player-vs-AI UI (market with live
  climbing prices + depleting-reserve bars, your/AI operations, power &
  stranded-capacity display, obsolescence, build/refresh). Linked from the
  FACET and BACKBONE pages.

**Not yet built (the next chunk):** server integration
(`game_type='hyperscale'`, PvP — non-trivial for a multi-phase economic turn),
ratings wiring, and PWA/service-worker registration. The offline UI is the
natural first playable milestone, mirroring how BACKBONE started.

## 14. Simulation findings (v0.1)

`sim_hyperscale.py` runs an AI-vs-AI round-robin across the four archetypes
(each played by a tunable `HeuristicAI`) with exploration noise for
game-to-game variety, and reports win rates, first-mover advantage, and
"economy shape" (tier viability + how much of the frontier is consumed). Eight
tuning iterations took it from a broken first draft to a defensible balance.

**What the first draft got wrong (all caught by the sim):**
- **Economy far too starved** — players built ~2 datacenters and the frontier
  barely moved. Fixed by raising base income 8 → 32 and widening the game to 16
  rounds.
- **Rack-spam strictly dominated (81%)** and the Campus was *never built* — the
  super-linear scale bonus was too small to justify slower builds. Fixed by
  widening the output-per-GPU ladder (Rack 1.2 / Pod 1.5 / Campus 2.7) and
  making the Campus faster (build 3 → 2 rds) and less power-hungry.
- **No Act-3 crunch** — reserves lasted forever. Fixed by cutting premium
  reserves ~20–25%; the frontier now reaches **~60–70% consumed** (GPU 68%,
  HBM 60%, PWR 62%), producing real late-game scarcity.
- **Strong first-mover advantage** (up to 73% in mirrors). Fixed by
  **alternating who buys first each round** — this alone neutralised it
  (mirrors now 45–50%); a token +2 P2 credit nudge centres it.

**Current balance (100 games/matchup, both seats):**

| Archetype | Win% | Notes |
|---|---|---|
| Balanced (pod + rack) | ~60% | the strong, "correct" core line |
| Market-maker (pod + cornering) | ~52% | |
| Swarm (rack tempo) | ~50% | |
| Hyperscale (campus gambit) | ~38% | viable but highest-risk; campus built in 44% of games |

Three archetypes sit within a ~10-point band; the Campus gambit is the
weakest (a demanding, higher-variance line rather than a trap — a reasonable
place for it, tunable up with a small Campus buff).

**Key methodological caveat (borrowed straight from the BACKBONE audit):** the
win rates measure *AI competence as much as strategy strength*. One iteration's
"swarm is weak (26%)" turned out to be a dumb AI that froze at 4 racks with 355
idle credits; fixing the AI to stockpile and expand flipped swarm to *87%*
before the rack nerf brought it back to ~50%. So these numbers are provisional
until either a stronger AI or human playtesting confirms them — exactly as
BACKBONE needed its 150-game validation pass.

**Still open:** tighten the Hyperscale gap; confirm NET (only ~45% consumed) is
contested enough to matter; verify the flexible-slots "partial fill" variant
(§ future) would add depth without breaking the binding-constraint clarity.
