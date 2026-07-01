# Git Workflow

## Branch Strategy

- `main` — always deployable. Nothing broken merges here.
- `develop` — integration branch for the current phase (skip this for a solo
  project until you have >1 contributor; merging directly to `main` via PRs
  is fine at your current team size of one).
- `feature/<phase-number>-<short-description>` — e.g. `feature/p1-fastapi-foundation`.
- `fix/<short-description>` — bug fixes outside normal feature work.

**Why branch per phase/feature even solo:** it forces you to keep `main` in a
state you could demo at any time, and gives you a clean diff per PR to review
your own work critically before merging — which is the actual point, not
ceremony.

## Commit Convention — Conventional Commits

```
<type>(<scope>): <short summary>

[optional body — why, not what]
```

Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `perf`, `ci`

Examples:
```
feat(api): add liveness and readiness health endpoints
fix(database): correct asyncpg connection string scheme
docs(architecture): document modular monolith rationale
chore(deps): pin fastapi to 0.111.0
```

**Why this matters beyond style:** `git log --oneline` becomes a changelog
you can actually generate from, and `feat`/`fix` prefixes let you grep history
fast when bisecting a regression six months from now.

## Per-Phase Workflow

1. `git checkout -b feature/p<N>-<description>`
2. Commit in small, working increments — not one giant commit per phase.
3. Before merging: tests pass, `ruff check .` clean, `.env.example` updated
   if new config was added.
4. Merge to `main`, tag the milestone: `git tag -a v0.1.0-phase1 -m "Phase 1: foundation"`.

**Why tag phase boundaries:** lets you `git checkout v0.1.0-phase1` later to
show "this is exactly what existed at end of Phase 1" — useful for a portfolio
walkthrough, and for bisecting "which phase introduced this regression."

## What NOT to do

- Don't commit `.env` (real secrets) — only `.env.example`.
- Don't commit `data/raw/` — datasets belong in `.gitignore` (large, not code).
- Don't squash-merge away your phase history before you've used it for a
  portfolio writeup — you'll want the granular commits to reference later.
