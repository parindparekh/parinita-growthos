#!/usr/bin/env bash
# End-to-end walkthrough: a blocked release, the evidence that unblocks it, a reviewer's decision on an
# opinion, a human approval, a public feed, and the audit chain. The same steps can be done in /console.
set -euo pipefail
cd "$(dirname "$0")/.."
BASE=${BASE:-http://localhost:8080}
env_val() { grep -E "^$1=" .env | head -1 | cut -d= -f2-; }
KEY=${API_KEY:-$(env_val API_KEY)}
APPROVER_KEY=${APPROVER_KEY:-$(env_val API_KEYS | cut -d, -f1 | cut -d: -f3)}
PY=$(command -v python3 || command -v python)
j() { "$PY" -c "import json,sys; d=json.load(sys.stdin); print($1)"; }
api() { curl -sS -X "$1" "$BASE$2" -H "X-API-Key: ${4:-$KEY}" -H 'Content-Type: application/json' ${3:+-d "$3"}; }

echo "1) PR draft: an unsourced number, and prose nobody has accounted for -> blocked"
ID=$(api POST /v1/content '{"content_type":"press_release","classification":"pr","title":"GrowthOS pilot results","body":"Parinita GrowthOS cut release review time by 40% in the pilot.\nCustomers love it.\nWe believe governed publishing matters.","cta_url":"https://example.com/try"}' | j 'd["id"]')
api POST "/v1/content/$ID/pipeline" | j '"   state=%s\n   " % d["state"] + "\n   ".join(d["results"]["gate"]["blockers"])'

echo "2) Sentence ledger: what each sentence needs"
api GET "/v1/content/$ID/assertions" | j '"\n".join("   %-8s %-15s %s" % (s["status"], s.get("suggestion") or s.get("reason",""), s["text"]) for s in d["sentences"])'

echo "3) Attach sourced claims for the facts; a reviewer lets the opinion stand"
api PATCH "/v1/content/$ID" '{"claims":[
  {"text":"GrowthOS pilot results: Parinita GrowthOS cut release review time by 40% in the pilot","sources":[{"uri":"internal://pilot-report-2026-09"}]},
  {"text":"Customers love it (pilot satisfaction survey)","sources":[{"uri":"internal://pilot-csat-2026-09"}]}]}' >/dev/null
OPINION=$(api GET "/v1/content/$ID/assertions" | j '[s["hash"] for s in d["sentences"] if s["status"]=="open"][0]')
api PUT "/v1/content/$ID/assertions/$OPINION/disposition" '{"disposition":"opinion","note":"company stance"}' "$APPROVER_KEY" >/dev/null
api POST "/v1/content/$ID/pipeline" | j '"   state=%s sentences=%s" % (d["state"], d["results"]["gate"]["checks"]["sentences"])'

echo "4) Investor content -> blocked until a named approver signs this exact version"
INV=$(api POST /v1/content '{"classification":"investor","title":"Investor update for the demo","body":"Bookings were in line with the plan shared in June.","claims":[{"text":"Investor update for the demo: bookings were in line with the plan shared in June","sources":[{"uri":"internal://board-pack-2026-09"}]}]}' | j 'd["id"]')
api POST "/v1/content/$INV/pipeline" | j '"   state=%s blockers=%s" % (d["state"], d["results"]["gate"]["blockers"])'
api POST "/v1/content/$INV/approve" '{"approver":"Demo Approver","note":"demo"}' "$APPROVER_KEY" | j '"   state=%s approved_by=%s" % (d["state"], d.get("approved_by"))'

echo "5) Public feed: the PR item is there, the investor item is not"
api POST /v1/feeds '{"name":"Demo newsroom","slug":"demo-newsroom","direction":"outbound","protocol":"jsonfeed"}' >/dev/null || true
curl -sS "$BASE/feeds/demo-newsroom" | j '"   items=%s" % [i["title"] for i in d["items"]]'

echo "6) Audit chain"
api GET /v1/audit/verify | j '"   ok=%s events=%s head=%s" % (d["ok"], d["events"], d["head_hash"][:16])'
echo "Open $BASE/console to see the same releases in Growth Command."
