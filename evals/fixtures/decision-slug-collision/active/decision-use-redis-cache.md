# Use Redis for session cache
Date: 2026-08-12
Supersedes: none
Decision: Store web sessions in Redis with a 30-minute sliding TTL.
Why: Sessions must survive app restarts and be shared across 4 instances.
Alternatives: Signed cookies (4 KB limit, can't revoke).
Deferred: none
