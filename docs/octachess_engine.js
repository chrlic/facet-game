// OCTACHESS — chess on an octagon+gate (diamond) board.
//
// Board model: 64 octagons in an 8x8 rook grid, plus 49 "gates" (diamonds) sitting
// at every interior vertex — one between each 2x2 block of octagons. Every diagonal
// in the game runs octagon -> gate -> octagon, so the gates are the diagonal cells.
//
// Combined lattice trick (the whole engine rests on this):
//   octagon (r,c)  r,c in 0..7  ->  (x=2c,   y=2r  )   [even,even]
//   gate    (r,c)  r,c in 0..6  ->  (x=2c+1, y=2r+1)   [odd, odd ]
// On this lattice:
//   rook   = slide by (0,+-2)/(+-2,0)         (octagon -> octagon, never touches gates)
//   bishop = slide by (+-1,+-1)               (auto-alternates gate/octagon)
//   knight = leap  (+-4,+-2)/(+-2,+-4)        (octagon -> octagon, ignores gates)
//   king   = one step of any of the above 8   (8 nbrs on an octagon, only 4 on a gate)
//   queen  = rook + bishop, but "heavy": may pass through empty gates yet not stop on one
//   pawn   = forward octagon push; captures into a forward gate; from a gate steps
//            forward-diagonally onto an octagon.
// Only light pieces (K,Q?...) — heavy = rook & queen — may not REST on a gate, so they
// can't cement gates shut.  (Queen may traverse an empty gate but not end there.)
(function (global) {
  "use strict";

  var N = 8, G = 7;
  var HEAVY = { R: true, Q: true };
  var VAL = { P: 100, N: 330, B: 320, R: 500, Q: 900, K: 20000, W: 300 };

  // ---- coordinate helpers -------------------------------------------------
  function keyAt(x, y) {                 // lattice -> cell key, or null if no cell
    if (x < 0 || y < 0) return null;
    var ex = x & 1, ey = y & 1;
    if (ex === 0 && ey === 0) { var c = x >> 1, r = y >> 1; return (c < N && r < N) ? "o:" + r + ":" + c : null; }
    if (ex === 1 && ey === 1) { var gc = (x - 1) >> 1, gr = (y - 1) >> 1; return (gc < G && gr < G) ? "g:" + gr + ":" + gc : null; }
    return null;                          // (odd,even)/(even,odd) are square edges, not cells
  }
  function xyOf(k) {
    var p = k.split(":"), r = +p[1], c = +p[2];
    return p[0] === "o" ? [2 * c, 2 * r] : [2 * c + 1, 2 * r + 1];
  }
  function isGate(k) { return k.charCodeAt(0) === 103; } // 'g'
  function okCell(t, r, c) { return t + ":" + r + ":" + c; }

  // Algebraic-ish label for display / logs: octagons a1..h8, gates like "a1/b2".
  function label(k) {
    var p = k.split(":"), r = +p[1], c = +p[2];
    var files = "abcdefgh";
    if (p[0] === "o") return files[c] + (8 - r);
    // gate between octagons (r,c),(r,c+1),(r+1,c),(r+1,c+1) -> name by its lower-left octagon corner
    return "♢" + files[c] + (8 - r);
  }

  // ---- board / state ------------------------------------------------------
  // piece = { t:'K|Q|R|B|N|P', s:0|1 }   side 0 = White (bottom, moves up: y decreasing)
  function cloneBoard(b) { var o = {}; for (var k in b) o[k] = b[k]; return o; }
  function cloneState(s) {
    return {
      board: cloneBoard(s.board), turn: s.turn,
      castle: { 0: { k: s.castle[0].k, q: s.castle[0].q }, 1: { k: s.castle[1].k, q: s.castle[1].q } },
      half: s.half, full: s.full
    };
  }

  // opts.warden (default false): swap each side's queenside knight for a gate-only Warden
  // that starts on a home gate. Passed through from the UI's "Warden" toggle.
  function initial(opts) {
    var warden = opts && opts.warden;
    var b = {};
    var back = ["R", "N", "B", "Q", "K", "B", "N", "R"];
    for (var c = 0; c < 8; c++) {
      b[okCell("o", 0, c)] = { t: back[c], s: 1 };  // black back rank (top)
      b[okCell("o", 1, c)] = { t: "P", s: 1 };
      b[okCell("o", 6, c)] = { t: "P", s: 0 };
      b[okCell("o", 7, c)] = { t: back[c], s: 0 };  // white back rank (bottom)
    }
    if (warden) {
      delete b[okCell("o", 7, 1)];                  // remove white b1 knight
      delete b[okCell("o", 0, 6)];                  // remove black g8 knight (point-symmetric)
      b[okCell("g", 6, 1)] = { t: "W", s: 0 };      // white Warden on a home gate
      b[okCell("g", 0, 5)] = { t: "W", s: 1 };      // black Warden (symmetric)
    }
    return { board: b, turn: 0, castle: { 0: { k: true, q: true }, 1: { k: true, q: true } }, half: 0, full: 1 };
  }

  // ---- pseudo-legal move generation --------------------------------------
  function slide(board, x, y, dx, dy, side, allowGate, out) {
    var nx = x + dx, ny = y + dy;
    while (true) {
      var k = keyAt(nx, ny);
      if (!k) break;
      var occ = board[k], gate = isGate(k);
      if (occ) {
        if (occ.s !== side && !(gate && !allowGate)) out.push({ to: k, cap: true });
        break;                             // any piece blocks further travel
      }
      if (allowGate || !gate) out.push({ to: k, cap: false }); // empty gate: heavy passes, doesn't stop
      nx += dx; ny += dy;
    }
  }

  var DIAG = [[1, 1], [1, -1], [-1, 1], [-1, -1]];
  var ORTH = [[2, 0], [-2, 0], [0, 2], [0, -2]];
  var KNIGHT = [[4, 2], [4, -2], [-4, 2], [-4, -2], [2, 4], [2, -4], [-2, 4], [-2, -4]];
  // Warden: gate-only. Steps to an orthogonally-adjacent gate on the 7x7 gate grid (±2 on the
  // lattice; gates are never adjacent, so it leaps the intervening octagon/edge). Immune to
  // rooks & queens (they can't land on gates). 4-directional keeps it ~fair vs the knight it
  // replaces (self-play: 8-dir was too strong at 79%, this is ~63%).
  var WARDEN = [[2, 0], [-2, 0], [0, 2], [0, -2]];

  // Generate pseudo-legal moves for one piece at key k. If attacksOnly, produce only
  // the squares the piece *attacks* (used for check detection); pawns then yield their
  // diagonal capture squares regardless of occupancy, and castling is never generated.
  function pieceMoves(state, k, attacksOnly, out) {
    var board = state.board, p = board[k], side = p.s;
    var xy = xyOf(k), x = xy[0], y = xy[1], i, d, nx, ny, nk, occ;
    switch (p.t) {
      case "R":
        for (i = 0; i < 4; i++) slide(board, x, y, ORTH[i][0], ORTH[i][1], side, false, out);
        break;
      case "B":
        for (i = 0; i < 4; i++) slide(board, x, y, DIAG[i][0], DIAG[i][1], side, true, out);
        break;
      case "Q":
        for (i = 0; i < 4; i++) slide(board, x, y, ORTH[i][0], ORTH[i][1], side, false, out);
        for (i = 0; i < 4; i++) slide(board, x, y, DIAG[i][0], DIAG[i][1], side, false, out); // heavy: no gate landing
        break;
      case "N":
        for (i = 0; i < 8; i++) {
          nk = keyAt(x + KNIGHT[i][0], y + KNIGHT[i][1]); if (!nk) continue;
          occ = board[nk]; if (!occ) out.push({ to: nk, cap: false }); else if (occ.s !== side) out.push({ to: nk, cap: true });
        }
        break;
      case "W":                            // Warden — steps to an adjacent gate (gate-only)
        for (i = 0; i < WARDEN.length; i++) {
          nk = keyAt(x + WARDEN[i][0], y + WARDEN[i][1]); if (!nk) continue; // always a gate
          occ = board[nk]; if (!occ) out.push({ to: nk, cap: false }); else if (occ.s !== side) out.push({ to: nk, cap: true });
        }
        break;
      case "K":
        if (isGate(k)) {
          // on a gate: only the 4 diagonal octagons (the "coffin" — few escapes)
          for (i = 0; i < 4; i++) {
            nk = keyAt(x + DIAG[i][0], y + DIAG[i][1]); if (!nk) continue;
            occ = board[nk]; if (!occ) out.push({ to: nk, cap: false }); else if (occ.s !== side) out.push({ to: nk, cap: true });
          }
        } else {
          // on an octagon: 4 orthogonal octagons ...
          for (i = 0; i < 4; i++) {
            nk = keyAt(x + ORTH[i][0], y + ORTH[i][1]); if (!nk) continue;
            occ = board[nk]; if (!occ) out.push({ to: nk, cap: false }); else if (occ.s !== side) out.push({ to: nk, cap: true });
          }
          // ... plus, on each diagonal, the adjacent gate AND the octagon across an empty gate
          for (i = 0; i < 4; i++) {
            var gk = keyAt(x + DIAG[i][0], y + DIAG[i][1]); if (!gk) continue;
            var gocc = board[gk];
            if (!gocc) out.push({ to: gk, cap: false }); else if (gocc.s !== side) out.push({ to: gk, cap: true });
            if (!gocc) {                       // gate empty -> king may step across to the diagonal octagon
              var dk = keyAt(x + 2 * DIAG[i][0], y + 2 * DIAG[i][1]); if (!dk) continue;
              occ = board[dk]; if (!occ) out.push({ to: dk, cap: false }); else if (occ.s !== side) out.push({ to: dk, cap: true });
            }
          }
        }
        break;
      case "P":
        var dir = side === 0 ? -1 : 1;     // white moves up (y decreasing)
        var onGate = isGate(k);
        if (onGate) {
          // step forward-diagonally onto an octagon: move if empty, capture if enemy
          for (d = -1; d <= 1; d += 2) {
            nk = keyAt(x + d, y + dir); if (!nk) continue;
            occ = board[nk];
            if (attacksOnly) { out.push({ to: nk, cap: !!occ }); continue; }
            if (!occ) out.push({ to: nk, cap: false });
            else if (occ.s !== side) out.push({ to: nk, cap: true });
          }
        } else {
          // Diagonal capture runs octagon -> gate -> octagon (the board's diagonal).
          // The pawn attacks (and can capture) the adjacent forward GATE; if that gate is
          // empty, the attack passes through it to the diagonally-forward OCTACHESS. This lets
          // pawns capture into a gate outpost AND defend/attack each other across octagons
          // (pawn chains), so they are as strong as chess pawns.
          for (d = -1; d <= 1; d += 2) {
            nk = keyAt(x + d, y + dir); if (!nk) continue;   // the forward gate
            occ = board[nk];
            var farK = keyAt(x + 2 * d, y + 2 * dir);         // the diagonally-forward octagon
            if (attacksOnly) {
              out.push({ to: nk, cap: !!occ });               // always attacks the gate
              if (!occ && farK) out.push({ to: farK, cap: true }); // and the octagon beyond an empty gate
              continue;
            }
            if (occ) { if (occ.s !== side) out.push({ to: nk, cap: true }); } // capture piece in the gate
            else if (farK) {                                  // empty gate: reach the far octagon
              var farOcc = board[farK];
              if (farOcc && farOcc.s !== side) out.push({ to: farK, cap: true });
            }
          }
          if (!attacksOnly) {
            // straight push one octagon
            nk = keyAt(x, y + 2 * dir);
            if (nk && !board[nk]) {
              out.push({ to: nk, cap: false });
              // double push from home rank
              var homeR = side === 0 ? 6 : 1;
              if ((y >> 1) === homeR) { var nk2 = keyAt(x, y + 4 * dir); if (nk2 && !board[nk2]) out.push({ to: nk2, cap: false }); }
            }
          }
        }
        break;
    }
  }

  function attackedBy(state, targetKey, bySide) {
    var board = state.board, buf = [];
    for (var k in board) {
      if (board[k].s !== bySide) continue;
      buf.length = 0; pieceMoves(state, k, true, buf);
      for (var i = 0; i < buf.length; i++) if (buf[i].to === targetKey) return true;
    }
    return false;
  }
  function kingKey(state, side) {
    for (var k in state.board) { var p = state.board[k]; if (p.t === "K" && p.s === side) return k; }
    return null;
  }
  function inCheck(state, side) { var kk = kingKey(state, side); return kk ? attackedBy(state, kk, side ^ 1) : false; }

  // Apply a move onto a *fresh* state (does not mutate the input).
  function applyMove(state, m) {
    var s = cloneState(state), b = s.board, side = state.turn, p = b[m.from];
    var cap = b[m.to];
    delete b[m.from];
    var np = { t: m.promo || p.t, s: side };
    b[m.to] = np;
    if (m.castle) {                        // move the rook too
      var rr = side === 0 ? 7 : 0;
      if (m.castle === "k") { b[okCell("o", rr, 5)] = b[okCell("o", rr, 7)]; delete b[okCell("o", rr, 7)]; }
      else { b[okCell("o", rr, 3)] = b[okCell("o", rr, 0)]; delete b[okCell("o", rr, 0)]; }
    }
    // castling rights
    if (p.t === "K") { s.castle[side].k = false; s.castle[side].q = false; }
    if (p.t === "R") {
      var hr = side === 0 ? 7 : 0;
      if (m.from === okCell("o", hr, 0)) s.castle[side].q = false;
      if (m.from === okCell("o", hr, 7)) s.castle[side].k = false;
    }
    var er = side === 0 ? 0 : 7;           // capturing a rook on its home corner kills that right
    if (m.to === okCell("o", er, 0)) s.castle[side ^ 1].q = false;
    if (m.to === okCell("o", er, 7)) s.castle[side ^ 1].k = false;

    s.half = (p.t === "P" || cap) ? 0 : s.half + 1;
    if (side === 1) s.full++;
    s.turn = side ^ 1;
    return s;
  }

  function castlingMoves(state, side, out) {
    if (inCheck(state, side)) return;
    var hr = side === 0 ? 7 : 0, b = state.board, kFrom = okCell("o", hr, 4);
    if (!b[kFrom] || b[kFrom].t !== "K") return;
    var enemy = side ^ 1;
    // kingside: c5,c6 empty; king passes e->f->g
    if (state.castle[side].k && b[okCell("o", hr, 7)] && b[okCell("o", hr, 7)].t === "R" &&
      !b[okCell("o", hr, 5)] && !b[okCell("o", hr, 6)] &&
      !attackedBy(state, okCell("o", hr, 5), enemy) && !attackedBy(state, okCell("o", hr, 6), enemy)) {
      out.push({ from: kFrom, to: okCell("o", hr, 6), cap: false, castle: "k" });
    }
    // queenside: c1,c2,c3 empty; king passes e->d->c
    if (state.castle[side].q && b[okCell("o", hr, 0)] && b[okCell("o", hr, 0)].t === "R" &&
      !b[okCell("o", hr, 1)] && !b[okCell("o", hr, 2)] && !b[okCell("o", hr, 3)] &&
      !attackedBy(state, okCell("o", hr, 3), enemy) && !attackedBy(state, okCell("o", hr, 2), enemy)) {
      out.push({ from: kFrom, to: okCell("o", hr, 2), cap: false, castle: "q" });
    }
  }

  // Full legal move list for the side to move.
  function legalMoves(state) {
    var side = state.turn, board = state.board, res = [], buf = [];
    for (var k in board) {
      if (board[k].s !== side) continue;
      buf.length = 0; pieceMoves(state, k, false, buf);
      var pt = board[k].t;
      for (var i = 0; i < buf.length; i++) {
        var mv = { from: k, to: buf[i].to, cap: buf[i].cap, piece: pt };
        // promotion: pawn reaching the far octagon rank
        if (pt === "P" && !isGate(buf[i].to)) {
          var rr = +buf[i].to.split(":")[1];
          if ((side === 0 && rr === 0) || (side === 1 && rr === 7)) {
            var promos = ["Q", "R", "B", "N"];
            for (var pi = 0; pi < 4; pi++) {
              var pm = { from: k, to: buf[i].to, cap: buf[i].cap, piece: pt, promo: promos[pi] };
              if (!inCheck(applyMove(state, pm), side)) res.push(pm);
            }
            continue;
          }
        }
        if (!inCheck(applyMove(state, mv), side)) res.push(mv);
      }
    }
    castlingMoves(state, side, res);       // castling squares already checked for attacks
    // (castling king-destination safety verified above; also ensure not landing in check)
    return res.filter(function (m) { return !m.castle || !inCheck(applyMove(state, m), side); });
  }

  function status(state) {
    var moves = legalMoves(state), chk = inCheck(state, state.turn);
    if (moves.length === 0) {
      if (chk) return { over: true, result: state.turn === 0 ? "black" : "white", reason: "checkmate", check: true };
      return { over: true, result: "draw", reason: "stalemate", check: false };
    }
    if (state.half >= 100) return { over: true, result: "draw", reason: "50-move", check: chk };
    if (insufficient(state.board)) return { over: true, result: "draw", reason: "insufficient", check: chk };
    return { over: false, result: null, reason: null, check: chk };
  }
  function insufficient(b) {
    var pieces = [];
    for (var k in b) if (b[k].t !== "K") pieces.push(b[k].t);
    if (pieces.length === 0) return true;
    if (pieces.length === 1 && (pieces[0] === "N" || pieces[0] === "B")) return true;
    return false;
  }

  // ---- evaluation & AI ----------------------------------------------------
  // centrality of a lattice point 0..1 (1 = dead centre of the 8x8 octagon field)
  function central(x, y) {
    var cx = 7, cy = 7; // centre of lattice (octagons span 0..14)
    return 1 - (Math.abs(x - cx) + Math.abs(y - cy)) / 14;
  }
  function evaluate(state) {
    var b = state.board, sc = 0;
    for (var k in b) {
      var p = b[k], xy = xyOf(k), sgn = p.s === 0 ? 1 : -1, v = VAL[p.t], bonus = 0;
      var ce = central(xy[0], xy[1]);
      if (p.t === "N" || p.t === "B") bonus += 14 * ce;
      if (p.t === "P") {
        var adv = p.s === 0 ? (14 - xy[1]) : xy[1]; // how far advanced (lattice units)
        bonus += adv * 1.2 + 6 * ce;
        if (isGate(k)) bonus += 10;            // pawn outpost in a gate blocks two diagonals
      }
      if (isGate(k) && (p.t === "N" || p.t === "B")) bonus += 12 * ce; // light piece holds a gate
      if (p.t === "W") bonus += 16 * ce + 4;      // Warden: reward central gate control
      if (p.t === "K" && isGate(k)) bonus -= 18;  // king in a gate has only 4 escapes
      sc += sgn * (v + bonus);
    }
    return sc; // white-positive
  }

  function orderMoves(state, moves) {
    var b = state.board;
    for (var i = 0; i < moves.length; i++) {
      var m = moves[i], sc = 0;
      if (m.cap) { var victim = b[m.to]; sc = 1000 + (victim ? VAL[victim.t] : 0) - VAL[m.piece] / 10; }
      if (m.promo) sc += 800;
      m._o = sc;
    }
    moves.sort(function (a, c) { return c._o - a._o; });
    return moves;
  }

  function quiesce(state, alpha, beta, side) {
    var stand = evaluate(state) * (side === 0 ? 1 : -1);
    if (stand >= beta) return beta;
    if (stand > alpha) alpha = stand;
    var moves = legalMoves(state);
    orderMoves(state, moves);
    for (var i = 0; i < moves.length; i++) {
      if (!moves[i].cap && !moves[i].promo) continue;
      var sc = -quiesce(applyMove(state, moves[i]), -beta, -alpha, side ^ 1);
      if (sc >= beta) return beta;
      if (sc > alpha) alpha = sc;
    }
    return alpha;
  }

  function negamax(state, depth, alpha, beta, side, deadline) {
    if (Date.now() > deadline) return { score: evaluate(state) * (side === 0 ? 1 : -1), timeout: true };
    var moves = legalMoves(state);
    if (moves.length === 0) {
      if (inCheck(state, side)) return { score: -100000 - depth }; // prefer slower mates against us / faster for us
      return { score: 0 };
    }
    if (depth === 0) return { score: quiesce(state, alpha, beta, side) };
    orderMoves(state, moves);
    var best = -Infinity, bestMove = moves[0];
    for (var i = 0; i < moves.length; i++) {
      var r = negamax(applyMove(state, moves[i]), depth - 1, -beta, -alpha, side ^ 1, deadline);
      var sc = -r.score;
      if (sc > best) { best = sc; bestMove = moves[i]; }
      if (best > alpha) alpha = best;
      if (alpha >= beta) break;
    }
    return { score: best, move: bestMove };
  }

  // difficulty: 'easy'|'normal'|'hard'
  function aiMove(state, difficulty, timeMs) {
    var maxDepth = difficulty === "easy" ? 2 : difficulty === "hard" ? 5 : 3;
    var budget = timeMs || (difficulty === "hard" ? 2500 : difficulty === "normal" ? 1200 : 400);
    var deadline = Date.now() + budget, side = state.turn, bestMove = null, bestScore = 0;
    var top = legalMoves(state);
    if (top.length === 0) return null;
    if (difficulty === "easy") {
      // easy: shallow search but pick randomly among near-best to feel less machine-like
      var r0 = negamax(state, maxDepth, -Infinity, Infinity, side, deadline);
      return r0.move || top[0];
    }
    for (var d = 1; d <= maxDepth; d++) {
      var r = negamax(state, d, -Infinity, Infinity, side, deadline);
      if (Date.now() > deadline) break;   // iteration didn't finish: keep the last completed depth's move
      if (r.move) { bestMove = r.move; bestScore = r.score; }
    }
    return bestMove || top[0];
  }

  // ---- public API ---------------------------------------------------------
  var OCTACHESS = {
    N: N, G: G,
    initial: initial, cloneState: cloneState,
    legalMoves: legalMoves, applyMove: applyMove, status: status,
    inCheck: inCheck, kingKey: kingKey, attackedBy: attackedBy,
    evaluate: evaluate, aiMove: aiMove,
    keyAt: keyAt, xyOf: xyOf, isGate: isGate, cell: okCell, label: label,
    VAL: VAL
  };
  if (typeof module !== "undefined" && module.exports) module.exports = OCTACHESS;
  global.OCTACHESS = OCTACHESS;
})(typeof self !== "undefined" ? self : this);
