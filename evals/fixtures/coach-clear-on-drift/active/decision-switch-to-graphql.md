# Switch invoices to GraphQL
Date: 2026-03-02
Supersedes: decision-use-rest-api.md
Decision: Serve invoices through a GraphQL invoice(id) query and delete the REST endpoints.
Why: Mobile needs invoice plus line items in one round trip.
Alternatives: Keep REST with an include= parameter (mobile team rejected it).
Deferred: none
