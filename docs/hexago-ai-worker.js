// HEXA-GO AI worker — runs the (RAVE) Monte-Carlo search off the main thread so the UI never
// freezes while the AI thinks. The page posts {reqId, board:{type,size}, state, budgetMs}; we
// reply {reqId, move}. The engine's time-budget loop uses real Date.now() here (a worker has a
// normal clock), so it can think as long as we allow without blocking rendering.
/* global HEXAGO */
importScripts("hexago_engine.js");

self.onmessage = function (e) {
  var d = e.data || {};
  try {
    HEXAGO.setBoard(d.board.type, d.board.size);
    var mv = HEXAGO.aiMove(d.state, d.budgetMs);
    self.postMessage({ reqId: d.reqId, move: mv });
  } catch (err) {
    self.postMessage({ reqId: d.reqId, error: String(err && err.message || err) });
  }
};
