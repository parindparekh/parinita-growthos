# Hallucination Gate policy 1.2

Deterministic: same input, same decision. Code in `app/gate.py`; every rule has a test in `tests/test_gate.py`
or `tests/test_sentences.py`.

## Rules

| # | Rule | Outcome |
|---|---|---|
| 1 | A `fact` or `quote` claim has no source with a valid URI (`https`, `http`, `doi`, `urn`, `internal`, `chrysalis`, `s3`, `gs`). | Block |
| 2 | A `forecast` claim lacks projection language (expect, estimate, forecast, projected, target, plans to, guidance, outlook ...). | Block |
| 3 | A numeric assertion in title/summary/body is not present in any supported claim. | Block in evidence classes, warn otherwise |
| 4 | A direct quotation (25+ characters) is not present in a sourced `quote` claim. | Block in evidence classes, warn otherwise |
| 5 | A superlative or absolute (#1, largest, fastest, world's first, best-in-class, guaranteed ...) is not present in a supported claim. | Block for high-risk, warn otherwise |
| 6 | **Sentence accounting.** An assertive sentence has neither a supported claim nor a reviewer disposition. | Block in evidence classes, warn otherwise |
| 7 | Classification is `investor`, `regulated`, `legal`, `health` or `financial` and no approval is bound to the current `content_hash`. | Block |
| 8 | Title or body is empty. | Block |

- **Evidence classes** = the five high-risk classes + `GATE_EVIDENCE_CLASSES` (default `pr,social`).
- **Supported claim** = sourced `fact`/`quote`, or labeled `forecast`. `opinion` and `internal` claims never count.

## Sentence accounting (rule 6)

v1.1 could only see sentences that contained a number, a quotation or a superlative. "Customers love it",
"Acme is a launch partner" and "The platform is SOC 2 certified" passed unexamined. In 1.2 every sentence in the
title, summary and body gets exactly one status:

| Status | Meaning | How it gets there |
|---|---|---|
| `covered` | A supported claim stands behind it. | The claim lists the sentence's hash in `covers` (explicit link), **or** at least `GATE_SENTENCE_MATCH` (default 60%) of the sentence's content words appear in one supported claim (lexical match). |
| `waived` | A reviewer decided it needs no evidence. | `PUT /v1/content/{id}/assertions/{hash}/disposition` with `opinion`, `boilerplate` or `not_factual`. Recorded with the reviewer's identity, shown as "stet" in the console, audited. |
| `exempt` | It asserts nothing. | Questions, calls to action ("Learn more at ..."), contact lines, one-word labels, short headings, separators. Deliberately narrow. |
| `open` | Unaccounted. | Everything else. This is what rule 6 acts on. |

- A disposition is bound to the hash of the sentence text. Edit the sentence and the decision is void.
- Who may waive: `GATE_WAIVER_ROLE` (default `approver`). With SSO on, it must be an SSO identity. In production,
  the author or last editor of high-risk content cannot waive its sentences.
- `GATE_SENTENCE_MODE=block|warn|off`.
- The ledger also carries a `suggestion` for open sentences (`opinion` when it sees first-person stance wording,
  otherwise `needs_evidence`). Suggestions are hints for the reviewer and never change the outcome.

## Where the gate runs

1. Checks / `gate` agent: sets `approved` or `blocked`.
2. `POST /approve`: re-evaluated with the new approval.
3. `POST /publish`: re-evaluated immediately before any delivery, for every adapter; refusals are audited.
4. `GET /feeds/{slug}`: every candidate item is re-evaluated at render time.

## Model-generated copy

Signal / Podcast / Amplify output from a model is stored only if it has the expected shape and introduces no
number, quotation, superlative or URL absent from the governed master, and no sentence built mostly from words
the master never uses (vocabulary grounding, same threshold as rule 6). Otherwise the deterministic fallback is
stored and the offending fragments are recorded in `rejected_ungrounded`. Copy is pinned to the `content_hash` it
was generated from; provider adapters only use copy for the current version.

## Known limits

- Matching is lexical. A claim that reuses a sentence's words covers it even if the source says something
  different; a faithful paraphrase with different words does not match and needs an explicit `covers` link.
- A source reference is checked for form, not truth or reachability.
- The splitter and the exemption rules are English-oriented heuristics. They over-flag rather than under-flag.
- Sentence accounting makes reviewers decide; it does not decide for them. A reviewer can waive a factual
  sentence as "opinion". That decision is attributed and audited, not prevented.
