# Summary

<!-- One or two sentences describing what this PR changes and why. -->

## Changes

<!-- Bullet list of concrete changes. Reference files / modules where helpful. -->
-
-
-

## Test plan

<!-- Tick what you actually ran. Add commands and any manual repro steps. -->
- [ ] `make test-backend`
- [ ] `make test-frontend`
- [ ] `npm run build --prefix frontend`
- [ ] Manual smoke test in the operations console
- [ ] Eval run (`POST /api/evals/runs` or eval panel) — required when touching ingestion / retrieval / agents
- [ ] Other: <!-- describe -->

## Screenshots / recordings

<!-- For user-visible changes. Drop images or short clips here. -->

## Checklist

- [ ] Branch is up to date with `main`
- [ ] No secrets, real API keys, customer data or internal URLs in the diff
- [ ] Updated `README.md` / `docs/` when behaviour, env vars, ports or external services changed
- [ ] Conventional commit messages (`feat:`, `fix:`, `docs:`, ...)
- [ ] I read [`CONTRIBUTING.md`](../CONTRIBUTING.md)

## Related issues

<!-- Closes #123, refs #456 -->
