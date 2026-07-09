# BACKBONE

*A network-building strategy game for 2 players • Ages 10+ • roughly 30 minutes*

> **Ruleset v1.1.** This is the current, played ruleset — matching the live
> implementation (`backbone_engine.py`) and the illustrated `BACKBONE_GUIDE.pdf`.
> It supersedes the original tabletop draft, which is preserved at the end of
> this document (*Appendix: Original Draft (v1.0)*) along with the reasoning
> and simulation data behind every change (`BACKBONE_FAIRNESS.md`).

---

## Objective

You are a rival network operator. Expand your infrastructure across the hex map, bring **Datacenters** online, and connect **Cities** to your network. The first player to end a turn with **10 AI tokens** or more triggers the endgame — see *Winning the Game* below.

## Components

| Item | Quantity |
|---|---|
| Hex board (9 × 9) | 1 |
| Router tokens | 14 per player |
| Switch tokens | 8 per player |
| Wireless AP tokens | 5 per player |
| Firewall tokens | 6 per player |
| Server tokens | 6 per player |
| Datacenter tokens | 4 per player |
| Bandwidth (BW) chips | ~40 |
| AI tokens (score markers) | ~24 |
| City markers (neutral) | 7 |
| "Disabled" markers | 6 |

*Prototype tip:* print the board layout (see below), use coins or colored beads as tokens, and dried beans as Bandwidth chips.

## Setup

1. Place the board with the 7 **Cities** on their marked hexes (see the board layout at the end). Cities are neutral and never move — the layout is a true 180° rotation, so both start corners are exactly the same distance from every City.
2. Player 1 places 1 **Router** and 1 **Server** on their starting corner hex and the hex next to it. Player 2 does the same in the opposite corner.
3. Player 1 takes **3 BW**; Player 2 takes **5 BW** (the extra 2 BW offsets going second).
4. Player 1 begins.

## Key Concepts

**Your network:** all of your pieces that form one connected chain back to your starting hex. Adjacent means the six hexes touching a hex. A Wireless AP counts as adjacent to pieces on the far side of the single hex it jumps.

**Territory:** every hex occupied by one of your pieces is your territory. Two pieces can never share a hex, and you cannot build on cities or enemy pieces.

**Connected city:** a City is connected to you while one of your **Servers** sits on a hex adjacent to it and that Server is part of your network. A City can be served by both players at once — competition is allowed!

**Online Datacenter:** a Datacenter is *online* while it is adjacent to at least 2 of your Routers and connected (through your network) to at least 1 of your Servers. If a hack breaks either condition, it is offline until repaired.

## Turn Structure

On your turn, do these steps in order:

| Step | What happens |
|---|---|
| 1. Income | Take **3 BW** + **1 BW per City** you are connected to. Hand limit: 10 BW. |
| 2. Actions | Take **any 2 actions** (same action twice is allowed): **Build**, **Hack**, or **Reroute**. |
| 3. Recover | Remove Disabled markers from your pieces that were hacked on your opponent's last turn. |
| 4. Score | Count your AI tokens. Reaching **10 or more** here can end the game — see *Winning the Game*. |

## The Three Actions

### Build

Pay the cost and place one piece from your supply on an empty hex adjacent to your network (Firewalls are placed on top of an existing piece instead). New pieces must keep your network connected.

### Hack

Pay **1 BW** — you may Hack **at most once per turn** — and choose an enemy piece adjacent to your network. If it has a Firewall, the Firewall is discarded (and returns to its owner's supply) and the piece is safe. Otherwise place a Disabled marker on it: until it recovers, it does not connect, serve, or score — **and any of the victim's pieces only reachable through it fall out of the network too.** Hacks never destroy pieces or remove territory.

### Reroute

Move one of your **Switches** or **Wireless APs** to a different legal hex, free of charge. Your network must remain fully connected (at least as large as before) after the move.

## Infrastructure Pieces

| Piece | Cost | What it does |
|---|---|---|
| Router | 2 BW | The backbone. Extends your network into a new hex and claims it as territory. Datacenters need adjacent Routers to go online. |
| Switch | 1 BW | Cheap glue. Links up to 3 adjacent friendly pieces. May only be placed adjacent to **2 or more** of your pieces — it fills gaps, it does not expand. |
| Wireless AP | 3 BW | Jumps your connection over exactly 1 hex — empty *or* enemy-occupied. The jumped hex is not your territory; the AP's hex is. |
| Firewall | 2 BW | Placed on top of one of your pieces. Blocks the next Hack against that piece, then is discarded. A piece holds only 1 Firewall at a time. |
| Server | 3 BW | Serves 1 adjacent City (choose which if next to several). Also satisfies the Server requirement for Datacenters connected to it. |
| Datacenter | 6 BW | Your engine of victory. Online while adjacent to 2+ of your Routers and connected to 1+ of your Servers. |

## Scoring (checked at the end of your turn)

| Source | AI tokens |
|---|---|
| Each of your **online** Datacenters | 1 |
| Each City connected to your network | 1 |
| Two or more of your Datacenters connected to each other through your network (bonus, once) | 2 |

## Winning the Game

The moment you end a turn with **10 AI tokens or more**, your opponent gets exactly **one more full turn** before the game is scored — a fair chance to catch up or overtake, since the player who reaches the target first would otherwise win almost automatically. Afterward: whoever holds more AI tokens wins; a tie goes to whoever has more connected Cities; still tied is a draw.

(If *you* are the second player to reach the target on that closing exchange, the game ends immediately — both sides have already had the same number of turns, so no extra turn is needed.)

If both players are stuck with no productive action for a full round (four consecutive Passes), the game ends the same way: most AI tokens, then more connected Cities, then a draw.

## Example Turn

*Ana is connected to 2 Cities, so she collects 3 + 2 = 5 BW. Action 1: she builds a Router (2 BW) toward the center City. Action 2: she hacks (1 BW) Ben's Server next to that City — he has no Firewall on it, so it is Disabled and Ben loses that City's AI token and income until his next turn ends. Ana ends her turn with 2 BW saved and holds: 2 online Datacenters + 2 Cities = 4 AI tokens so far.*

## Strategy Tips

- Routers grab ground fast but stretch you thin — a long, unprotected spine is easy to hack at the joints. Switches and Wireless APs make dense, efficient cores but concede territory.
- Firewall the pieces whose loss hurts most: the Server feeding a Datacenter, or the single link holding two halves of your network together — not whatever's simply nearest the front line.
- An unbuilt Datacenter is not a Datacenter. It needs 2 Routers and a networked Server before it earns anything — don't count AI tokens you don't have yet.
- The 2-token link bonus is often the sprint that ends the game — plan your network's shape around getting two Datacenters into the same component, not just building them wherever there's room.
- Hacking is limited to once per turn — cheap, but not spam. A well-timed single Hack that severs a bridge is worth far more than denying one piece's income.

## Board Layout

A 9 × 9 hex grid. City positions are a true 180° rotation through the center hex, so both players face identical distances to every City. Using (column, row) coordinates from the bottom-left:

- **P1 start:** (0, 0) — bottom-left corner
- **P2 start:** (8, 8) — top-right corner
- **Cities (C):** (1, 4), (7, 4), (3, 1), (4, 7), (5, 1), (2, 7), and (4, 4) — the center hex

```
Row 8:   . . . . . . . . P2
Row 7:    . . C . C . . . .
Row 6:   . . . . . . . . .
Row 5:    . . . . . . . . .
Row 4:   . C . . C . . C .
Row 3:    . . . . . . . . .
Row 2:   . . . . . . . . .
Row 1:    . . . C . C . . .
Row 0:   P1 . . . . . . . .
```

*(Odd rows are offset half a hex to the right, as on a standard pointy-top hex grid.)*

## Variants

- **Longer game:** play to 16 AI tokens and raise the hand limit to 12 BW.
- **Original draft (v1.0):** play the rules exactly as first printed — see the Appendix below. Not recommended for competitive play; kept for historical/comparison interest.

---

## Appendix: Original Draft (v1.0)

This is the rulebook exactly as first written, before simulation testing.
`backbone_engine.py` can still reproduce it exactly: `Board(cities=CITIES,
target_vp=12, hack_cost=2, hack_limit=None, final_turn=False)`. It differs
from the current rules (above) in four ways:

1. **City layout:** the original city positions — (5,7) and (3,7) instead of
   today's (4,7) and (2,7) — were mirrored using offset-coordinate
   reflection, which is *not* a valid transformation on a hex grid. Player 2
   ends up measurably closer to most Cities than Player 1.
2. **Target: 12 AI tokens** instead of 10.
3. **Hacks cost 2 BW with no per-turn limit** (today's 1 BW / once-per-turn
   was originally an optional "Aggressive" variant).
4. **No final turn:** the game ends the instant either player reaches the
   target, with no equalizing turn for the other side.

**Why it changed:** AI-vs-AI simulation (`BACKBONE_FAIRNESS.md`) found the
original rules produced a geometrically unfair board and a game that
essentially never ends between competent players — unlimited 2-BW Hacks
suppress scoring faster than it can be rebuilt, so 100% of simulated games
ended in stalemate with ~87% of all actions spent hacking, adjudicated by
raw token count rather than actually won. The current v1.1 rules were
validated over 150 simulated games: Player 1 wins 45.1% of decisive games
(a fair result), zero stalemates, ~22 turns per game, hacking at a healthy
~16% of actions — close to the "30–45 minutes" originally advertised.

Player 2 keeps the same **+2 BW** setup bonus in both versions — it was
tested with and without under v1.1, and games stayed measurably more even
with it in place.

*(Internally, both `backbone_engine.py` and `docs/backbone_engine.js` still
call this scoring metric "VP" / `target_vp` in code — that's a code-level
name only; the game itself now presents this as "AI tokens" everywhere a
player sees it.)*
