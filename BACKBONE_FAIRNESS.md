# BACKBONE — Fairness Analysis & Recommended Rule Changes

AI-vs-AI simulation study of `Backbone_Rulebook.md` as written, plus rule
variants. Engine: `backbone_engine.py` (all variants are constructor knobs;
defaults implement the rulebook). Harness: `sim_backbone.py`, 60 games per
variant, 150 for the final candidates. "P1 ratio" = share of decisive games
won by Player 1; a fair game sits near 0.50.

## Headline findings

### 1. The board is not symmetric (analytical, verified)

The rulebook mirrors the cities "through the center", but the mirror used is
offset-coordinate point reflection — **not a valid hex-grid transformation**.
City-distance profiles from each start corner:

    P1: [4, 4, 6, 6, 7, 9, 9]
    P2: [3, 4, 5, 6, 7, 8, 9]     ← strictly closer to almost every city

Fix: rotate through the true 180° hex rotation about (4,4). Moving just two
cities restores exact symmetry (identical profiles `[4,4,6,6,7,8,9]`):

    (5,7) → (4,7)        (3,7) → (2,7)

### 2. The game as written does not end ("hack-lock")

A hack costs 2 BW and denies ~1–2 VP for a full round; income is 6–10 BW.
Two hacks per turn therefore suppress VP faster than the victim can rebuild
— permanently. In self-play, **100% of games** hit the cap in a mutual
hack-war (~87% of all actions are hacks) with both players stuck at 8–10 VP.
12 VP is effectively unreachable under competent opposition.

None of the "obvious" fixes help on their own:

| Variant | Stalemate rate | Note |
|---|---|---|
| rulebook as written | 100% | 87% of actions are hacks |
| P2 bonus 0 / +2 / +4 BW | 100% | compensation changes nothing at all |
| recover before scoring | 100% | timing tweak insufficient |
| hack cost 3 BW | 100% | still affordable forever |
| "Aggressive" variant alone | 100% | fewer hacks, same deadlock |
| **target 10 VP** | **8%** | games end in ~33 turns |

Target VP is the master dial: at 10, building beats hacking (hack share
drops to ~23%) and games finish in the rulebook's advertised 30–45 minutes.

### 3. With a reachable target, first-mover tempo dominates

At 10 VP the advantage flips to P1 (72–80%): whoever crosses the line first
wins, and P1 moves — and scores — first. The +2 BW setup bonus does not
cover this. The clean fix is a **final equalizing turn**: if P1 reaches the
target, P2 gets one last turn; higher VP wins, ties go to more connected
cities, then a draw.

## Recommended rules ("Backbone v1.1")

1. **Cities:** (1,4), (7,4), (3,1), (5,1), (4,4), **(4,7), (2,7)**
   (true mirror symmetry)
2. **Target: 10 VP** (12 is unreachable under interaction)
3. **Final turn:** when Player 1 ends a turn at 10+ VP, Player 2 takes one
   last turn; compare VP, then connected cities, else draw
4. **Hacks: 1 BW, at most one per turn** (the rulebook's own "Aggressive"
   variant, promoted to the default)
5. **Keep** Player 2's +2 BW setup bonus

Validated over 150 games: **P1 ratio 0.451 (CI 0.371–0.533) — statistically
fair. Zero stalemates, average 22 turns, hacking 16% of actions, ~5% draws**
(final-turn ties). Every metric healthy.

## Caveats, honestly stated

- **Adjudication artifact:** in fully-stalled games the action cap always
  lands at the start of P1's turn, when P1's pieces are still disabled but
  P2's have recovered. The lopsided win *splits* of 100%-stall configs are
  therefore tainted; their *stall rates* are the real verdict.
- **AI-mediated anomaly:** removing P2's +2 BW under the final rules made P2
  *stronger* (0.215 vs 0.451) — directionally impossible as a pure resource
  effect. The extra bandwidth appears to bait this AI's P2 into premature
  datacenter buys. Treat "+2 BW keeps it fair" as validated under this AI;
  revisit with a stronger AI or human play.
- All results are self-play at ~0.12 s/action with candidate-pruned search;
  human play may differ (the FACET project's history says: expect it to).

## Rules ambiguities found while implementing (worth an errata)

1. **Recover timing:** the turn table says recover (step 3) before scoring
   (step 4), but the worked example has the victim losing the city point —
   which requires scoring while still disabled. Implemented per the example.
2. **Reroute to the same hex** is legal by a literal reading of "a different
   legal hex"… clarified as forbidden (also crashed the JS port's naive
   apply — now fixed and tested both sides).
3. **Server next to two cities:** "choose which" needs an explicit, sticky
   choice at build time (implemented; the UI asks).
4. **Hacking the starting hex** takes the victim's whole network offline for
   a turn (rules as written). Powerful but not dominant in sims; a firewall
   on the start piece is the counter. Worth calling out in strategy tips.

## Reproduction

    python3 sim_backbone.py                 # all variants, 3 workers, resumable
    python3 sim_backbone.py final_bw2 150   # the recommended ruleset

Engine knobs: `Board(cities=SYM_CITIES, target_vp=10, final_turn=True,
hack_cost=1, hack_limit=1)` — defaults reproduce the rulebook exactly.
