#!/bin/bash
# Check each key in .env with a free call (model listing / whoami) and confirm the model IDs we plan to use exist.
# Costs nothing: no completions are requested. Keys go to curl via stdin, not argv.
cd "$(dirname "$0")/.."
set -a; source .env; set +a

list() {  # $1=name $2=key $3=models URL $4..=IDs to look for
  local name=$1 key=$2 url=$3; shift 3
  [ -z "$key" ] && { echo "$name: no key (skipped)"; return; }
  local body; body=$(curl -sS -K- "$url" <<< "header = \"Authorization: Bearer $key\"") || { echo "$name: request failed"; return; }
  echo "$body" | grep -q '"data"' || { echo "$name: KEY REJECTED: ${body:0:200}"; return; }
  echo "$name: key ok"
  for id in "$@"; do echo "$body" | grep -qF "\"$id\"" && echo "  found   $id" || echo "  MISSING $id"; done
}

list SAIL "${SAIL_API_KEY:-}" "${SAIL_BASE_URL:-https://api.sailresearch.com/v1}/models" \
  Qwen/Qwen3.6-35B-A3B deepseek-ai/DeepSeek-V4-Flash-0731 zai-org/GLM-5.3 google/gemma-4-31B-it
list Fireworks "${FIREWORKS_API_KEY:-}" https://api.fireworks.ai/inference/v1/models \
  accounts/fireworks/models/glm-5p3 accounts/fireworks/models/kimi-k3 accounts/fireworks/models/qwen3-embedding-8b
list Baseten "${BASETEN_API_KEY:-}" https://inference.baseten.co/v1/models \
  deepseek-ai/DeepSeek-V4-Flash-0731 zai-org/GLM-5.3 moonshotai/Kimi-K3

if [ -n "${HF_TOKEN:-}" ]; then
  r=$(curl -sS -K- https://huggingface.co/api/whoami-v2 <<< "header = \"Authorization: Bearer $HF_TOKEN\"")
  echo "$r" | grep -q '"name"' && echo "HF: key ok" || echo "HF: KEY REJECTED"
else echo "HF: no key (skipped; public models still download)"; fi

# TypeSafe has no free endpoint we know of; the key is checked by the first real (tiny) Jev call.
[ -n "${TYPESAFE_API_KEY:-}" ] && echo "TypeSafe: key present (validated on first Jev call)" || echo "TypeSafe: no key"
