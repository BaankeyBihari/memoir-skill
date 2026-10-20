# Stream CSV exports
Date: 2026-10-20
Supersedes: none
Decision: Stream report rows with csv.writer over a generator instead of building the file in memory.
Why: Largest report is 2M rows; buffering would need ~1 GB.
Alternatives: Background job + download link (more moving parts than needed today).
Deferred: Background jobs, revisit if exports pass 60 s.
