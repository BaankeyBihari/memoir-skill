# Move tax logic into billing/tax.py
Date: 2026-10-20
Supersedes: none
Decision: Consolidate all tax calculation into a new billing/tax.py; other billing modules call it.
Why: Tax rules are duplicated across 3 files and drifted twice this quarter.
Alternatives: Leave duplicates and add tests (doesn't stop drift).
Deferred: none
