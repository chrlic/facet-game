// Phase-A data generation: self-play with the MC AI (the "teacher"), recording each position, the
// root visit distribution (policy target pi), and the eventual game outcome (value target z, from the
// side-to-move's POV). Output = JSONL, one position per line. Usage:
//   node net/gen_data.js <nGames> <budgetMs> <outFile> [board] [size]
const fs = require("fs");
const GO = require("../docs/hexago_engine.js");

const nGames = +(process.argv[2] || 40);
const budget = +(process.argv[3] || 80);
const outFile = process.argv[4] || "net/data.jsonl";
const board = process.argv[5] || "tri";
const size = process.argv[6] || "m";
GO.setBoard(board, size);

const out = fs.createWriteStream(outFile);
let totalPos = 0;
for (let g = 0; g < nGames; g++) {
  let s = GO.initial();
  const recs = [];
  let mv = 0;
  while (mv < 400) {
    const m = GO.aiMove(s, budget, { visits: true });
    if (!m.pass && m.dist && m.dist.length) {
      recs.push({ c: Array.from(s.color).join(""), turn: s.turn, ko: s.ko, pi: m.dist });
    }
    s = m.pass ? GO.pass(s) : GO.play(s, m.id);
    if (GO.status(s).over) break;
    mv++;
  }
  const fin = GO.scoreArea(s, 200);
  const w = fin.winner; // black / white / draw
  for (const r of recs) {
    const z = w === "draw" ? 0 : (((w === "black" ? 1 : 2) === r.turn) ? 1 : -1);
    out.write(JSON.stringify({ c: r.c, turn: r.turn, ko: r.ko, pi: r.pi, z }) + "\n");
  }
  totalPos += recs.length;
  process.stderr.write(`game ${g + 1}/${nGames}  moves ${mv}  winner ${w}  +${recs.length} pos (total ${totalPos})\n`);
}
out.end(() => process.stderr.write(`DONE: ${totalPos} positions -> ${outFile}\n`));
