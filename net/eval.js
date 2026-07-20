// Evaluate the trained net: net-PUCT vs the MC engine (equal budget), vs random, and opening quality.
// Usage: node net/eval.js [weights] [games] [budgetMs] [board] [size]
const fs = require("fs");
const GO = require("../docs/hexago_engine.js");
const NET = require("../docs/hexago_net.js");

const wfile = process.argv[2] || "docs/hexago-weights.json";
const N = +(process.argv[3] || 12);
const budget = +(process.argv[4] || 300);
const board = process.argv[5] || "tri", size = process.argv[6] || "m";
GO.setBoard(board, size);
NET.setWeights(JSON.parse(fs.readFileSync(wfile, "utf8")));
const NP = GO.board().size, BD = GO.board().bd;

function rnd(s) { const ms = []; for (let i = 0; i < NP; i++) if (s.color[i] === 0 && GO.isLegal(s, i)) ms.push(i); return ms.length ? { id: ms[(Math.random() * ms.length) | 0] } : { pass: true }; }
function netMove(s) { return NET.netPuct(s, budget); }
function mcMove(s) { return GO.aiMove(s, budget); }

function match(a, b, games) {   // a,b are move fns; a plays black on even games
  let aw = 0, seq = "";
  for (let g = 0; g < games; g++) {
    const aBlack = g % 2 === 0; let s = GO.initial(), mv = 0;
    while (mv < 400) { const black = s.turn === 1; const m = (black === aBlack) ? a(s) : b(s); s = m.pass ? GO.pass(s) : GO.play(s, m.id); if (GO.status(s).over) break; mv++; }
    const w = GO.scoreArea(s, 200).winner; const aWon = (w === "black") === aBlack; if (aWon) aw++; seq += aWon ? "A" : "b";
  }
  return { aw, games, seq };
}

// opening lines
let s = GO.initial(), lines = [];
for (let i = 0; i < 8; i++) { const m = netMove(s); if (m.pass) break; lines.push(BD[m.id] + 1); s = GO.play(s, m.id); }
console.log("net-PUCT opening lines:", lines.join(","), "(want 3-4, not 1)");
console.log("first net-PUCT sims:", netMove(GO.play(GO.initial(), 63)).sims);

const vr = match(netMove, rnd, 6);
console.log(`net-PUCT vs random: ${vr.aw}/${vr.games}  ${vr.seq}`);
const vm = match(netMove, mcMove, N);
console.log(`net-PUCT vs MC (=${budget}ms): ${vm.aw}/${vm.games}  ${vm.seq}  => ${(100 * vm.aw / vm.games).toFixed(0)}%`);
