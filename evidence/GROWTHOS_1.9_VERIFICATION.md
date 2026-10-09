# GrowthOS 1.9 verification

## Implemented

- Live Denizen inference connection, credentials stored only in ignored local configuration or a Kubernetes runtime Secret.
- Specialist instructions for press releases, social posts, outreach emails and podcast scripts.
- Persistent shared brand voice and writing examples; only administrators can change them.
- Four-format campaigns generated from one brief. Provider failure before completion saves no partial campaign.
- Another-version flow preserves the original and gives the model the prior draft and source material.
- Mechanical checks for source-absent numbers and URLs, unfinished placeholders, excluded phrases and missing podcast sections. Findings remain editorial advice, not factual verification.
- Separate AI review tied to the content hash. Edits mark earlier review as stale. No generated text grants approval or verified claims.
- Source notes, campaign navigation, text export, and disabled-by-default destination setup in the console.
- Helm chart, production values example, chart validation script and manual image/chart packaging workflow.

## Verified locally

- Full regression snapshot: **308 passed, 3 skipped**, recorded in `growthos-1.9-local.xml`. Three optional MCP SDK cases were skipped in this environment.
- Final focused suite after subsequent fixes: **23 passed**, recorded in `growthos-1.9-focused.xml`. Includes brand permissions, atomic campaign failure, revision lineage, review invalidation, parser behavior, browser workflows, XSS, approvals and mobile layout.
- Helm 3.19 lint passed. Four deployment variants rendered and resource wiring checks passed. Seven invalid configuration cases failed as intended.
- Real Denizen Qwen generated all four synthetic campaign drafts, each saved in draft state. AI editorial review returned successfully after accommodating its list-shaped response. Synthetic test records are identifiable as tests in the local workspace.
- Desktop studio and mobile brand settings inspected; no page errors and no phone-width overflow.

## Limits and outstanding production checks

- No Kubernetes rollout has been performed. Image build/pull, cluster admission, PVC provisioning, real DNS/TLS, backup restore and cluster smoke tests remain unverified. No cluster context or deployment hostname was supplied. Docker/Kubernetes are not installed in the local validation environment.
- The verified model remains `qwen3-0.6b`. Alternative Denizen model trials produced truncated, malformed, timed-out or less source-faithful output; no superior model was established by these limited trials. This is not a benchmark of those model families.
- The small Qwen model can ignore requested podcast structure or add unsupported meaning. Checks surface detectable issues; human source review remains necessary. An empty AI findings list is not proof of accuracy.
- Podcast script generation is connected; production audio, consent, podcast hosting and distribution are not verified.
- The later replacement credential was rejected by the current Denizen endpoint with HTTP 401. The existing verified connection was preserved. Neither credential is included in Git, the container build context or the Helm package.
- No claim of a perfect quality score or production readiness is made.
