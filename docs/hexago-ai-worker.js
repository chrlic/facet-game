// HEXA-GO AI worker — runs the search off the main thread so the UI never freezes. The page posts
// {reqId, board:{type,size}, state, budgetMs}; we reply {reqId, move}. Uses the neural net-PUCT+RAVE
// evaluator when weights are available (much stronger than the MC engine), else falls back to the
// RAVE-flat Monte-Carlo engine. Real Date.now() clock here, so it can think for the full budget.
/* global HEXAGO, HEXANET */
importScripts("hexago_engine.js");
importScripts("hexago_net.js");

var netReady = false, netTried = false;
function ensureNet(cb) {
  if (netReady) return cb(true);
  if (netTried) return cb(false);
  netTried = true;
  fetch("hexago-weights.json").then(function (r) { return r.ok ? r.json() : null; })
    .then(function (w) { if (w) { HEXANET.setWeights(w); netReady = true; } cb(netReady); })
    .catch(function () { cb(false); });
}

self.onmessage = function (e) {
  var d = e.data || {};
  ensureNet(function (haveNet) {
    try {
      HEXAGO.setBoard(d.board.type, d.board.size);
      // net-PUCT (strong) when the net loaded; otherwise the MC engine (still solid). Same time budget.
      var mv = (haveNet && HEXANET.loaded()) ? HEXANET.netPuct(d.state, d.budgetMs) : HEXAGO.aiMove(d.state, d.budgetMs);
      self.postMessage({ reqId: d.reqId, move: mv, engine: (haveNet ? "net" : "mc") });
    } catch (err) {
      self.postMessage({ reqId: d.reqId, error: String(err && err.message || err) });
    }
  });
};
