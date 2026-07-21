// Duel two players and report player-A win-rate (last line = decimal). Each player is either a net
// weights file (net-PUCT, rollout leaf) or "MC" (the RAVE-flat engine at a time budget).
// Usage: node net/duel.js <A|MC> <B|MC> <games> <sims> <board> <size> [mcBudgetMs]
const fs = require("fs");
const GO = require("../docs/hexago_engine.js");
const NET = require("../docs/hexago_net.js");

const A = process.argv[2], B = process.argv[3];
const games = +(process.argv[4] || 20), sims = +(process.argv[5] || 50);
const board = process.argv[6] || "tri", size = process.argv[7] || "m", mcBudget = +(process.argv[8] || 200);
GO.setBoard(board, size);

function mover(tag) {
  if (tag === "MC") return (s) => GO.aiMove(s, mcBudget);
  const W = JSON.parse(fs.readFileSync(tag, "utf8"));
  return (s) => { NET.setWeights(W); return NET.netPuct(s, 0, { sims: sims, rollout: true }); };
}
const fa = mover(A), fb = mover(B);
let aw = 0, seq = "", marginSum = 0;
for (let g = 0; g < games; g++) {
  const aBlack = g % 2 === 0; let s = GO.initial(), mv = 0;
  while (mv < 3 * GO.board().size) { const black = s.turn === 1; const m = (black === aBlack) ? fa(s) : fb(s); s = m.pass ? GO.pass(s) : GO.play(s, m.id); if (GO.status(s).over) break; mv++; }
  const fin = GO.scoreArea(s, 160); const aWon = (fin.winner === "black") === aBlack; if (aWon) aw++; seq += aWon ? "A" : "b";
  marginSum += aBlack ? fin.margin : -fin.margin;   // score margin from A's perspective (+ = A ahead)
}
const avgM = marginSum / games;
process.stderr.write(`A(${A}) vs B(${B}): ${aw}/${games}  ${seq}  avgMargin ${avgM >= 0 ? "+" : ""}${avgM.toFixed(1)}\n`);
console.log((aw / games).toFixed(3));
