# Retrospective human review

This extension leaves v1.0.0 data, media, findings and legacy export unchanged. It creates a separate edition using existing public media, with no generation or API access. Magic Hour designed and funded the parent dataset and supplies its single API integration. Rubric registration occurs after generation but before human review: this is post-hoc, not a prospective preregistration.

## Prepare and review

```bash
python3 build_release.py --human-review /absolute/private-review-edition
# A sparse checkout can use the unchanged media in another complete checkout:
python3 build_release.py --human-review /absolute/private-review-edition --media-root /absolute/full-dataset
```

1. Preserve the edition directory. `private-randomization.json` is mode 0600; keep it with the coordinator only. Re-running retains its assignment and registration. Changed parent/rubric hashes require a new directory. Never distribute that key before ratings are frozen.
2. Give each human reviewer `blind-packet/` plus their assigned rows from `ratings.csv`. Every opaque MP4 is byte-identical to a completed parent output; the packet contains no model, price, original output filename or model-group order. Read `rubric.json`, the input image and exact motion brief, then watch the full clip.
3. Collect three humans' independent ratings for every complete clip. One must be independent of Magic Hour. Each reviewer discloses affiliation, independence and any prior recognition in `reviewers.csv`. Pseudonyms are R1/R2/R3. Prior exposure to the public dataset can undermine blinding; disclose it, rather than claiming guaranteed blindness.
4. Fill all five dimensions (`pass`, `minor`, `block`), `accepted` (`yes` only when no block), a nonempty decision reason, and timezone-aware ISO review timestamp. Do not change clip keys or rubric versions. Blank rows remain unscored; partly filled or contradictory rows are rejected. No AI/completion/download labels may replace human judgment.
5. Re-run the same export command. Final acceptance/cost metrics and anonymized raw ratings, disclosures and unblinding key appear only after all 174 ratings and the independence disclosure gate are complete. Missing ratings remain unknown. The coordinator must verify actual human identity and independence; the exporter validates records, not the truth of a declaration.

## Data dictionary and publication boundary

- `registration.json`: edition ID, registration timestamp, parent version, post-hoc status, rubric version, parent result/design/rubric SHA256 hashes and commitment hash for the private assignment. Fieldwork timestamps remain in parent `results.jsonl`; scoring timestamps remain in ratings.
- `all-attempts.csv`: all 60 unique run IDs, scenarios, requested model labels, repeats, technical status, exact completed-output SHA256 and final charged customer credits. Failed attempts have no output hash or human quality rating.
- `ratings.csv`: each opaque clip × reviewer with rubric version, five dimensions, binary decision, reason and scoring timestamp. No personal reviewer names or contact details; disclosures/reasons must not contain personal data.
- `reviewers.csv`: pseudonym, disclosed affiliation, declared independence and prior recognition. Public only at complete coverage.
- `unblinding-key.json`: clip key → exact run ID/output SHA256. Public only at complete coverage; independent users can then join ratings to unchanged parent rows and reproduce summaries offline.
- `summary.json` / `summary.csv`: readiness and exact rating counts; per-model attempt/completion counts and final customer charges. `accepted`, `acceptance_yield`, `acceptance_among_completed` and `credits_per_accepted_clip` are absent while unscored. Majority acceptance requires at least two of three yes ratings.
- `manifest.json`: explicit SHA256 allowlist of published files. Publish only listed files plus the manifest, never the entire edition directory or repository. The private key, raw coordinator state, blind packet and arbitrary files are excluded. `DATA_DICTIONARY.md` and `rubric.json` document the released contract.

Technical completion = completed/all attempts. Brief acceptance yield = majority-accepted/all attempts. Acceptance among completed = majority-accepted/completed. Credits per accepted clip = final charged credits across all attempts (including rejected clips and failed charges)/accepted clips; zero accepted clips gives null, never zero cost. Parent failure charges are already final after refunds; preserve that treatment. Shared source-image generation cost is not recorded and is excluded separately. Customer credits are not provider COGS or historical billed USD; no dollar conversion is supplied.

No ranked winner, significance claim or general reliability league is supported by this four-scenario pilot. Publication of acceptance findings waits for completed human review and factual claim review. Never overwrite the immutable v1.0.0 release with this edition.
