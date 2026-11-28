#!/bin/bash
# Prompt for API keys (hidden input), write .env (mode 600), and mirror it to the Modal secret `jev-keys`
# so remote jobs see the same keys. Press Enter to keep an existing value. Re-run any time.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -t 0 ] || { echo "setup_keys.sh needs an interactive terminal (hidden prompt). Run it in Terminal, not via '!'." >&2; exit 1; }
touch .env && chmod 600 .env

get() { grep -E "^$1=" .env | tail -1 | cut -d= -f2- || true; }
set_kv() { grep -vE "^$1=" .env > .env.tmp || true; echo "$1=$2" >> .env.tmp; mv .env.tmp .env; chmod 600 .env; }

# usage: scripts/setup_keys.sh [KEY_NAME ...]   (no args = all keys; e.g. scripts/setup_keys.sh SAIL_API_KEY)
keys=("$@"); [ ${#keys[@]} -gt 0 ] || keys=(SAIL_API_KEY TYPESAFE_API_KEY HF_TOKEN FIREWORKS_API_KEY BASETEN_API_KEY)
for k in "${keys[@]}"; do
  cur=$(get $k); hint=${cur:+" (set, ends …${cur: -4})"}
  read -rsp "$k$hint: " v; echo
  [ -n "$v" ] && set_kv $k "$v"
done
# Fixed, non-secret defaults (provider docs, 2026-11-21)
[ -n "$(get SAIL_BASE_URL)" ] || set_kv SAIL_BASE_URL https://api.sailresearch.com/v1

uvx --quiet --from modal --with python-dotenv modal secret create jev-keys --from-dotenv .env --force >/dev/null
echo "Wrote .env and Modal secret 'jev-keys'. Now run: scripts/check_keys.sh"
