Idea is chess on octagon-diamond board.

The octagons alone are just an 8×8 rook grid. Orthogonal moves work exactly as in chess.
Diamonds are never adjacent to each other. From a diamond you can only go to an octagon. They're isolated nodes.
Therefore every diagonal in the game runs through a diamond. A slide from one octagon to the diagonal one is octagon → diamond → octagon. The diamonds sit on every single diagonal intersection.

So call them gates, and the game writes itself.
Rook — slides orthogonally across octagons. Can't fit in a gate. Identical to chess. It becomes the reliable piece.
Bishop — slides diagonally, alternating octagon, gate, octagon, gate. It can stop on either. Crucially it's blocked by anything sitting in a gate, so bishops are no longer long-range for free — their lines are studded with chokepoints.
The emergent gem: each diamond sits between four octagons — two of each checkerboard colour. Both diagonal lines pass through it. So a bishop that stops in a gate can leave on the other colour. Bishops stop being colourbound, but only by spending a tempo in a gate, and only if that gate is free and safe. The entire strategic core of the game becomes gate control — and it's a fight that matters to both players' bishops simultaneously.
Knight — a plain (2,1) leaper between octagons. It ignores gates completely. That makes it the one piece immune to the game's central constraint, so it's relatively far stronger here than in chess. Probably the correct trade-off: chess's knight/bishop balance flips.
King — steps to any of its 8 neighbours. On an octagon it has 8 escape squares; on a gate it has only 4. A gate is a bottleneck you can hide behind and a coffin you can be trapped in. Great endgame texture.
Pawn — moves one octagon forward, captures into either forward gate. From a gate it steps forward-diagonally onto an octagon. So pawns zigzag through the gates, and a pawn parked in a central gate is a permanent outpost blocking two enemy diagonals at once.
The board would be 64 octagons + 49 gates = 113 cells, standard chess army, pawns on the second octagon rank.
Why it might be a good game rather than a novelty: most chess variants add pieces or squares. This one adds a scarcity. Diagonals go from free to contested, so bishop development becomes a real fight rather than a formality, and the openings would be about seizing the four central gates the way chess openings are about e4/d4. The colour-switching-through-gates mechanic also quietly fixes chess's ugliest asymmetry — the permanently colourbound bishop — without inventing a fairy piece.
The obvious risk is that gates get plugged early and the position locks into a rook-and-knight grind. You'd probably want a rule that only light pieces (bishop, knight, pawn, king) may occupy gates, so heavy pieces can't just cement them shut.

Design the board so, that the octagons are slighly irreular sides so, that the diamonds are comparably large, but still a bit smaller, than octagons. Produce the board and pieces and offline ai to play the game as a new OCTA-CHESS game.