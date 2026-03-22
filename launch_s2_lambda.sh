#!/usr/bin/env bash
# Lambda Cloud launcher for FishAudio S2 Pro (SGLang Omni) using udocker
# Usage:
#   export LAMBDA_API_KEY="secret_..."
#   ./launch_s2_lambda.sh [instance_type] [region]
#
# If no instance_type is given, polls for the cheapest available single-GPU
# H100/H200/B200 instance. Once launched, SSHes in and bootstraps udocker
# with the sglang-omni image + GPU passthrough.
#
# Cost for 4-hour booth (approx):
#   gpu_1x_gh200       → $1.99/hr → ~$8
#   gpu_1x_h100_pcie   → $2.86/hr → ~$12
#   gpu_1x_h100_sxm5   → $3.78/hr → ~$16
#   gpu_1x_b200_sxm6   → $6.08/hr → ~$25
set -euo pipefail

API_KEY="${LAMBDA_API_KEY:?Set LAMBDA_API_KEY}"
API="https://cloud.lambda.ai/api/v1"
AUTH="Authorization: Bearer $API_KEY"

PREFERRED_TYPES=(
  gpu_1x_h100_sxm5    # $3.78/hr  – 80 GB, closest to H200 perf
  gpu_1x_h100_pcie    # $2.86/hr  – 80 GB PCIe
  gpu_1x_b200_sxm6    # $6.08/hr  – 180 GB, overkill but works
  gpu_1x_gh200        # $1.99/hr  – 96 GB unified memory
  gpu_2x_h100_sxm5    # $7.34/hr  – fallback: 2x H100
)

INSTANCE_TYPE="${1:-}"
REGION="${2:-}"
SSH_KEY_NAME="abdur rahim"
POLL_INTERVAL=30

header() { printf '\n\033[1;36m>>> %s\033[0m\n' "$1"; }
info()   { printf '    %s\n' "$1"; }
err()    { printf '\033[1;31mERR: %s\033[0m\n' "$1" >&2; }

find_available_instance() {
  header "Polling Lambda Cloud for available GPU instances..."
  local data
  data=$(curl -sf -H "$AUTH" "$API/instance-types")

  for itype in "${PREFERRED_TYPES[@]}"; do
    local regions
    regions=$(echo "$data" | python3 -c "
import json, sys
d = json.load(sys.stdin)['data']
entry = d.get('$itype', {})
caps = entry.get('regions_with_capacity_available', [])
print(' '.join(r['name'] for r in caps))
" 2>/dev/null)

    if [[ -n "$regions" ]]; then
      INSTANCE_TYPE="$itype"
      REGION="${regions%% *}"
      local price
      price=$(echo "$data" | python3 -c "
import json, sys
d = json.load(sys.stdin)['data']
print(d['$itype']['instance_type']['price_cents_per_hour'] / 100)
")
      info "Found: $INSTANCE_TYPE in $REGION (\$$price/hr)"
      return 0
    fi
  done
  return 1
}

launch_instance() {
  header "Launching $INSTANCE_TYPE in $REGION..."
  local resp
  resp=$(curl -sf -H "$AUTH" -H "Content-Type: application/json" \
    -X POST "$API/instance-operations/launch" \
    -d "{
      \"region_name\": \"$REGION\",
      \"instance_type_name\": \"$INSTANCE_TYPE\",
      \"ssh_key_names\": [\"$SSH_KEY_NAME\"],
      \"quantity\": 1,
      \"name\": \"s2-tts-$(date +%s)\"
    }")

  INSTANCE_ID=$(echo "$resp" | python3 -c "
import json, sys
d = json.load(sys.stdin)
ids = d.get('data', {}).get('instance_ids', [])
if ids: print(ids[0])
else: print(json.dumps(d)); sys.exit(1)
")
  info "Instance ID: $INSTANCE_ID"
}

wait_for_instance() {
  header "Waiting for instance $INSTANCE_ID to become active..."
  local ip=""
  for i in $(seq 1 60); do
    local resp
    resp=$(curl -sf -H "$AUTH" "$API/instances/$INSTANCE_ID" 2>/dev/null || echo '{}')
    local status
    status=$(echo "$resp" | python3 -c "
import json, sys
d = json.load(sys.stdin).get('data', {})
print(d.get('status', 'unknown'))
" 2>/dev/null)
    ip=$(echo "$resp" | python3 -c "
import json, sys
d = json.load(sys.stdin).get('data', {})
print(d.get('ip', '') or '')
" 2>/dev/null)

    info "[$i/60] status=$status ip=${ip:-pending}"
    if [[ "$status" == "active" && -n "$ip" ]]; then
      INSTANCE_IP="$ip"
      return 0
    fi
    sleep 10
  done
  err "Timed out waiting for instance"
  exit 1
}

bootstrap_remote() {
  header "Bootstrapping udocker + SGLang Omni on $INSTANCE_IP..."

  ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 "ubuntu@$INSTANCE_IP" bash -s <<'REMOTE_SCRIPT'
set -euo pipefail

echo "=== Installing udocker ==="
pip install udocker 2>/dev/null || pip3 install udocker
udocker install 2>/dev/null || true

echo "=== Pulling sglang-omni image ==="
udocker pull frankleeeee/sglang-omni:dev

echo "=== Creating container ==="
udocker create --name=sglang frankleeeee/sglang-omni:dev

echo "=== Enabling NVIDIA GPU passthrough ==="
udocker setup --nvidia --force sglang

echo "=== Cloning sglang-omni inside container ==="
udocker run \
  --volume=/dev/shm \
  --volume=/tmp \
  --env="NVIDIA_VISIBLE_DEVICES=all" \
  --workdir=/workspace \
  sglang /bin/bash -c '
    set -e
    git clone https://github.com/sgl-project/sglang-omni.git /workspace/sglang-omni
    cd /workspace/sglang-omni
    pip install uv 2>/dev/null || true
    uv venv .venv -p 3.12 && source .venv/bin/activate
    uv pip install -v ".[s2pro]"
    huggingface-cli download fishaudio/s2-pro
    echo "=== S2 Pro model ready ==="
  '

echo ""
echo "=========================================="
echo " Setup complete! Connect and run:"
echo "   ssh ubuntu@$HOSTNAME"
echo ""
echo " Start the playground (Gradio UI):"
echo "   udocker run --volume=/dev/shm --env=NVIDIA_VISIBLE_DEVICES=all sglang /bin/bash -c \\"
echo "     'cd /workspace/sglang-omni && source .venv/bin/activate && ./playground/tts/start.sh'"
echo ""
echo " Or start the API server (port 8000, no -p needed — udocker shares host network):"
echo "   udocker run --volume=/dev/shm --env=NVIDIA_VISIBLE_DEVICES=all sglang /bin/bash -c \\"
echo "     'cd /workspace/sglang-omni && source .venv/bin/activate && python -m sglang_omni.cli.cli serve \\"
echo "       --model-path fishaudio/s2-pro --config examples/configs/s2pro_tts.yaml --port 8000'"
echo ""
echo " Test TTS (no voice clone — robotic):"
echo "   curl -X POST http://localhost:8000/v1/audio/speech \\"
echo "     -H 'Content-Type: application/json' \\"
echo "     -d '{\"input\": \"Why do you want to know?\"}' --output test.wav"
echo "=========================================="
REMOTE_SCRIPT
}

# ── Main ─────────────────────────────────────────────────────────────────
if [[ -z "$INSTANCE_TYPE" ]]; then
  while true; do
    if find_available_instance; then
      break
    fi
    info "No capacity. Retrying in ${POLL_INTERVAL}s... ($(date +%H:%M:%S))"
    sleep "$POLL_INTERVAL"
  done
fi

if [[ -z "$REGION" ]]; then
  err "Specify region as second argument, e.g.: $0 gpu_1x_h100_sxm5 us-east-1"
  exit 1
fi

launch_instance
wait_for_instance
bootstrap_remote

header "Done! Instance running at $INSTANCE_IP"
info "SSH:  ssh ubuntu@$INSTANCE_IP"
info "Type: $INSTANCE_TYPE ($REGION)"
info "ID:   $INSTANCE_ID"
info ""
info "To terminate:  curl -sf -H 'Authorization: Bearer \$LAMBDA_API_KEY' \\"
info "  -X POST $API/instance-operations/terminate \\"
info "  -H 'Content-Type: application/json' \\"
info "  -d '{\"instance_ids\": [\"$INSTANCE_ID\"]}'"
