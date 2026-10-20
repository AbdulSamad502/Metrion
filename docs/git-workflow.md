# Git workflow

Three long-lived local branches. Everything else is temporary.

| Branch | Purpose | Receives |
|---|---|---|
| `main` | Core Metrion: engine, agents (CEO, CFO, CI, PI, Slim CMO), backend, frontend, migrations, CI V3. | Reviewed changes only. |
| `feat/pnl-calculator-and-expense-tracker` | Profit Calculator and the Expense Tracker (ledger tables, routes, UI, specs). | Its own work, plus `main`. |
| `frontend-ui-ux` | Frontend UI/UX work and design tooling (`.agents`, `.claude/skills`, `.codex`, `.github/skills`, `DESIGN.md`, `PRODUCT.md`, design rules in `CLAUDE.md`). | Its own work, plus `main`. |

## Integration direction

```
main ──merge──▶ feat/pnl-calculator-and-expense-tracker
main ──merge──▶ frontend-ui-ux
```

- Feature branches **pull `main` in** regularly so they never drift. Do this often; small merges conflict less.
- `main` is **never** updated automatically from a feature branch. When a feature branch is ready, open a pull request into `main` (or merge by hand after review and a green test run). Do not script it.
- `feat/pnl-calculator-and-expense-tracker` and `frontend-ui-ux` do not merge into each other. If the UI branch needs an expense screen, it takes it from `main` after the P&L branch has landed there.
- File ownership: Expense Tracker code (`expense_ledger*`, `components/expenses/`, `app/dashboard/cfo/expenses/`, `lib/expenseLedger.ts`, calc-engine migration `*_expense_ledger`) belongs to the P&L branch. Design tooling and design rules belong to `frontend-ui-ux`. Shared files (`navigation.ts`, contract JSONs, `main.py` router list) are resolved on whichever branch is merging `main`, never by copying between feature branches.

## Before any update: check the starting state

```bash
git status --short            # must be empty, or you know exactly what is uncommitted
git branch --show-current
git fetch origin              # updates remote-tracking refs only; changes no local branch
git log --oneline --left-right --count main...origin/main     # behind/ahead of the remote
git stash list                # stashes are not branches; review them, do not apply blindly
```

Never run `git reset --hard`, `git clean -fd`, or a force-push to get a clean tree. If the tree is dirty, commit it (a `wip:` commit is fine) or copy it aside first:

```bash
git diff HEAD --binary > ../metrion-wip.patch
```

## Updating `main`

```bash
git switch main
git merge --ff-only origin/main      # fails safely if main has diverged; then stop and look
```

## Updating a feature branch from `main`

```bash
git switch feat/pnl-calculator-and-expense-tracker     # or frontend-ui-ux
git merge main
# resolve conflicts (below), run the checks, then:
git commit                                              # only if the merge stopped for conflicts
```

Use a merge, not a rebase: both branches may be shared, and a merge never rewrites commits.

## Conflicts

1. `git status` lists the unmerged files. Fix each by hand, keeping both sides' intent (e.g. a router list gets both routers).
2. **Generated files are not hand-merged.** Take either side, then regenerate:
   - `frontend/test-support/requestContract.json`: `python backend/scripts/export_request_contract.py` (needs the backend env vars below).
   - `frontend/test-support/responseContracts.json`: from `frontend/`, `UPDATE_CONTRACTS=1 npx vitest run test-support/responseContracts.test.ts`.
3. `git diff --name-only --diff-filter=U` must be empty and `grep -rn '<<<<<<<' .` must find nothing before you commit.

## Migrations

- Each package owns its own Alembic chain (`calc-engine`, `data-foundation`, `competitor-intelligence`, `cfo`, `product-intelligence`, `slim-cmo`, `backend`). Run `python -m alembic heads` in each: there must be exactly one head.
- Two branches adding a revision to the same chain is the one real conflict: re-point the later migration's `down_revision` at the other's revision and renumber the file; never edit a migration that is already on `main`.
- Upgrade order: calc-engine, data-foundation, competitor-intelligence, cfo, product-intelligence, slim-cmo, **then** backend (backend migration `20261013_0020` needs slim-cmo's `cmo_generation` table).
- Check `upgrade head`, `downgrade base`, `upgrade head` on a **scratch** database only.

## Safe local test database

Use a throwaway container on port **5544** (the CI package's owner-role tests refuse any other port). Never point tests at the shared development database on 5432.

```bash
docker run -d --name ci-v3-pg -e POSTGRES_USER=metrion -e POSTGRES_PASSWORD=ci_scratch_pw -e POSTGRES_DB=metrion_ci \
  -p 5544:5432 -v "$PWD/docker/postgres-init:/docker-entrypoint-initdb.d:ro" pgvector/pgvector:pg16
```

Full setup and environment variables: `docs/ci-v3-local-testing.md`. Keep `.venv-ci/`, `.env` files and credentials out of commits (they are ignored).

## Verify consistency after an update

```bash
git status --short                                   # clean
git branch -vv                                       # three product branches, expected upstreams
git merge-base --is-ancestor main HEAD && echo "main is contained"     # on a feature branch
git log --oneline main..HEAD                         # only this branch's own commits
git diff --name-only --diff-filter=U                 # no unmerged files
```

Then run the checks for what you touched: `pytest` in the changed package(s), `mypy` in `packages/competitor-intelligence`, and in `frontend/`: `npx tsc --noEmit`, `npm run lint`, `npm test`, `npm run build`.

## Remote policy

Do not push, force-push, rename or delete remote branches without an explicit decision. `git push` only on the branch you intend, after the checks pass.
