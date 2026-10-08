# Local build verification — October 8, 2026

The supplied archive's original checksum manifest verified all 140 entries before changes.

Verified on Windows with Python 3.12:

- Hash-locked development dependency installation succeeded after adding Windows platform support: exclude uvloop on Windows/Cygwin; include hash-pinned colorama 0.4.6 and tzdata 2026.5 on Windows.
- `pip check`: no broken requirements.
- Main regression suite: **299 passed, 3 skipped, 0 failed**. The three skips require a separate MCP SDK interpreter.
- Those three SDK interoperability cases ran separately with MCP 2.2.0: **3 passed, 0 skipped, 0 failed**.
- Thus all **302 application test cases passed across two runs**. See `local-windows-pytest.xml` and `local-windows-sdk.xml`.
- Real application startup, `/health`, console loading and local admin sign-in passed.

The new local launcher binds to loopback and uses an isolated development database and generated access key, ignored by Git. It is not the production deployment entrypoint.

Not verified here: Docker image build, PostgreSQL target acceptance, production worker recovery, live Witness/Chrysalis and provider-account integrations. Local success is not evidence of a live hosted deployment.

The original packet's other evidence files are historical. The dependency inventory and checksum manifest have been regenerated for this repository import.
