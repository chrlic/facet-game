// Phase-B self-play: BOTH sides play net-PUCT (net priors + rollout leaf value) with root noise +
// temperature sampling for diversity. Records (state, root visit distribution pi, outcome z). Runnable
// in parallel (each process appends to its own file). Usage:
//   node net/selfplay.js <weights> <nGames> <sims> <outFile> [board] [size] [tempMoves]
const fs = require("fs");
const GO = require("../docs/hexago_engine.js");
const NET = require("../docs/hexago_net.js");

const wfile = process.argv[2] || "docs/hexago-weights.json";
const nGames = +(process.argv[3] || 20);
const sims = +(process.argv[4] || 60);
const outFile = process.argv[5] || "net/sp.jsonl";
// argv[6] = board list "tri/m,tri/s,elong/s" (rotated per game) OR just "tri" with argv[7]=size (legacy)
const boardsArg = process.argv[6] || "tri/m";
const boards = boardsArg.includes("/")
  ? boardsArg.split(",").map(b => b.split("/"))
  : [[boardsArg, process.argv[7] || "m"]];
const tempMoves = +(process.argv[8] || 18);
NET.setWeights(JSON.parse(fs.readFileSync(wfile, "utf8")));

function sample(dist, temp) {           // sample id ∝ visits^(1/temp)
  let tot = 0; const w = dist.map(([, n]) => { const x = Math.pow(n, 1 / temp); tot += x; return x; });
  let r = Math.random() * tot, acc = 0;
  for (let i = 0; i < dist.length; i++) { acc += w[i]; if (r <= acc) return dist[i][0]; }
  return dist[dist.length - 1][0];
}

let totalPos = 0;
for (let g = 0; g < nGames; g++) {
  const [bt, bsz] = boards[g % boards.length];          // rotate boards (multi-board self-play)
  GO.setBoard(bt, bsz);
  const NP = GO.board().size, maxM = 3 * NP, bkey = bt + "/" + bsz;
  let s = GO.initial(); const recs = []; let mv = 0;
  while (mv < maxM) {
    const m = NET.netPuct(s, 0, { sims: sims, rollout: true, noise: 0.25, k: 24 });
    if (m.pass || !m.dist || !m.dist.length) { s = GO.pass(s); if (GO.status(s).over) break; mv++; continue; }
    recs.push({ c: Array.from(s.color).join(""), turn: s.turn, ko: s.ko, pi: m.dist });
    const id = mv < tempMoves ? sample(m.dist, 1.0) : m.id;
    s = GO.play(s, id);
    if (GO.status(s).over) break;
    mv++;
  }
  const w = GO.scoreArea(s, 160).winner;
  let buf = "";
  for (const r of recs) { const z = w === "draw" ? 0 : (((w === "black" ? 1 : 2) === r.turn) ? 1 : -1); buf += JSON.stringify({ c: r.c, turn: r.turn, ko: r.ko, pi: r.pi, z, board: bkey }) + "\n"; }
  fs.appendFileSync(outFile, buf);
  totalPos += recs.length;
  process.stderr.write(`[${outFile}] game ${g + 1}/${nGames} ${bkey} moves ${mv} winner ${w} +${recs.length} (tot ${totalPos})\n`);
}
process.stderr.write(`DONE ${outFile}: ${totalPos} positions\n`);
