# GrowthOS v1.6 - Three-Day Deployment Acceptance

## Day 1 - Core runtime and trust
- Deploy PostgreSQL 16 + API + worker through Docker Compose.
- Verify `/health`, console, migration baseline and all production secrets.
- Configure Witness OIDC and confirm editor/approver/publisher/auditor role mapping.
- Configure Chrysalis assurance ingress and token.
- Call `/v1/chrysalis/anchor/audit`; require a stored Chrysalis receipt.
- Run split regression suite on PostgreSQL.

## Day 2 - Communications integrations
- Configure first launch destinations and execute one controlled live delivery per provider.
- Import a licensed/internal media contact sample and earned-coverage sample; verify target ranking.
- Configure inbound feeds and engagement ingress.
- Configure at least one live/licensed AEO probe and performance-event source.
- Verify Opportunity Queue refresh and Claim Graph on a controlled release.

## Day 3 - Fail-closed release exercise
- Create a high-risk test release with sourced claims.
- Verify Gate blocks missing evidence and stale approval.
- Approve with required human identity/four-eyes policy.
- Make Chrysalis temporarily unavailable; confirm Feed Agent refuses high-risk publish before any external side effect.
- Restore Chrysalis; confirm exact release hash receives receipt, then publish once.
- Verify delivery idempotency, local audit chain, Chrysalis audit-head anchor, release receipt, claim graph, performance ingest and recovery/runbook.

GA requires all mandatory items above to pass on the actual target environment. Contract/mock tests do not substitute for live provider acceptance.
