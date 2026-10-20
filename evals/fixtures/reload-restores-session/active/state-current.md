# Session State
Updated: 2026-10-18
## Goal
- Migrate login from session cookies to OAuth2 with PKCE
## Completed
- Authorization-code flow with PKCE works end to end in dev
## Blocked/Pending
- Access tokens expire after 5 minutes and the SPA does not refresh them yet
## Next Action
- Implement silent token refresh in src/auth/refresh.ts
