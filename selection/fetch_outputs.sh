#!/bin/bash
# Pull offline-sweep outputs from the jev-data volume into the repo.
set -euo pipefail
cd "$(dirname "$0")/.."
T=$(mktemp -d); modal volume get jev-data out "$T" >/dev/null
mkdir -p data/libraries data/selections results
for s in 1k 35k; do cp "$T/out/library_$s.json" data/libraries/$s.json; done
for f in "$T"/out/selections_*.json; do b=$(basename "$f" .json); cp "$f" data/selections/${b#selections_}.json; done
cp "$T"/out/offline_recall*.csv results/
rm -rf "$T"; ls data/libraries data/selections results
