#!/bin/bash
# [MEMFD_TABLES="a b"] generate.sh SF OUTDIR TOOLS PARTS JOBS  - dsdgen in PARTS chunks, joined in order into <table>.dat
set -euo pipefail
me=$(readlink -f "$0")
sf=$1; out=$2; tools=$3; parts=$4; jobs=$5
mkdir -p "$out"; [ -z "$(ls -A "$out")" ] || { echo "output directory is not empty"; exit 2; }
cd "$tools"
if [ "$parts" = 1 ]; then
  ./dsdgen -SCALE "$sf" -DIR "$out" > "$out/.log" 2>&1; rm -f "$out/.log"; exit 0
fi
if [ -n "${MEMFD_TABLES:-}" ]; then
  setsid python3 "$(dirname "$me")/memfd_tables.py" "$out" "$parts" 4 $MEMFD_TABLES > /dev/null 2> "$out/.memfd.log" < /dev/null &
  joiner=$!
fi
seq 1 "$parts" | xargs -P "$jobs" -I{} sh -c "./dsdgen -SCALE $sf -DIR '$out' -PARALLEL $parts -CHILD {} > '$out/.log{}' 2>&1 && touch '$out/.done{}'" || { tail -3 "$out"/.log*; exit 3; }
rm -f "$out"/.log*
cd "$out"
if [ -n "${MEMFD_TABLES:-}" ]; then
  while [ ! -f .memfd-ready ]; do sleep 2; kill -0 $joiner || { cat .memfd.log; exit 4; }; done
fi
rm -f .done*
for first in *_1_"$parts".dat; do
  t=${first%_1_"$parts".dat}
  mv "$first" "$t.dat"
  for i in $(seq 2 "$parts"); do
    f=${t}_${i}_$parts.dat
    [ -f "$f" ] || continue
    [ "$t" = dbgen_version ] || cat "$f" >> "$t.dat"
    rm "$f"
  done
done
ls | wc -l
