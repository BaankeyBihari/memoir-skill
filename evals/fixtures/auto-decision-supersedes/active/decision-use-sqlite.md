# Use SQLite for the job queue
Date: 2026-02-10
Supersedes: none
Decision: Store job-queue state in a single SQLite file.
Why: One worker, zero ops; good enough for the prototype.
Alternatives: Postgres (more to operate for one worker).
Deferred: Revisit when we run more than one worker.
