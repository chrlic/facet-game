#!/bin/bash
# Phase-C: multi-board self-play (CPU, <=3 workers) + MLX GPU training, starting from the champion
# widened to a moderately bigger net. Runs for a wall-clock budget. All artifacts under net/spc/.
#   net/phasec.sh <budgetSeconds> <workers> <games> <sims> <epochs>
cd /Users/mdivis/Documents/playground/games || exit 1
BUDGET=${1:-28800}; WORKERS=${2:-3}; GAMES=${3:-36}; SIMS=${4:-160}; EPOCHS=${5:-6}
NEWH=64; LR=2e-3; DSIMS=120
BOARDS="tri/s,tri/m,tri/l,elong/s,elong/m,elong/l"     # all sizes + both adjacencies (deg-6 and deg-5)
D=net/spc; mkdir -p "$D"; : > "$D/sp.log"; : > "$D/duel.log"
python3 net/widen.py docs/hexago-weights.json "$D/current.json" $NEWH
echo "PHASE C start $(date)  budget=${BUDGET}s workers=$WORKERS games=$GAMES sims=$SIMS H=$NEWH boards=$BOARDS"
echo -n "iter0 (widened champion) vs MC tri/m: "; node net/duel.js "$D/current.json" MC 6 $DSIMS tri m 200 2>>"$D/duel.log"

it=0
while [ $SECONDS -lt "$BUDGET" ]; do
  it=$((it+1))
  echo "=== ITER $it self-play $(date +%H:%M:%S) [elapsed ${SECONDS}s] ==="
  rm -f "$D"/it${it}_*.jsonl
  per=$(( (GAMES + WORKERS - 1) / WORKERS ))
  for w in $(seq 1 "$WORKERS"); do
    node net/selfplay.js "$D/current.json" "$per" "$SIMS" "$D/it${it}_${w}.jsonl" "$BOARDS" - 16 2>>"$D/sp.log" &
  done
  wait
  cat "$D"/it${it}_*.jsonl > "$D/it${it}.jsonl" 2>/dev/null; rm -f "$D"/it${it}_*.jsonl
  prev=$((it-1))
  if [ -f "$D/it${prev}.jsonl" ]; then cat "$D/it${it}.jsonl" "$D/it${prev}.jsonl" > "$D/train.jsonl"; else cp "$D/it${it}.jsonl" "$D/train.jsonl"; fi
  echo "ITER $it train ($(wc -l < "$D/train.jsonl") pos, GPU) $(date +%H:%M:%S)"
  python3 net/train_mlx.py --data "$D/train.jsonl" --out "$D/it${it}w.json" --epochs $EPOCHS --lr $LR --warm "$D/current.json" 2>&1 | tail -1
  cp "$D/it${it}w.json" "$D/current.json"
  if [ $(( it % 2 )) -eq 0 ]; then
    echo -n "ITER $it net vs MC tri/m: ";   node net/duel.js "$D/current.json" MC 6 $DSIMS tri   m 200 2>>"$D/duel.log"
    echo -n "ITER $it net vs MC elong/m: "; node net/duel.js "$D/current.json" MC 6 $DSIMS elong m 200 2>>"$D/duel.log"
  fi
done
echo "PHASE C done $(date)  $it iterations, ${SECONDS}s elapsed"
