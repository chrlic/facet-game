// GLYPH — a competitive Sokoban duel. Two pawns shove glyph-crates around a maze onto a shared central
// ALTAR of target slots. A slot is "claimed" by whoever pushes a matching-glyph crate onto it; you can
// shove a rival's loose crate back off. Hold ALL slots at once → you win. Offline; one engine drives the
// UI (glyph.html) and a headless fairness sim (see main() / `node glyph_engine.js`).
(function (root, factory) {
  var mod = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = mod;
  root.GLYPH = mod;
})(typeof self !== "undefined" ? self : this, function () {
  var DIRS = [[0, -1], [0, 1], [-1, 0], [1, 0]];        // up, down, left, right
  function k(x, y) { return x + "," + y; }
  function ek(x, y, nx, ny) { return (x < nx || y < ny) ? x + "," + y + ":" + nx + "," + ny : nx + "," + ny + ":" + x + "," + y; }
  // Can you move from (x,y) one step in direction d? Blocked by the grid border, a filled (wall) cell, or a
  // wall-EDGE sitting on the line between the two cells (the Quoridor-style walls). Occupants checked elsewhere.
  function passable(sc, x, y, d) {
    var nx = x + DIRS[d][0], ny = y + DIRS[d][1];
    if (nx < 0 || ny < 0 || nx >= sc.W || ny >= sc.H) return false;
    if (sc.walls[k(nx, ny)]) return false;
    if (sc.edges && sc.edges[ek(x, y, nx, ny)]) return false;
    return true;
  }

  // ---- scenarios: 180°-rotationally-symmetric mazes so neither side has an edge -----------------------
  // Two wall styles: tile-thick (grid '#') OR wall-EDGES on the lines between cells (Quoridor-style, all
  // cells walkable → far more maze real estate). edgeSegs author the edge-walls as ['v',x,y] (a vertical
  // wall on the LEFT side of cell x,y, i.e. between (x-1,y) and (x,y)) or ['h',x,y] (a horizontal wall on
  // the TOP of cell x,y, between (x,y-1) and (x,y)). Each segment is auto-mirrored 180° so the maze is fair.
  function mkEdges(W, H, segs) {
    var map = {}, render = [];
    function add(ax, ay, bx, by) { var key = ek(ax, ay, bx, by); if (!map[key]) { map[key] = 1; render.push([ax, ay, bx, by]); } }
    for (var i = 0; i < segs.length; i++) {
      var t = segs[i][0], x = segs[i][1], y = segs[i][2];
      if (t === "v") { add(x - 1, y, x, y);       add(W - 1 - x, H - 1 - y, W - x, H - 1 - y); }
      else           { add(x, y - 1, x, y);       add(W - 1 - x, H - 1 - y, W - 1 - x, H - y); }
    }
    return { map: map, render: render };
  }
  // grid: '#' wall, '.' floor (also sets W,H). slots/crates: [x,y,glyph]; pawns: [[x,y],[x,y]]. glyph 0/1/2.
  function build(name, grid, slots, crates, pawns, edgeSegs, aiDepth, anyGlyph) {
    var H = grid.length, W = grid[0].length, walls = {};
    for (var y = 0; y < H; y++) for (var x = 0; x < W; x++) if (grid[y][x] === "#") walls[k(x, y)] = 1;
    var e = edgeSegs ? mkEdges(W, H, edgeSegs) : null;
    var sc = { name: name, W: W, H: H, walls: walls, edges: e ? e.map : null, edgeRender: e ? e.render : [],
      aiDepth: aiDepth || 6,        // deeper search for the tougher (expert) boards
      anyGlyph: !!anyGlyph,         // generic Sokoban: ANY box claims ANY goal (no symbol matching)
      slots: slots.map(function (s) { return { x: s[0], y: s[1], g: s[2] }; }),
      crates0: crates.map(function (c) { return { x: c[0], y: c[1], g: c[2] }; }),
      pawns0: pawns.map(function (p) { return { x: p[0], y: p[1] }; }) };
    // Per-goal box PUSH-distance: min number of pushes to bring a box from a cell to the goal, accounting
    // for the pawn needing room BEHIND the box for each push (other boxes ignored). This is the classic
    // Sokoban simple-distance gradient — it lets the AI plan MULTI-step pushes (round corners, repositioning),
    // not just one-shot claims. Backward BFS from the goal over box cells.
    function pushField(gx, gy) {
      var d = {}, q = [[gx, gy]], hd = 0; d[k(gx, gy)] = 0;
      while (hd < q.length) { var c = q[hd++], cx = c[0], cy = c[1], cd = d[k(cx, cy)];
        for (var i = 0; i < 4; i++) {
          var px = cx - DIRS[i][0], py = cy - DIRS[i][1];   // box's previous cell (a push in dir i took it to C)
          var bx = px - DIRS[i][0], by = py - DIRS[i][1];   // cell the pawn stood on to make that push
          if (px < 0 || py < 0 || px >= W || py >= H || walls[k(px, py)]) continue;
          if (bx < 0 || by < 0 || bx >= W || by >= H || walls[k(bx, by)]) continue;
          if (!passable(sc, px, py, i) || !passable(sc, bx, by, i)) continue;   // box P->C and pawn behind->P
          var pk = k(px, py); if (d[pk] != null) continue;
          d[pk] = cd + 1; q.push([px, py]);
        }
      }
      return d;
    }
    sc.pdist = sc.slots.map(function (s) { return pushField(s.x, s.y); });
    return sc;
  }

  // 180°-symmetric mirror helper for authoring: mirror of (x,y) about board centre
  function mir(W, H, x, y) { return [W - 1 - x, H - 1 - y]; }

  // All mazes 180°-rotationally symmetric (fair). They SHARE one balanced altar core (slots + crates +
  // pawn starts, all mirror pairs, crates adjacent to the altar for short AI-plannable pushes) and vary
  // only the outer WALL decoration for Sokoban character — routes, cover, chokepoints — without touching
  // the altar fight that drives balance.
  // The target pattern is 180°-symmetric (▲ ● ▲ = glyphs 0,1,0) so neither side "owns" an end slot — the
  // whole fight is symmetric and the centre slot is the true decider. Every slot has TWO adjacent matching
  // crates (one above, one below): always pushable, never pinnable in a corner, and impossible to fully
  // deadlock-deny. All crates are 180° mirror pairs.
  // Wall-EDGE mazes (primary), Sokoban-inspired (rooms / corridors / off-centre goals). Every cell walkable;
  // walls live on the lines between cells (far more maze real estate). DENSER crate field for a meatier
  // puzzle: matching crates per slot + reserve/blocker crates. Glyph-2 crates match no slot — pure blockers
  // (park one on a slot to deny it). Goals need not be central; where they ARE central the fight is hottest.
  // Everything (slots, crates, wall-edges, pawn starts) is a 180° mirror pair, so the duel stays fair.
  var _F = ["...........", "...........", "...........", "...........", "...........",
            "...........", "...........", "...........", "..........."];   // 11 x 9, all floor

  // Boxes now start SEVERAL pushes from their goals — real Sokoban manipulation, not one-shot claims.
  // Cloister — central altar; boxes two pushes out on each axis, blockers cluttering the diagonals.
  var _S = [[4, 4, 0], [5, 4, 1], [6, 4, 0]];
  var _CD = [[3, 3, 0], [7, 5, 0], [3, 5, 0], [7, 3, 0],   // ▲ goals fed by DIAGONAL boxes -> 2-push L-corners
             [5, 2, 1], [5, 6, 1],                         // ● centre fed straight (the contested slot)
             [2, 4, 2], [8, 4, 2]];                        // blockers out on the flanks
  var _P = [[1, 4], [9, 4]];

  // Twin Vaults — a ▲ goal in each side room, its box shoved in from the corner; the ● fight in the centre.
  var _VS = [[2, 4, 0], [5, 4, 1], [8, 4, 0]];
  var _VC = [[1, 3, 0], [9, 5, 0], [1, 5, 0], [9, 3, 0], [5, 2, 1], [5, 6, 1],   // vault boxes L-push in from outside
             [4, 4, 2], [6, 4, 2]];                                              // centre blockers guard the ● slot
  var _VP = [[0, 4], [10, 4]];

  // Diagonal — corner goals fed by boxes an L-push away; the centre ● still the sharpest exchange.
  var _DS = [[3, 2, 0], [5, 4, 1], [7, 6, 0]];
  var _DC = [[2, 3, 0], [8, 5, 0], [4, 3, 0], [6, 5, 0], [5, 2, 1], [5, 6, 1],   // corner goals via L-pushes through (3,3)/(7,5)
             [1, 4, 2], [9, 4, 2]];                                              // flank blockers
  var _DP = [[1, 1], [9, 7]];

  // EXPERT tier — long, multi-corner routes; the AI searches deeper (depth 8) to keep up.
  // Long Haul: end goals fed by boxes in the FAR corners -> a full 4-push L (two pushes out, two pushes in).
  var _LC = [[2, 2, 0], [8, 6, 0], [2, 6, 0], [8, 2, 0],   // 4-push L to the ▲ goals
             [5, 1, 1], [5, 7, 1],                         // ● centre: 3-push straight
             [3, 4, 2], [7, 4, 2]];
  // Chicane: a wall jog forces an S-bend — push in, around the spur, and in again (two corners).
  var _HS = [[3, 4, 0], [5, 4, 1], [7, 4, 0]];
  var _HC = [[1, 2, 0], [9, 6, 0], [1, 6, 0], [9, 2, 0],   // corner boxes routed around the spurs to (3,4)/(7,4)
             [5, 2, 1], [5, 6, 1],
             [4, 4, 2], [6, 4, 2]];
  var _HP = [[0, 4], [10, 4]];

  // Adapted from real single-player Sokoban levels: each level's walls were symmetrised (intersected with
  // its own 180° rotation) onto an 11x11 canvas, giving a fair board that keeps the source's character.
  var _KG = ["###########", "#######..##", "####.....##", "######...##", "##...#....#", "#.........#",
             "#....#...##", "##...######", "##.....####", "##..#######", "###########"];   // "Hook"
  var _KS = [[7, 2, 0], [3, 8, 0], [5, 5, 1]];
  var _KC = [[7, 4, 0], [3, 6, 0], [4, 5, 1], [6, 5, 1]];   // pockets: straight 2-push up/down; centre: 1-push in
  var _KP = [[1, 5], [9, 5]];
  var _TG = ["###########", "#.....#####", "#.....#####", "#.....#####", "#........##", "##.......##",
             "##........#", "#####.....#", "#####.....#", "#####.....#", "###########"];   // "Steps"
  var _TS = [[3, 2, 0], [7, 8, 0], [5, 5, 1]];
  var _TC = [[3, 4, 0], [7, 6, 0], [3, 5, 1], [7, 5, 1]];
  var _TP = [[1, 4], [9, 6]];

  // FAITHFUL adaptations of soko/ Sokoban levels: walls symmetrised (intersect with the 180° rotation), and
  // the source's OWN boxes & goals mirrored in — real multi-step manipulation, not planted 2-push claims.
  // These are GENERIC (any box claims any goal, no symbols) and carry the source's true goal count.
  var _5G = ["###########", "#........##", "#.........#", "#.........#", "#...#.....#", "#.........#",
             "#.....#...#", "#.........#", "#.........#", "##........#", "###########"];   // "Five" (Rincewind)
  var _5S = [[8, 1, 0], [2, 9, 0], [7, 2, 0], [3, 8, 0], [8, 2, 0], [2, 8, 0], [7, 7, 0], [3, 3, 0], [6, 8, 0], [4, 2, 0]];
  var _5C = [[5, 2, 0], [5, 8, 0], [4, 3, 0], [6, 7, 0], [2, 4, 0], [8, 6, 0], [6, 5, 0], [4, 5, 0], [4, 7, 0], [6, 3, 0]];
  var _5P = [[6, 8], [4, 2]];
  var _LVG = ["###########", "#.#..######", "#....######", "#........##", "#........##", "##...#...##",
              "##........#", "##........#", "######....#", "######..#.#", "###########"];   // "LV-01" (wds)
  var _LVS = [[2, 2, 0], [8, 8, 0], [3, 2, 0], [7, 8, 0], [8, 3, 0], [2, 7, 0], [4, 7, 0], [6, 3, 0]];
  var _LVC = [[4, 2, 0], [6, 8, 0], [3, 3, 0], [7, 7, 0], [7, 4, 0], [3, 6, 0], [8, 5, 0], [2, 5, 0]];
  var _LVP = [[6, 7], [4, 3]];
  var _UG = ["###########", "#......#..#", "#.........#", "#......#..#", "#..#......#", "#..#.#.#..#",
             "#......#..#", "#..#......#", "#.........#", "#..#......#", "###########"];   // "Untitled" (Nopphon)
  var _US = [[2, 3, 0], [8, 7, 0], [1, 4, 0], [9, 6, 0], [2, 5, 0], [8, 5, 0]];
  var _UC = [[8, 2, 0], [2, 8, 0], [8, 3, 0], [2, 7, 0], [8, 8, 0], [2, 2, 0]];
  var _UP = [[1, 9], [9, 1]];
  var _SWG = ["#############", "#############", "#..##########", "#......#...##", "#..........##", "#......##...#",
              "#...........#", "#...##......#", "##..........#", "##...#......#", "##########..#",
              "#############", "#############"];   // "Sweet" (Shaggath) 13x13
  var _SWS = [[6, 4, 0], [6, 8, 0], [8, 4, 0], [4, 8, 0], [10, 4, 0], [2, 8, 0], [2, 5, 0], [10, 7, 0], [2, 6, 0], [10, 6, 0], [2, 7, 0], [10, 5, 0]];
  var _SWC = [[5, 3, 0], [7, 9, 0], [5, 4, 0], [7, 8, 0], [9, 5, 0], [3, 7, 0], [9, 6, 0], [3, 6, 0], [8, 7, 0], [4, 5, 0], [9, 7, 0], [3, 5, 0]];
  var _SWP = [[9, 8], [3, 4]];

  var MAZES = [
    build("Cloister", _F, _S, _CD, _P, []),            // corner boxes -> every ▲ claim is an L-push
    build("Twin Vaults", _F, _VS, _VC, _VP,            // open vaults, a fenced central battleground
      [["v", 4, 3], ["v", 4, 5], ["v", 4, 4], ["h", 3, 4], ["h", 7, 4]]),
    build("Diagonal", _F, _DS, _DC, _DP,               // corner goal-rooms on a diagonal, open centre cross
      [["h", 3, 1], ["v", 5, 1], ["v", 5, 2], ["h", 7, 5]]),
    build("Hook", _KG, _KS, _KC, _KP, null, 7),        // adapted from a Sokoban level (symmetrised)
    build("Steps", _TG, _TS, _TC, _TP),                // adapted from a Sokoban level (symmetrised)
    build("Warehouse", _UG, _US, _UC, _UP, null, 7, true), // FAITHFUL generic — Nopphon's "Untitled" (6 goals)
    build("Waterfall", _LVG, _LVS, _LVC, _LVP, null, 7, true), // FAITHFUL generic — wds's "LV-01" (8 goals)
    build("Five", _5G, _5S, _5C, _5P, null, 7, true),      // FAITHFUL generic — Rincewind's "Five" (10 goals)
    build("Sweet", _SWG, _SWS, _SWC, _SWP, null, 7, true), // FAITHFUL generic — Shaggath's "Sweet" (12 goals, 13x13)
    build("Long Haul ★", _F, _S, _LC, _P, [], 7),      // EXPERT: far-corner boxes -> 4-push L maneuvers
    build("Chicane ★", _F, _HS, _HC, _HP,              // EXPERT: tight goal cluster, long 4-push L routes
      [["v", 4, 3], ["v", 4, 5]], 7)
  ];

  // ---- state -----------------------------------------------------------------------------------------
  var PASS = 4;      // a "move" that skips your turn; two passes in a row end the game

  function newGame(mazeIdx) {
    var sc = MAZES[mazeIdx % MAZES.length];
    var st = { sc: sc,
      crates: sc.crates0.map(function (c) { return { x: c.x, y: c.y, g: c.g }; }),
      pawns: sc.pawns0.map(function (p) { return { x: p.x, y: p.y }; }),
      owner: sc.slots.map(function () { return -1; }),    // who has CLAIMED each slot (permanent once set)
      passes: 0, turn: 0, moves: 0, hist: [] };           // hist = the last few board positions (repetition ban)
    st.hist.push(keyOf(st));
    return st;
  }
  function clone(s) {
    return { sc: s.sc, crates: s.crates.map(function (c) { return { x: c.x, y: c.y, g: c.g }; }),
      pawns: s.pawns.map(function (p) { return { x: p.x, y: p.y }; }), owner: s.owner.slice(),
      passes: s.passes, turn: s.turn, moves: s.moves, hist: s.hist };   // share hist by ref (read-only in search)
  }
  // a full-board fingerprint: both pawns + every crate + who owns each slot. Used for the repetition ban.
  function keyOf(s) {
    var a = s.pawns[0].x + "," + s.pawns[0].y + "/" + s.pawns[1].x + "," + s.pawns[1].y + "|";
    for (var i = 0; i < s.crates.length; i++) a += s.crates[i].x + "," + s.crates[i].y + ";";
    return a + "|" + s.owner.join(",");
  }
  var REP_WINDOW = 8;   // no move may recreate a position from the last REP_WINDOW plies (kills shuffles/oscillation)
  // record the position now on the board (called by the driver after each real move)
  function remember(s) { s.hist.push(keyOf(s)); if (s.hist.length > REP_WINDOW) s.hist.shift(); }
  function majority(s) { return (s.sc.slots.length >> 1) + 1; }   // slots needed to win (2 of 3)

  function crateAt(s, x, y) { for (var i = 0; i < s.crates.length; i++) if (s.crates[i].x === x && s.crates[i].y === y) return i; return -1; }
  function pawnAt(s, x, y) { for (var i = 0; i < 2; i++) if (s.pawns[i].x === x && s.pawns[i].y === y) return i; return -1; }
  function slotAt(s, x, y) { var sl = s.sc.slots; for (var i = 0; i < sl.length; i++) if (sl[i].x === x && sl[i].y === y) return i; return -1; }
  function blocked(s, x, y) { return x < 0 || y < 0 || x >= s.sc.W || y >= s.sc.H || s.sc.walls[k(x, y)]; }
  // a crate that has claimed a slot (sits on an owned slot it matches) is LOCKED and cannot be pushed
  // which player (if any) has this crate claiming a goal — i.e. it sits on a goal it matches, and that goal is owned
  function claimerOf(s, ci) { var c = s.crates[ci], sl = slotAt(s, c.x, c.y);
    return (sl >= 0 && s.owner[sl] >= 0 && (s.sc.anyGlyph || s.sc.slots[sl].g === c.g)) ? s.owner[sl] : -1; }
  function frozen(s, ci) { return claimerOf(s, ci) >= 0; }                              // on someone's claimed goal
  // a claimed crate is immovable to the RIVAL, but its OWNER may still shove it (which releases the claim).
  function locked(s, ci, pl) { var o = claimerOf(s, ci); return o >= 0 && o !== pl; }

  // is direction d legal for `player`? Move onto floor, or push a LINE of one-or-more unlocked crates one
  // step — legal iff every crate/edge in the line is clear and the cell beyond the last crate is empty. A
  // locked (claimed) crate or a pawn anchors the line and stops the push.
  function canMove(s, player, d) {
    var p = s.pawns[player];
    if (!passable(s.sc, p.x, p.y, d)) return false;      // wall / wall-edge / border ahead of the pawn
    var cx = p.x + DIRS[d][0], cy = p.y + DIRS[d][1];
    if (pawnAt(s, cx, cy) >= 0) return false;            // can't push a pawn
    if (crateAt(s, cx, cy) < 0) return true;             // step onto empty floor
    while (true) {                                        // walk the chain of crates
      var ci = crateAt(s, cx, cy);
      if (ci < 0) return true;                            // empty cell reached -> the whole line can shift
      if (locked(s, ci, player)) return false;           // a rival's claimed crate anchors the line (yours you may shove)
      if (!passable(s.sc, cx, cy, d)) return false;       // wall/edge/border between this crate and the next cell
      cx += DIRS[d][0]; cy += DIRS[d][1];
      if (pawnAt(s, cx, cy) >= 0) return false;           // a pawn in the line blocks it
    }
  }
  function legalMoves(s, player) { var out = []; for (var d = 0; d < 4; d++) if (canMove(s, player, d)) out.push(d); return out; }
  // would playing d reproduce a recent position (within the repetition window)? PASS never repeats.
  function repeats(s, player, d) {
    if (d === PASS || !s.hist) return false;
    var c = clone(s); apply(c, player, d); return s.hist.indexOf(keyOf(c)) >= 0;
  }
  // legal moves that also don't repeat a past position. If empty, the player can only repeat -> must PASS.
  function freshMoves(s, player) {
    var out = [], m = legalMoves(s, player);
    for (var i = 0; i < m.length; i++) if (!repeats(s, player, m[i])) out.push(m[i]);
    return out;
  }

  // apply a move (dir 0-3, or PASS=4). Pushes the whole LINE of crates ahead one step; any pushed crate that
  // lands on its matching unclaimed slot CLAIMS it permanently (locks it). returns {pushed, claimed:slot|-1, over, won}
  function apply(s, player, d) {
    var pushed = false, claimed = -1;
    if (d === PASS) { s.passes++; s.moves++; return { pushed: false, claimed: -1, over: over(s), won: winner(s) }; }
    s.passes = 0;
    var p = s.pawns[player], nx = p.x + DIRS[d][0], ny = p.y + DIRS[d][1];
    // gather the line of crates in front (canMove already guaranteed the whole shift is legal)
    var chain = [], cx = nx, cy = ny, ci;
    while ((ci = crateAt(s, cx, cy)) >= 0) { chain.push(ci); cx += DIRS[d][0]; cy += DIRS[d][1]; }
    for (var i = chain.length - 1; i >= 0; i--) {          // shift far end first so cells don't collide
      var c = s.crates[chain[i]];
      var from = slotAt(s, c.x, c.y);                       // if it was claiming a goal, shoving it RELEASES that claim
      if (from >= 0 && s.owner[from] === player && (s.sc.anyGlyph || s.sc.slots[from].g === c.g)) s.owner[from] = -1;
      c.x += DIRS[d][0]; c.y += DIRS[d][1]; pushed = true;
      var to = slotAt(s, c.x, c.y);
      if (to >= 0 && s.owner[to] < 0 && (s.sc.anyGlyph || s.sc.slots[to].g === c.g)) { s.owner[to] = player; if (claimed < 0) claimed = to; }
    }
    s.pawns[player].x = nx; s.pawns[player].y = ny;
    s.moves++;
    return { pushed: pushed, claimed: claimed, over: over(s), won: winner(s) };
  }

  function owned(s, player) { var n = 0; for (var i = 0; i < s.owner.length; i++) if (s.owner[i] === player) n++; return n; }
  function allClaimed(s) { for (var i = 0; i < s.owner.length; i++) if (s.owner[i] < 0) return false; return true; }
  function over(s) { var m = majority(s); return owned(s, 0) >= m || owned(s, 1) >= m || allClaimed(s) || s.passes >= 2; }
  // winner: first to claim a majority of slots wins. If the game is stopped short (both passed / all locked
  // with no majority), the player holding more claims wins. Returns -1 for "still going" and for a true draw.
  function winner(s) {
    var m = majority(s);
    if (owned(s, 0) >= m) return 0; if (owned(s, 1) >= m) return 1;
    if (s.passes >= 2 || allClaimed(s)) return owned(s, 0) > owned(s, 1) ? 0 : (owned(s, 1) > owned(s, 0) ? 1 : -1);
    return -1;
  }

  // ---- heuristic + alpha-beta AI ---------------------------------------------------------------------
  // Crate-aware BFS distance field from a pawn: floors are walkable, but walls, ALL crates, and the other
  // pawn are obstacles — so the AI routes AROUND crates instead of trying to walk through (push) them.
  function pawnField(s, player) {
    var p = s.pawns[player], obst = {};
    for (var i = 0; i < s.crates.length; i++) obst[k(s.crates[i].x, s.crates[i].y)] = 1;
    var o = s.pawns[1 - player]; obst[k(o.x, o.y)] = 1;
    var d = {}, q = [[p.x, p.y]], hd = 0; d[k(p.x, p.y)] = 0;
    while (hd < q.length) { var c = q[hd++], cx = c[0], cy = c[1];
      for (var j = 0; j < 4; j++) { if (!passable(s.sc, cx, cy, j)) continue;
        var nx = cx + DIRS[j][0], ny = cy + DIRS[j][1], nk = k(nx, ny);
        if (obst[nk] || d[nk] != null) continue;
        d[nk] = d[k(cx, cy)] + 1; q.push([nx, ny]); } }
    return d;
  }

  // ---- push-SOLVER: a real Sokoban planner (single box, full pawn-reachability) --------------------------
  // cells the pawn can reach from (sx,sy), respecting walls/edges and a set of blocked cells (boxes/pawn)
  function floodReach(sc, sx, sy, blocked) {
    var d = {}; d[k(sx, sy)] = 1; var q = [[sx, sy]], hd = 0;
    while (hd < q.length) { var c = q[hd++], cx = c[0], cy = c[1];
      for (var i = 0; i < 4; i++) { if (!passable(sc, cx, cy, i)) continue;
        var nx = cx + DIRS[i][0], ny = cy + DIRS[i][1], nk = k(nx, ny);
        if (blocked[nk] || d[nk]) continue; d[nk] = 1; q.push([nx, ny]); } }
    return d;
  }
  function withKey(obj, x, y) { var o = {}; for (var kk in obj) o[kk] = 1; o[k(x, y)] = 1; return o; }
  function repOf(reg) { var m = null; for (var kk in reg) if (m === null || kk < m) m = kk; return m; }
  // Plan pushing box `bi` onto (gx,gy) for `player`: BFS over (box cell, pawn-reachable region) — other boxes
  // and the rival pawn are static. Returns { pushes, from:{x,y}, dir } for the FIRST push of a shortest plan.
  function pushSolve(s, player, bi, gx, gy) {
    var sc = s.sc, obst = {};
    for (var i = 0; i < s.crates.length; i++) if (i !== bi) obst[k(s.crates[i].x, s.crates[i].y)] = 1;
    var op = s.pawns[1 - player]; obst[k(op.x, op.y)] = 1;
    var b0 = s.crates[bi], p0 = s.pawns[player];
    if (b0.x === gx && b0.y === gy) return null;                     // already there (can't "push on")
    var reg0 = floodReach(sc, p0.x, p0.y, withKey(obst, b0.x, b0.y));
    var q = [{ bx: b0.x, by: b0.y, reg: reg0, push: 0, first: null }], hd = 0, seen = {}, cap = 700;
    seen[b0.x + "," + b0.y + ":" + repOf(reg0)] = 1;
    while (hd < q.length) {
      if (hd > cap) return null;                                     // give up on very deep single-box plans
      var st = q[hd++];
      for (var d = 0; d < 4; d++) {
        var nbx = st.bx + DIRS[d][0], nby = st.by + DIRS[d][1];
        if (!passable(sc, st.bx, st.by, d) || obst[k(nbx, nby)]) continue;    // box can't advance
        var fx = st.bx - DIRS[d][0], fy = st.by - DIRS[d][1];                 // pawn must stand behind
        if (!st.reg[k(fx, fy)] || !passable(sc, fx, fy, d)) continue;         // pawn can't reach / edge closed
        var first = st.first || { from: { x: fx, y: fy }, dir: d };
        if (nbx === gx && nby === gy) return { pushes: st.push + 1, from: first.from, dir: first.dir };
        var nreg = floodReach(sc, st.bx, st.by, withKey(obst, nbx, nby));     // pawn ends on the old box cell
        var key = nbx + "," + nby + ":" + repOf(nreg);
        if (seen[key]) continue; seen[key] = 1;
        q.push({ bx: nbx, by: nby, reg: nreg, push: st.push + 1, first: first });
      }
    }
    return null;
  }
  // BFS walking-distance field from a target cell over free cells (crate-/pawn-aware) — to route the pawn in
  function distField(s, tx, ty, player) {
    var obst = {}; for (var i = 0; i < s.crates.length; i++) obst[k(s.crates[i].x, s.crates[i].y)] = 1;
    var op = s.pawns[1 - player]; obst[k(op.x, op.y)] = 1;
    var d = {}; d[k(tx, ty)] = 0; var q = [[tx, ty]], hd = 0;
    while (hd < q.length) { var c = q[hd++], cx = c[0], cy = c[1];
      for (var j = 0; j < 4; j++) { if (!passable(s.sc, cx, cy, j)) continue;
        var nx = cx + DIRS[j][0], ny = cy + DIRS[j][1], nk = k(nx, ny);
        if ((obst[nk] && !(nx === tx && ny === ty)) || d[nk] != null) continue;
        d[nk] = d[k(cx, cy)] + 1; q.push([nx, ny]); } }
    return d;
  }
  // Cheapest goal `player` can claim right now, and the single move toward it: { cost, move, gi }.
  function claimPlan(s, player) {
    var slots = s.sc.slots, any = s.sc.anyGlyph, p = s.pawns[player], best = null;
    for (var gi = 0; gi < slots.length; gi++) {
      if (s.owner[gi] >= 0) continue;
      var g = slots[gi];
      for (var bi = 0; bi < s.crates.length; bi++) { var c = s.crates[bi];
        if ((!any && c.g !== g.g) || frozen(s, bi)) continue;   // don't feed a claim from an already-claimed crate
        var sol = pushSolve(s, player, bi, g.x, g.y); if (!sol) continue;
        var atFrom = (p.x === sol.from.x && p.y === sol.from.y);
        var walk = atFrom ? 0 : (distField(s, sol.from.x, sol.from.y, player)[k(p.x, p.y)]);
        if (walk == null) continue;                                          // can't even reach the push cell
        var cost = sol.pushes * 4 + walk;                                    // pushes cost more than walking
        if (!best || cost < best.cost) best = { cost: cost, sol: sol, gi: gi };
      }
    }
    if (!best) return null;
    var sol = best.sol, mv = -1;
    if (p.x === sol.from.x && p.y === sol.from.y) mv = sol.dir;              // in position -> push
    else { var df = distField(s, sol.from.x, sol.from.y, player), bd = 1e9;  // else step toward the push cell
      for (var d2 = 0; d2 < 4; d2++) { if (!canMove(s, player, d2)) continue;
        var nx = p.x + DIRS[d2][0], ny = p.y + DIRS[d2][1], dd = df[k(nx, ny)];
        if (dd != null && dd < bd && crateAt(s, nx, ny) < 0) { bd = dd; mv = d2; } } }  // pure step, don't disturb boxes
    return mv < 0 ? null : { cost: best.cost, move: mv, gi: best.gi };
  }
  // the single move that begins a push whose first pushing cell is `from` (dir `dir`): push if already in
  // position, else step toward it (a pure step that doesn't disturb any box). -1 if unreachable.
  function stepToPush(s, player, from, dir) {
    var p = s.pawns[player];
    if (p.x === from.x && p.y === from.y) return dir;
    var df = distField(s, from.x, from.y, player), bd = 1e9, mv = -1;
    for (var d = 0; d < 4; d++) { if (!canMove(s, player, d)) continue;
      var nx = p.x + DIRS[d][0], ny = p.y + DIRS[d][1], dd = df[k(nx, ny)];
      if (dd != null && dd < bd && crateAt(s, nx, ny) < 0) { bd = dd; mv = d; } }
    return mv;
  }
  // CLEARING search: when nothing can be claimed by a single box (blockers in the way), a bounded push-BFS
  // over ALL movable crates to get ANY of them onto ANY open goal — it will shove blocking crates aside
  // first if that's what it takes. Returns the first push { from, dir } of a shortest such plan, or null.
  function clearPlan(s, player) {
    var sc = s.sc, p0 = s.pawns[player], stat = {}, mpos = [];
    var op = s.pawns[1 - player]; stat[k(op.x, op.y)] = 1;
    for (var i = 0; i < s.crates.length; i++) { var c = s.crates[i];
      if (locked(s, i, player)) stat[k(c.x, c.y)] = 1; else mpos.push([c.x, c.y]); }  // rival claims static; mine movable
    if (!mpos.length) return null;
    var goalOpen = {}, any = false;
    for (var gi = 0; gi < sc.slots.length; gi++) if (s.owner[gi] < 0) { goalOpen[k(sc.slots[gi].x, sc.slots[gi].y)] = 1; any = true; }
    if (!any) return null;
    function occ(pos) { var o = {}; for (var j = 0; j < pos.length; j++) o[k(pos[j][0], pos[j][1])] = 1; return o; }
    function key(pos, px, py) { return pos.map(function (a) { return a[0] + "," + a[1]; }).sort().join(";") + "|" + px + "," + py; }
    function region(pos, px, py) { var o = occ(pos); for (var kk in stat) o[kk] = 1; var r = floodReach(sc, px, py, o); return { reg: r, rep: repOf(r) }; }
    var r0 = region(mpos, p0.x, p0.y);
    var q = [{ pos: mpos, reg: r0, rep: r0.rep, first: null }], hd = 0, seen = {}, cap = 5000;
    seen[key(mpos, 0, 0).split("|")[0] + "|" + r0.rep] = 1;
    while (hd < q.length) {
      if (hd > cap) return null;
      var st = q[hd++], oc = occ(st.pos);
      for (var j = 0; j < st.pos.length; j++) {
        var bx = st.pos[j][0], by = st.pos[j][1];
        for (var d = 0; d < 4; d++) {
          if (!passable(sc, bx, by, d)) continue;
          var nbx = bx + DIRS[d][0], nby = by + DIRS[d][1], nk = k(nbx, nby);
          if (oc[nk] || stat[nk]) continue;                                       // destination occupied
          var fx = bx - DIRS[d][0], fy = by - DIRS[d][1];
          if (!st.reg[k(fx, fy)] || !passable(sc, fx, fy, d)) continue;           // pawn can't push from behind
          var first = st.first || { from: { x: fx, y: fy }, dir: d };
          if (goalOpen[nk]) return { from: first.from, dir: first.dir };          // a crate reached an open goal
          var npos = st.pos.slice(); npos[j] = [nbx, nby];
          var nr = region(npos, bx, by);                                          // pawn ends on the old crate cell
          var nkey = npos.map(function (a) { return a[0] + "," + a[1]; }).sort().join(";") + "|" + nr.rep;
          if (seen[nkey]) continue; seen[nkey] = 1;
          q.push({ pos: npos, reg: nr.reg, rep: nr.rep, first: first });
        }
      }
    }
    return null;
  }
  // For one open slot, the best matching box's PUSH-distance to it, plus how far `player`'s pawn is from
  // being in position to make the next push that shortens that distance. `field` = the pawn's crate-aware
  // walk distances. This drives multi-step Sokoban play: pick the box that's push-closest and go work it in.
  function slotWork(s, player, i, field) {
    var pd = s.sc.pdist[i], slots = s.sc.slots, any = s.sc.anyGlyph, best = 99, box = -1;
    for (var ci = 0; ci < s.crates.length; ci++) { var c = s.crates[ci];
      if ((!any && c.g !== slots[i].g) || frozen(s, ci)) continue;    // generic: any box can feed any goal
      var dd = pd[k(c.x, c.y)]; if (dd != null && dd < best) { best = dd; box = ci; }
    }
    if (box < 0) return { pd: 22, pw: 20 };                 // no workable box for this glyph -> far
    if (best === 0) return { pd: 0, pw: 0 };
    var c = s.crates[box], pw = 20;                          // walk to the cell behind the box for the next push
    for (var di = 0; di < 4; di++) {
      var nx = c.x + DIRS[di][0], ny = c.y + DIRS[di][1];    // box would move here (must shorten pushdist)
      if (pd[k(nx, ny)] !== best - 1 || !passable(s.sc, c.x, c.y, di)) continue;
      var bx = c.x - DIRS[di][0], by = c.y - DIRS[di][1];    // pawn stands here to push
      if (blocked(s, bx, by) || crateAt(s, bx, by) >= 0) continue;
      var w = (s.pawns[player].x === bx && s.pawns[player].y === by) ? 0 : field[k(bx, by)];
      if (w != null && w < pw) pw = w;
    }
    return { pd: best, pw: pw };
  }
  // total "how close am I to claiming the open slots" (bigger = closer). Sums each open slot's push work.
  function progress(s, player) {
    var field = pawnField(s, player), slots = s.sc.slots, sumPd = 0, bestClaim = 60;
    for (var i = 0; i < slots.length; i++) { if (s.owner[i] >= 0) continue;
      var w = slotWork(s, player, i, field);
      sumPd += Math.min(w.pd, 20);                          // overall: keep boxes moving toward the open goals
      var claim = 2 * w.pd + w.pw;                          // this goal's total distance-to-claim for the pawn
      if (claim < bestClaim) bestClaim = claim;             // ...and beeline for the single easiest next claim (focus)
    }
    // near goals dominate (10x the focus term) but every open goal still tugs a little (keeps boxes advancing)
    return -(4 * sumPd + 16 * Math.min(bestClaim, 40));
  }
  function evalState(s, me) {
    if (over(s)) { var w = winner(s); return w === me ? 1e6 : (w === 1 - me ? -1e6 : 0); }
    // permanent claims dominate; then my push-progress minus the rival's (discounted) -> race + block.
    return 600 * (owned(s, me) - owned(s, 1 - me)) + progress(s, me) - 0.9 * progress(s, 1 - me);
  }
  function ab(s, player, me, depth, alpha, beta) {
    if (over(s) || depth === 0) return evalState(s, me);
    var moves = legalMoves(s, player); if (!moves.length) return evalState(s, me);
    if (player === me) {
      var best = -1e9;
      for (var i = 0; i < moves.length; i++) { var c = clone(s); apply(c, player, moves[i]);
        best = Math.max(best, ab(c, 1 - player, me, depth - 1, alpha, beta));
        alpha = Math.max(alpha, best); if (beta <= alpha) break; }
      return best;
    } else {
      var worst = 1e9;
      for (var j = 0; j < moves.length; j++) { var c2 = clone(s); apply(c2, player, moves[j]);
        worst = Math.min(worst, ab(c2, 1 - player, me, depth - 1, alpha, beta));
        beta = Math.min(beta, worst); if (beta <= alpha) break; }
      return worst;
    }
  }
  // The AI never *initiates* a pass — it plays its best move. It only *accepts* a pass (passes back to end
  // the game) when the opponent just passed AND it is content: not behind on either held slots or control
  // score, and not on the verge of a sweep win. So pass/pass ends the game only by mutual agreement; a
  // player who is behind keeps fighting instead of settling.
  function aiMove(s, player, depth) {
    depth = depth || 6;
    var opp = 1 - player, order = freshMoves(s, player);                   // legal, non-repeating
    if (!order.length) return PASS;                                        // only repeating moves left: must pass
    var mine = claimPlan(s, player), theirs = claimPlan(s, opp);
    // Defence: if the rival will claim clearly sooner and I'm not about to, go sit on their target goal (a
    // pawn on the goal cell blocks the push). Only when it's cheap — otherwise just out-race them.
    if (theirs && (!mine || theirs.cost + 3 < mine.cost)) {
      var g = s.sc.slots[theirs.gi], p = s.pawns[player];
      if (crateAt(s, g.x, g.y) < 0) {
        var df = distField(s, g.x, g.y, player), bd = 1e9, mv = -1;
        for (var d = 0; d < 4; d++) { if (!canMove(s, player, d)) continue;
          var nx = p.x + DIRS[d][0], ny = p.y + DIRS[d][1], dd = df[k(nx, ny)];
          if (dd != null && dd < bd && crateAt(s, nx, ny) < 0) { bd = dd; mv = d; } }
        if (mv >= 0 && bd < 30 && order.indexOf(mv) >= 0) return mv;
      }
    }
    // Offence: take the step toward the cheapest goal I can actually claim (a full solved push sequence).
    if (mine && order.indexOf(mine.move) >= 0) return mine.move;
    // No direct claim -> try to CLEAR a path (shove a blocking crate aside first), then head that way.
    if (!mine) {
      var cp = clearPlan(s, player);
      if (cp) { var cm = stepToPush(s, player, cp.from, cp.dir); if (cm >= 0 && order.indexOf(cm) >= 0) return cm; }
      return PASS;                                                                // genuinely stuck -> offer to end
    }
    // I can claim but the planned step is momentarily blocked -> best positioning move (keep fighting, don't end).
    var ord = order.slice();
    for (var i = ord.length - 1; i > 0; i--) { var j = (Math.random() * (i + 1)) | 0; var t = ord[i]; ord[i] = ord[j]; ord[j] = t; }
    var best = -1e9, pick = ord[0];
    for (var m = 0; m < ord.length; m++) { var c = clone(s); apply(c, player, ord[m]);
      var v = ab(c, opp, player, depth - 1, -1e9, 1e9);
      if (v > best) { best = v; pick = ord[m]; } }
    return pick;
  }

  return { MAZES: MAZES, DIRS: DIRS, PASS: PASS, newGame: newGame, clone: clone, legalMoves: legalMoves,
    canMove: canMove, apply: apply, over: over, winner: winner, owned: owned, majority: majority,
    crateAt: crateAt, pawnAt: pawnAt, slotAt: slotAt, locked: locked, aiMove: aiMove,
    keyOf: keyOf, remember: remember, repeats: repeats, build: build };
});

// ---- headless fairness / sanity sim: node docs/glyph_engine.js [nGames] [depth] --------------------------
if (typeof require !== "undefined" && require.main === module) {
  var G = module.exports, n = +(process.argv[2] || 40), baseDepth = +(process.argv[3] || 5);
  for (var mi = 0; mi < G.MAZES.length; mi++) {
    var firstWins = 0, draws = 0, lens = [], depth = Math.max(baseDepth, G.MAZES[mi].aiDepth || 0);
    for (var g = 0; g < n; g++) {
      var s = G.newGame(mi), first = g % 2, cur = first, plies = 0, w = -1, stall = 0, sig = "";
      // Model a real pass/pass: the self-play AI never initiates a pass, so end the game once claims have
      // been frozen for STALL plies (neither side able to claim another slot) — the point at which two
      // players would both pass — and decide it on who holds more claims.
      while (plies < 300) {
        var d = G.aiMove(s, cur, depth);
        var r = G.apply(s, cur, d); G.remember(s); plies++;
        if (r.over) { w = r.won; break; }                  // reached a majority (or all slots locked)
        var nsig = s.owner.join(",");
        if (nsig === sig) { if (++stall >= 30) break; } else { stall = 0; sig = nsig; }
        cur = 1 - cur;
      }
      if (w < 0) w = G.owned(s, 0) > G.owned(s, 1) ? 0 : (G.owned(s, 1) > G.owned(s, 0) ? 1 : -1);  // pass/pass -> more claims
      if (w < 0) draws++; else if (w === first) firstWins++;
      lens.push(plies);
    }
    var decided = n - draws, avg = lens.reduce(function (a, b) { return a + b; }, 0) / n;
    console.log("Maze " + mi + " (" + G.MAZES[mi].name + "): first-mover " +
      (decided ? (firstWins / decided).toFixed(2) : "-") + "  draws " + draws + "/" + n +
      "  avg length " + avg.toFixed(0) + " plies");
  }
}
