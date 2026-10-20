# Keep tokens in memory only
Date: 2026-10-16
Supersedes: none
Decision: Hold access tokens in a JS closure, never in localStorage.
Why: localStorage is readable by any injected script.
Alternatives: localStorage (XSS exposure); httpOnly cookie via BFF (needs a new service).
Deferred: BFF pattern, revisit if we add a server-rendered app.
