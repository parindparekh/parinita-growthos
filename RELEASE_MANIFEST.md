# Parinita GrowthOS v1.8.0 Release Manifest

Date: 2026-10-08. Status: locally verified deployment candidate; target acceptance pending.

- Source, adapters, migrations, worker, console, launchers and tests included.
- 28 named capabilities: 15 core identities, 13 channel specialists.
- 37 protocol implementations inherited; live certification not claimed.
- Supplied packet evidence: 302 passed; baseline 285 passed. New Windows verification: 299 main-suite passes plus 3 separately run SDK passes; see `evidence/LOCAL_BUILD.md`.
- `evidence/pytest.xml`, `evidence/baseline-pytest.xml`, test summary and original checksum verification included.
- `requirements.lock`, `requirements-dev.lock`, `evidence/sbom.cdx.json`, `.github/workflows/ci.yml` included.
- The packet's separate deliverables are retained locally and excluded from the public source repository. Application operating documentation remains under `docs/`.
- No new migration/schema; new assurance annotations stored in existing JSON.
- `docs/AGENT_NAMING.md` includes naming exclusions and compatibility.
- `CHECKSUMS.sha256` covers every release file except itself; ZIP has one top-level versioned folder.

Acceptance still required: PostgreSQL/Docker, actual worker recovery, Witness roles, real Chrysalis ingress, live providers and account token renewal. CI definitions are not completed CI evidence.
