# Contributing to CL_agent

Thanks for your interest in improving CL_agent! This document describes how to file issues,
propose changes and run the project locally for development.

> 中文贡献者请直接读下方对照说明，所有流程都同时支持中英文 issue / PR 描述。

---

## Code of Conduct

Be respectful, assume good intent, give actionable feedback. We follow the spirit of the
[Contributor Covenant](https://www.contributor-covenant.org/). Harassment of any kind is not
tolerated.

## Ways to contribute

- **Report a bug** — open a GitHub Issue using the *Bug report* template.
- **Request a feature** — open an Issue using the *Feature request* template.
- **Improve docs** — README, architecture notes and the `docs/knowledge-base` samples are all
  fair game.
- **Submit a PR** — fix a bug, add a feature, or improve test coverage.

## Local development

See the [English Quickstart](README.md#english-quickstart) in the README for the canonical
setup steps. The short version:

```bash
git clone https://github.com/BOBOXERWHITE/CL_agent.git
cd CL_agent
cp .env.example .env
cp frontend/.env.example frontend/.env
docker compose up -d postgres redis minio etcd milvus attu

make backend-install
make frontend-install
```

Run the dev servers in two terminals:

```bash
# terminal 1
cd backend && uvicorn app.main:app --reload

# terminal 2
cd frontend && npm run dev
```

## Branching & commit messages

- Branch from `main`, name your branch `feat/<short-name>`, `fix/<short-name>`, or
  `docs/<short-name>`.
- Use [Conventional Commits](https://www.conventionalcommits.org/) for messages:
  `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`, `perf:`, `ci:`.
- Keep commits focused. One logical change per commit makes review faster.

## Pull request checklist

Before opening a PR:

- [ ] Tests pass locally (`make test`)
- [ ] No new lint warnings (`ruff check backend`, `npm run lint --prefix frontend`)
- [ ] Documentation updated when behaviour, env vars, ports or external services change
      (see `docs/development-rules.md`)
- [ ] No secrets, real API keys, customer data or internal URLs in the diff
- [ ] If you touched ingestion, retrieval or agents, you ran the relevant evaluation
      (`POST /api/evals/runs` or the eval panel in the console)

PR description should include:

- **What** changed and **why**
- A short test plan (manual or automated)
- Screenshots when the change is user-visible

## Testing

| Layer | Command |
| --- | --- |
| Backend | `make test-backend` (or `pytest -q backend/tests`) |
| Frontend unit | `make test-frontend` (or `npm test --prefix frontend`) |
| Frontend build | `npm run build --prefix frontend` |
| Combined | `make test` |

We aim for **80%+ coverage** on new business logic. Pure scaffolding code can be exempt with a
note in the PR description.

## Coding style

- **Python**: PEP 8, type hints required on public functions, formatted by `ruff format`.
- **TypeScript / React**: `eslint` + `prettier` defaults from the repo. Prefer functional
  components and hooks. No class components in new code.
- **SQL**: lower case keywords, snake_case identifiers, explicit column lists in selects.
- **Files**: keep modules under ~400 lines; extract helpers when a file grows past that.

## Reporting security issues

**Do not open a public issue for security problems.** Email the maintainer (see the GitHub
profile of [@BOBOXERWHITE](https://github.com/BOBOXERWHITE)) with a description and, if
possible, a minimal reproduction. We will respond within 7 days.

## License

By contributing you agree that your contributions are licensed under the
[MIT License](LICENSE) of this project.
