# Move login to OAuth2 with PKCE
Date: 2026-10-15
Supersedes: decision-use-session-cookies.md
Decision: Authenticate the SPA with the company IdP using the OAuth2 authorization-code flow with PKCE.
Why: Security requires SSO and the cookie setup can't do cross-domain SSO.
Alternatives: Implicit flow (deprecated by OAuth 2.1).
Deferred: Refresh-token rotation, revisit before production launch.
