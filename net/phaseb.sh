#!/bin/bash
# Phase-B AlphaZero-style loop: parallel self-play -> warm-start train -> always-promote, with a net-vs-MC
# probe every 2 iterations to track strength. All artifacts under net/spb/ (gitignored).
cd /Users/mdivis/Documents/playground/games || exit 1
# WORKERS capped at 3 (user compute budget). Self-play uses net-PUCT+RAVE at SIMS (supra-MC data);
# the MC probe duels at the cheaper DSIMS to track deployable strength.
BOARD=tri; SIZE=m; ITERS=${1:-20}; WORKERS=${2:-3}; GAMES=${3:-48}; SIMS=${4:-200}; DSIMS=120; EPOCHS=5; H=48; K=3; LR=0.015
D=net/spb; mkdir -p "$D"; : > "$D/sp.log"; : > "$D/duel.log"
cp docs/hexago-weights.json "$D/current.json"
echo "PHASE B start $(date)  board=$BOARD/$SIZE iters=$ITERS games=$GAMES sims=$SIMS workers=$WORKERS"
echo -n "iter0 (Phase-A) net vs MC: "; node net/duel.js "$D/current.json" MC 6 $DSIMS $BOARD $SIZE 200 2>>"$D/duel.log"

for it in $(seq 1 "$ITERS"); do
  echo "=== ITER $it self-play $(date +%H:%M:%S) ==="
  rm -f "$D"/it${it}_*.jsonl
  per=$(( (GAMES + WORKERS - 1) / WORKERS ))
  for w in $(seq 1 "$WORKERS"); do
    node net/selfplay.js "$D/current.json" "$per" "$SIMS" "$D/it${it}_${w}.jsonl" "$BOARD" "$SIZE" 18 2>>"$D/sp.log" &
  done
  wait
  cat "$D"/it${it}_*.jsonl > "$D/it${it}.jsonl" 2>/dev/null; rm -f "$D"/it${it}_*.jsonl
  prev=$((it-1))
  if [ -f "$D/it${prev}.jsonl" ]; then cat "$D/it${it}.jsonl" "$D/it${prev}.jsonl" > "$D/train.jsonl"; else cp "$D/it${it}.jsonl" "$D/train.jsonl"; fi
  echo "ITER $it train ($(wc -l < "$D/train.jsonl") positions) $(date +%H:%M:%S)"
  node net/train.js train "$D/train.jsonl" "$D/it${it}w.json" $EPOCHS $H $K $LR "$D/current.json" 2>&1 | tail -1
  cp "$D/it${it}w.json" "$D/current.json"           # always-promote (AlphaZero-Zero style)
  if [ $(( it % 2 )) -eq 0 ] || [ "$it" -eq "$ITERS" ]; then
    echo -n "ITER $it net vs MC: "; node net/duel.js "$D/current.json" MC 6 $DSIMS $BOARD $SIZE 200 2>>"$D/duel.log"
  fi
done
echo "PHASE B done $(date)"
