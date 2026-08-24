# CI and automatic merge

Every pull request and every push to `main` runs the `Deployment CI` workflow.
It is intentionally independent of file-path filters so protected-branch checks
are always reported, including for documentation-only pull requests.

## Required checks

The workflow publishes three stable checks:

- `Shell scripts`: parses every Bash script and runs all `scripts/test-*.sh`
  regression tests.
- `Python unit tests`: discovers and runs `scripts/test_*.py` with Python 3.12.
- `Compose configuration`: renders every `compose/docker-compose*.yml` file
  against `.env.example` without pulling images or starting containers.

The `main` branch requires all three checks, requires the pull request branch to
be current with `main`, and requires all review conversations to be resolved. A
failed, cancelled, skipped, or missing required check blocks both manual and
automatic merges.

The existing `Monitoring rules / Prometheus rules` workflow remains scoped to
monitoring changes. It provides an additional check when files under
`monitoring/` or its workflow change, but it is not a global required check
because path-filtered checks are absent on unrelated pull requests.

## Using automatic merge

Repository auto-merge is enabled. After review, enable it on a pull request:

```bash
gh pr merge <number> \
  --repo shikanon/lens-rhyme-deployment \
  --auto \
  --squash \
  --delete-branch
```

GitHub waits for the required checks and for the branch to be current before
merging. Enabling auto-merge is not a substitute for review: do it only after
the pull request content, deployment impact, and rollback path have been
approved.

## Running the same checks locally

From the deployment repository root:

```bash
bash -n scripts/*.sh scripts/lib/*.sh

for test_script in scripts/test-*.sh; do
  bash "$test_script"
done

python3 -m unittest discover -s scripts -p 'test_*.py'

for compose_file in compose/docker-compose*.yml; do
  docker compose --env-file .env.example -f "$compose_file" config --quiet
done
```

Compose validation checks interpolation, service references, volumes, networks,
and the final merged model. It does not pull images, connect to a server, or
prove that a production rollout is healthy. Continue to use the deployment
smoke/prerelease gates for release validation.

## Changing CI

Keep job names stable because branch protection refers to their check names.
When adding a new deployment format, add a validation step here before making
that check required. Pin third-party actions to full commit SHAs and retain
`permissions: contents: read` unless a reviewed workflow change requires more.
