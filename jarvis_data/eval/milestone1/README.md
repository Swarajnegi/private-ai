# Milestone 1: independent training review and observed baseline

The review gate applies retroactively to JARVIS-generated answers. Capture,
historical conversations, retrieval and parse verdicts remain intact. The parse
rule version is unchanged. Approval is an independent training-quality decision,
not a claim that an old answer describes current runtime facts.

`training_reviews.jsonl` is an append-only fact registry. Exchange identities use
session ID and timestamp; their SHA-256 covers the complete question and answer
as canonical UTF-8 JSON. KB identities use the existing ID and hash the complete
entry, including its provenance. Existing `lineN` KB aliases identify legacy
entries without a numeric ID; moving or changing that entry invalidates its
digest. Session distills require their own KB review because the existing writer
does not retain reliable exchange linkage.

The last appended decision matching identity and digest applies. An absent,
changed, conflicting or unresolvable source is pending. Only independent
`codex/model`, `claude/model`, `antigravity/model` or `owner/name` reviewers can
submit; JARVIS cannot approve its own answers. The writer is an explicit CLI,
not a registered conversational tool. Reviewer identity records the actual
reviewer and is not a cryptographic credential.

All builders, both SFT exports, pipeline audits and the Stage 5 training audit
use `jarvis_core.specialists.training_review`. Derived records declare
`metadata.training_sources`, a list of source records with source paths and
metadata. Exports carry content-bound `metadata.training_review` references;
audits resolve original sources again rather than trusting a saved approval.
Direct source fragments must match original content after existing whitespace
normalization and third-party redaction. Rejections, retractions, parse routing
and evaluation exclusions take precedence. Existing owner-only extractors and
facts supported by the parse extractor's verified owner quotations are retained.

Read-only commands, after sourcing `.runtime/environment.ps1`:

```powershell
.venv/Scripts/python.exe scripts/review_training.py --list --status pending
.venv/Scripts/python.exe scripts/review_training.py --list --session <id> --packets
.venv/Scripts/python.exe scripts/review_training.py --packet .runtime/milestone1/identity.json
```

An identity file contains `{"kind":"exchange","session_id":"...","ts":"..."}`
or `{"kind":"kb","id":123}`. Packets contain the complete source and available
context references. Conflicting sources include complete variants and cannot
be submitted until their provenance is resolved.

Explicit submissions contain `{"verdicts":[...]}`. Every verdict requires
`identity`, current `digest`, `decision` (`approved` or `rejected`), an individual
`rationale`, and a nonempty `evidence_refs` list. Example invocation:

```powershell
.venv/Scripts/python.exe scripts/review_training.py --submit .runtime/milestone1/verdicts.json --reviewer codex/<actual-model>
```

Submission validates the whole batch before appending, serializes concurrent
writers, heals a valid missing newline, fsyncs, and ignores identical repeat
submissions. A torn or malformed review row blocks exports and audits. It is
never silently skipped or automatically deleted.

`baseline.json` records the individually reviewed October 13 session and its
four associated legacy KB copies: 11 reviews, three approvals and eight
rejections. Owner corrections remain available separately. The six cases cover
hardware attribution, unsupported performance claims, missing-file error
classification, repeated reads, continuity loss and ambiguous transcription.
The first five remain unresolved; the sixth has no original audio for a reliable
accuracy judgment. This milestone establishes those cases and prevents their
unreviewed answers from becoming training targets; it does not repair behaviour.

Verification commands:

```powershell
.venv/Scripts/python.exe scripts/test_training_review.py
.venv/Scripts/python.exe scripts/baseline_milestone1.py
.venv/Scripts/python.exe scripts/check_pipeline.py
.venv/Scripts/python.exe scripts/eval_c002.py self-test
.venv/Scripts/python.exe scripts/rebuild_corpora.py
```

The production rebuild enters the existing exclusive maintenance supervisor and
can defer on RAM, battery, competing work, cooldown or retry policy. A deferred
attempt is outstanding production validation, never a completed milestone.
Correctly excluded pending sources are a visible training hold; any ineligible
material still present in a built artifact is an audit failure. Review-registry
changes are included in the corpus freshness fingerprint.

Antigravity's bounded independent test assignment is q056, clarified by q057.
Mail does not start a session. A response and test file are integrated only after
Codex review and rerun; assignment delivery alone is not test evidence.

Production sign-off on 2026-10-14: 22 Codex review/export/writer checks and 20
Antigravity fixture checks reviewed and rerun by Codex pass. All five rebuilt
exports have zero ineligible records; all 36 pipeline invariants pass. The final
supervised rebuild took 64.11 s (5.41 GiB minimum available RAM, 248.11 MiB peak
process-tree commit). The original 947-record client snapshot is byte-identical;
an explicit regression protects it from shared metadata mutation. Live UI,
capture and CPU voice capabilities remain operational. Historical review holds
remain 122 pending / 8 rejected / 3 approved. The unrelated episode-index
catch-up timeout and behavioural baseline failures remain visible.
