<!-- ai4educ:shared-rules:start hash=2b63ced31d4b -->
# Development Rules

- Before starting, check `git status`, the current branch, and repository instructions.
- Do not overwrite or remove unrelated existing changes.
- Never commit directly to `main`/`master` (only exception: the ai4educ sync commit, see Pull requests): every change goes on a branch created from an up-to-date default branch, named `feature/...`, `fix/...`, `refactor/...`, `docs/...`, or `chore/...`.

## Commits

- At the end of every coding session, create one or more commits and push them to GitHub.
- Keep commits atomic: one logical type of change per commit.
- Do not mix features, bug fixes, refactoring, formatting, dependency updates, and documentation unless they are inseparable.
- Use clear Conventional Commit messages, for example:
  - `feat: add CSV export`
  - `fix: correct attendance calculation`
  - `refactor: simplify validation logic`
  - `docs: update setup instructions`
  - `chore: update dependencies`
- Review changes with `git diff` and `git diff --staged` before committing.
- Do not use vague commit messages such as `update`, `fix`, or `changes`.

## Pull requests (solo developer)

The user works alone and reviews and merges from the GitHub mobile app: each pull request is the readable chapter of the project history.

- When the work is done, push the branch and open a pull request to the default branch with `gh pr create`. Give the user the PR link.
- PR title in Conventional Commit form (`feat: ...`, `fix: ...`): it is what the app lists and what the merge commit keeps.
- PR body short and readable on a phone: Obiettivo, Modifiche principali, Test eseguiti, Passi manuali (sudo, deploy), Issue collegate (`Closes #N`).
- Do not merge the PR yourself unless the user explicitly asks. The user merges from the app with "Create a merge commit".
- When the user says it is merged, verify with `gh pr view <N> --json state` before switching branch (the app sometimes does not register the confirm), then `git switch <default> && git pull --ff-only` and delete the local branch.
- If the repository has no GitHub remote, keep the branch local and tell the user.
- Exception for the ai4educ sync: `AGENTS.md`/`CLAUDE.md` rewritten by `sync-project.sh` are generated, so they need no PR. Commit only those two files as `chore: sync shared rules` directly on the default branch and push, when the repository is on its default branch and even with its remote; otherwise commit them alone on the current branch. Never mix them with other changes.

## Validation

- Run relevant tests, linting, type checks, formatting checks, and builds before the final commit.
- Add or update tests when changing application behaviour or fixing a bug.
- Clearly report any checks that could not be run and explain why.

## Live dev environment (SSH)

The user often works over SSH from another machine: to see work in progress, use a live dev environment next to production, never production itself.

- Run the app in dev mode with hot reload (e.g. `uvicorn --reload`, `next dev`, `vite`) bound to `127.0.0.1` on dedicated ports, different from production; check they are free first (`ss -ltn`).
- Isolate data: a separate database or data directory (e.g. `<name>_test`), never production data. Point dev to it through dev-only env files (e.g. `.env.development`) so production defaults stay unchanged.
- Do not rebuild or restart production containers (`docker compose up`) to show a change in progress.
- Put the start commands in `scripts/dev-*.sh` and document ports, data, start/stop and limits in `docs/operations/live-dev-environment.md`; reference it from `CONTEXT.md`. Reference implementation: `counselorbot-sbs`.
- Give the user the exact tunnel command and URL, e.g. `ssh -N -L 3107:127.0.0.1:3107 -L 8002:127.0.0.1:8002 <user>@<server>` then `http://localhost:3107`.
- At the end of the session say whether dev processes are still running and how to stop them.

## Docker

- If the project uses Docker, rebuild the relevant images whenever Dockerfiles, Compose files, dependencies, build scripts, environment build variables, or application code copied into the image are changed.
- Use the appropriate command, such as `docker compose up -d --build`.
- After rebuilding, verify container status and inspect logs if needed.
- Do not remove volumes, databases, or persistent data without explicit approval.

## Sudo in deploy (reminder obbligatorio)

- **Nessun agente può inserire una password sudo**: quando un deploy o un aggiornamento include passi sudo (es. `sudo ./update_nginx.sh` in counselorbot-sbs, riavvii di servizi di sistema), l'agente NON può eseguirli.
- **Prima di lanciare un deploy**: avvisare l'utente che al termine dovrà dare a mano il comando sudo e quale comando è.
- **Nel riepilogo finale di ogni deploy**: ripetere sempre il promemoria esplicito con il comando esatto da dare a mano (es. `sudo ./update_nginx.sh`), chiarendo se è obbligatorio o se la config esistente resta valida.
- Non provare workaround (askpass, `-S` con password, echo della password): è sempre l'utente a lanciare il comando sudo.

## Documentation and safety

- Update documentation when changing setup steps, configuration, environment variables, dependencies, APIs, database schema, or operational procedures.
- Never commit secrets, credentials, API keys, `.env` files, or production data. Update `.env.example` when needed.
- Do not use force push, destructive reset, rebase, or cleanup commands without explicit approval.

## End of session

Before finishing:
1. Check `git status`.
2. Run the relevant verification commands.
3. Create separate commits by change type.
4. Push the branch to GitHub and open or update its pull request.
5. Provide a short summary of changed files, checks run, Docker rebuild status, commits created, branch used, PR link, and any remaining issues.
<!-- ai4educ:shared-rules:end -->

## Project Context
Read `CONTEXT.md` for domain knowledge, architecture, conventions, and common tasks.

> GENERATED by ai4educ-shared-config/v1.0 — DO NOT EDIT
> Source: blocks/shared-rules.md (hash: 2b63ced31d4b)
