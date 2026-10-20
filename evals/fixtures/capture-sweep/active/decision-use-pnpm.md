# Use pnpm workspaces
Date: 2026-10-19
Supersedes: none
Decision: Manage the monorepo with pnpm workspaces.
Why: Strict node_modules catches undeclared dependencies; installs are 3x faster than npm here.
Alternatives: npm workspaces (hoisting hides missing deps); Yarn Berry (PnP breaks two of our tools).
Deferred: none
