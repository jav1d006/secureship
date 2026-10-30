#!/usr/bin/env bash
# Upload the current git checkout to SecureShip, wait for the result, fail below a score.
# Env: SECURESHIP_URL, SECURESHIP_API_KEY, SCANNERS, FAIL_UNDER, SARIF_FILE, TIMEOUT_SEC
set -euo pipefail

: "${SECURESHIP_URL:?set SECURESHIP_URL}"
: "${SECURESHIP_API_KEY:?set SECURESHIP_API_KEY}"
url="${SECURESHIP_URL%/}"
scanners="${SCANNERS:-secrets,dependencies,code}"
fail_under="${FAIL_UNDER:-0}"
timeout_sec="${TIMEOUT_SEC:-600}"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
api() { curl -fsS --max-time 120 -H "X-API-Key: $SECURESHIP_API_KEY" "$@"; }

git archive --format=zip -o "$work/project.zip" HEAD
resp="$(api -F "file=@$work/project.zip" -F "scanners=$scanners" "$url/api/v1/scans")"
id="$(jq -er .id <<<"$resp")"
echo "SecureShip scan $id queued (scanners: $scanners)"

deadline=$((SECONDS + timeout_sec))
while :; do
  scan="$(api "$url/api/v1/scans/$id")"
  status="$(jq -r .status <<<"$scan")"
  [ "$status" = "done" ] && break
  if [ "$status" = failed ]; then
    echo "::error::SecureShip scan failed: $(jq -r '.error // "unknown error"' <<<"$scan")"
    exit 1
  fi
  if [ "$SECONDS" -ge "$deadline" ]; then
    echo "::error::SecureShip scan did not finish within ${timeout_sec}s"
    exit 1
  fi
  sleep 3
done

score="$(jq -r .score <<<"$scan")"
echo "Security score: $score/100"
jq -r '[.result | to_entries[] | select(.key as $k | ["modules","errors","skipped","timings"] | index($k) | not)
        | .value.findings[]?.severity] | group_by(.) | map("\(.[0]): \(length)") | join("  ") | if . == "" then "no findings" else . end' <<<"$scan"

if [ -n "${SARIF_FILE:-}" ]; then
  api "$url/api/v1/scans/$id/export?format=sarif" -o "$SARIF_FILE"
  echo "SARIF written to $SARIF_FILE"
fi
if [ -n "${GITHUB_OUTPUT:-}" ]; then
  { echo "score=$score"; echo "scan-id=$id"; } >>"$GITHUB_OUTPUT"
fi

if [ "$score" -lt "$fail_under" ]; then
  echo "::error::Security score $score is below the required $fail_under"
  exit 1
fi
