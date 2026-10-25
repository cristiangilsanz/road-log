#!/usr/bin/env bash
set -euo pipefail

URL="http://localhost:${DASHBOARD_PORT:-8088}"

wait_for() {
    local description="$1" check="$2"
    for _ in $(seq 1 90); do
        if eval "$check" >/dev/null 2>&1; then
            echo "ok: $description"
            return 0
        fi
        sleep 2
    done
    echo "timed out waiting for $description"
    return 1
}

fleet='curl -sf "$URL/api/fleet"'
wait_for "six trucks online and reporting" "$fleet | python3 -c 'import json,sys; v=json.load(sys.stdin)[\"vehicles\"]; sys.exit(sum(1 for x in v if x[\"online\"] and x[\"telemetry\"]) < 6)'"
wait_for "driving events detected" "curl -sf \"$URL/api/events?seconds=600\" | python3 -c 'import json,sys; sys.exit(not json.load(sys.stdin))'"
curl -sf -X POST "$URL/api/vehicles/TRK-01/config" -H "Content-Type: application/json" \
    -d '{"telemetry_interval": 1, "sampling_interval": 0.5}' >/dev/null
echo "ok: configuration accepted"
wait_for "TRK-01 reporting every second" "curl -sf \"$URL/api/vehicles/TRK-01/telemetry?seconds=5\" | python3 -c 'import json,sys; sys.exit(len(json.load(sys.stdin)) < 4)'"
