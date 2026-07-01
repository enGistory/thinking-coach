# P11 Release Acceptance Checklist

Date: 2026-06-25
Status: DRAFT, awaiting real release environment and target-device acceptance

## Preconditions

- Use a real but uncommitted `infra/env.production`; never copy values into Git,
  logs, screenshots, or task reports.
- Put TLS files under ignored `infra/certs/fullchain.pem` and
  `infra/certs/privkey.pem`.
- Use only fake or explicitly approved non-sensitive training data until the
  owner authorizes a production run.
- Confirm 3-4 test accounts, target devices, domain, HTTPS certificate, Aliyun,
  Bocha, OSS, and Web Push credentials are available.
- Do not proceed if any step requires reading real `.env` values in Codex,
  operating a production database, or deleting production data without explicit
  authorization.

## Local Gates

- Last local refresh: 2026-06-25 on branch `codex/p11-release`. Rerun before
  final release signoff if code or release config changes.
- Current backend refresh note: after the worker error-code hardening, bare
  `uv lock --check` still fails in a shell with no `UV_*` variables because uv
  wants to resolve against different registry metadata. The committed
  `uv.lock` is pinned to `https://mirrors.aliyun.com/pypi/simple`; the
  reproducible online gate is to set `UV_DEFAULT_INDEX` to that registry before
  running the check. `UV_INDEX_URL` is not equivalent for this lockfile
  consistency check. Unapproved lockfile rewrites remain out of scope.
- [x] `cd services/backend && set UV_DEFAULT_INDEX=https://mirrors.aliyun.com/pypi/simple&& uv lock --check`
- [x] `git status --short -- services/backend/uv.lock` after the online lock
  check was empty
- [x] `cd services/backend && uv lock --check --offline`
- [x] `cd services/backend && uv run python scripts/verify_dependency_policy.py`
- [x] `cd services/backend && uv run ruff check .`
- [x] `cd services/backend && uv run ruff format --check .`
- [x] `cd services/backend && uv run mypy app`
- [x] `cd services/backend && uv run pytest -q`
- [x] `pnpm --dir apps/web lint`
- [x] `pnpm --dir apps/web type-check`
- [x] `pnpm --dir apps/web test`
- [x] `pnpm --dir apps/web build`
- [x] `pnpm --dir apps/web scan-dist-secrets`
- [x] `docker compose --env-file infra/env.production.example -f infra/docker-compose.prod.yml config --quiet`
- [x] `bash -n infra/scripts/backup-postgres.sh infra/scripts/restore-postgres.sh`
- [x] Temporary pgvector run of
  `cd services/backend && .venv\Scripts\pytest.exe -q tests\test_release_checkpointer_p11.py`
- [x] `git diff --check`

## Release Environment Preflight

- [ ] `cd services/backend && uv run python scripts/validate_release_env.py ../../infra/env.production`
- [ ] Confirm release preflight rejects placeholder, short, local-only, or
  non-HTTPS env values without printing the configured secret values.
- [x] Local release preflight regression rejects BOM or invalid UTF-8 env files
  before value validation, and does not print configured secret values.
- [x] Local release preflight regression rejects duplicate env variable names
  before value validation, and reports only variable names.
- [x] Local release preflight regression rejects malformed env lines and invalid
  variable names before value validation, without echoing the configured values
  or invalid left-hand-side text.
- [x] Confirm `infra/env.production`, `infra/certs/`, and `backups/` are ignored:
  `git check-ignore infra/env.production infra/certs/fullchain.pem infra/certs/privkey.pem backups/postgres/thinking-test.dump`
- [x] Confirm the frontend build artifact contains no model keys, API keys, OSS
  secrets, VAPID private keys, or real signed URLs.
- [x] Local frontend regression verifies `scan-dist-secrets` reports secret value
  matches by variable name only and does not print the actual secret value.
- [x] Local frontend regression verifies `scan-dist-secrets` flags Aliyun OSS
  v1, Aliyun OSS v4, and S3-compatible signed URL markers without printing the
  signed URL or signature value.
- [x] Local release manifest regression records the Alembic migration head,
  supplied image tag, Git revision/status, and release artifact hashes, and can
  write the same non-secret JSON to an explicit evidence file without reading or
  printing secret env values.
- [x] Local release manifest output-safety regression rejects blank or
  whitespace-containing image tags, non-JSON output paths, source/config
  overwrite targets, and private release artifact paths such as certs, backups,
  and secrets.
- [ ] Record the migration head and current image tag before deployment.

## Deployment Smoke

- [ ] Start the stack only after explicit approval:
  `docker compose --env-file infra/env.production -f infra/docker-compose.prod.yml up -d --build`
- [ ] Confirm `http://<domain>/` redirects to HTTPS.
- [ ] Confirm `https://<domain>/api/v1/health` returns `ok` or a clearly
  understood non-sensitive degraded reason.
- [ ] Confirm Nginx serves the PWA and proxies `/api/`.
- [ ] Confirm uploads up to the configured release limit are accepted and larger
  files fail closed.
- [ ] Confirm `api`, `worker`, and `scheduler` start without printing secrets.

## Provider Smoke

- [ ] LLM: `cd services/backend && uv run python -m app.scripts.smoke_ai --task llm`
- [ ] Embedding:
  `cd services/backend && uv run python -m app.scripts.smoke_ai --task embedding --dimensions 1024`
- [ ] TTS: `cd services/backend && uv run python -m app.scripts.smoke_ai --task tts`
- [ ] ASR:
  `cd services/backend && uv run python -m app.scripts.smoke_ai --task asr --audio-url <short-lived-non-sensitive-url>`
- [ ] Bocha search live smoke:
  `cd services/backend && RUN_LIVE_SEARCH_TESTS=1 uv run pytest -q tests/test_source_question_provider_p08.py::test_live_bocha_search_provider_smoke`

## P0 E2E Acceptance

- [ ] Create or confirm 3-4 USER accounts and one ADMIN account.
- [ ] Each USER can log in, enable notifications, and has isolated current
  training state.
- [ ] The system schedules an unpredictable strike inside an allowed window.
- [ ] Before acceptance, the user sees no full question text, sources, target
  defect, domain, or answer skeleton.
- [ ] After acceptance, the question has real source summary and the first answer
  can be recorded only once.
- [ ] Complete first answer, at least one follow-up, and final answer on a target
  phone/browser.
- [ ] Worker completes transcript, metrics, LangGraph resume, evaluation report,
  defect occurrence sync, and final `COMPLETED` state.
- [ ] Report shows logic, speech, adaptability, final score, quote/time evidence,
  historical defect context, appeal status, and source summary.
- [ ] Provenance after completion shows source metadata and claim mappings.
- [ ] Weekly report generation is deterministic and user-scoped.
- [ ] Duplicate, transcript, source, evaluation, and defect-classification
  appeals can be submitted and show handling status.
- [ ] Another USER cannot access the first user's training, audio, report,
  provenance, defects, appeals, export, or deletion status.

## Privacy And Deletion

Local evidence: a fresh temporary pgvector run passed
`tests/test_migrations_p11.py tests/test_release_privacy_p11.py` with 19 tests.
This covers Alembic upgrade/downgrade/upgrade plus the database-level and HTTP
privacy/export/deletion assertions below. Deletion-status lookup uses request id
+ proof code without a bearer token, keeps the proof code out of the URL, and
renders the proof lookup input as a non-autocompleted password field.

- [x] Frontend destructive deletion flows best-effort clear the local
  IndexedDB `pending-audio` cache and pending attempt reference after successful
  account or single-training deletion requests.
- [x] Backend destructive deletion flows do not unlink paths outside
  `audio_root`; invalid or non-file audio references are counted separately and
  do not block business data deletion.
- [x] Already successful account-deletion requests cannot be downgraded to
  `FAILED` by later retry/failure handling; proof status remains successful and
  no FAILED audit is added after success.
- [x] Personal export includes account/training/report/source/defect/appeal/audit
  metadata and excludes audio bytes, private audio paths, signed URLs, model
  private outputs, secrets, and other users' data.
- [x] Single-training deletion removes voice attempts, audio files, transcripts,
  report/issues, defect occurrences, duplicate complaints, ordinary appeals,
  orphan question/source/vector rows, and related checkpoints; deletion proof
  distinguishes database audio references from physical files actually removed.
- [x] Account deletion immediately disables login, revokes refresh tokens, queues
  `DELETE_ACCOUNT`, and returns a one-time proof code.
- [x] Account deletion worker clears business data, vectors, audio files, related
  AI jobs/model runs, and LangGraph checkpoint rows for that user; deletion
  proof distinguishes database audio references from physical files actually
  removed.
- [x] Successful account deletion retains only proof hash, deletion counts, and
  non-PII user hash; deletion request and request-scoped audit events do not
  retain the raw user UUID.
- [x] Deletion status can be checked with request id + proof code without a bearer
  token, and wrong proof codes fail closed.
- [ ] Logs around deletion do not contain raw answers, audio paths, signed URLs,
  JWTs, API keys, or proof code values.
- [x] Local worker error-code regression rejects unsafe exception `code` or
  `error_code` values before they can be persisted into job failure fields.
- [x] Local deletion-failure audit regression sanitizes unsafe deletion
  `error_code` values, so proof codes, refresh tokens, audio paths, signed URLs,
  signature values, and API keys are not persisted into deletion request status
  or privacy audit error fields.
- [x] Unified error responses filter sensitive HTTPException detail extras such
  as proof codes, tokens, authorization, audio paths, signed URLs, secrets, and
  API keys.

## Backup And Restore

Local evidence: a temporary fake release-rehearsal Compose project has verified
`backup-postgres.sh` dump + `.sha256` generation and `restore-postgres.sh`
recovery into the same test database. Formal release signoff still requires the
approved release env and target deployment context below.

- [ ] Run `infra/scripts/backup-postgres.sh` with `COMPOSE_ENV_FILE` pointing to
  the approved release env.
- [ ] Confirm the dump and `.sha256` sidecar are written under ignored `backups/`.
- [x] Local backup-script regression verifies failed `pg_dump` writes only a
  temporary file and leaves no final `.dump`, temp dump, or `.sha256` sidecar
  behind.
- [x] Local backup-script regression verifies checksum generation is required
  and atomic; failed checksum generation leaves no final `.dump`, temp dump, or
  `.sha256` sidecar behind.
- [x] Local backup-script regression verifies CRLF env values for
  `POSTGRES_USER` and `POSTGRES_DB` are normalized before reaching `pg_dump`.
- [x] Confirm backup retention keeps at least the newest 7 daily backups and 4
  older weekly snapshots, and prunes matching stale `.sha256` sidecars.
- [ ] Restore the dump into a fresh non-production database with
  `infra/scripts/restore-postgres.sh <dump>`.
- [ ] Confirm restore rehearsal uses `APP_ENV!=production`; production restore
  requires separate explicit approval plus `RESTORE_ALLOW_PRODUCTION=1`.
- [x] Local restore-script regression verifies CRLF env values for
  `RESTORE_ALLOW_PRODUCTION`, `POSTGRES_USER`, and `POSTGRES_DB` are normalized
  before the production guard and `pg_restore` invocation.
- [x] Confirm checksum verification runs before `pg_restore` when the sidecar is
  present.
- [x] Local restore-script regression requires a `.sha256` sidecar by default
  before reading the release env or reaching Docker/`pg_restore`; the explicit
  `RESTORE_ALLOW_MISSING_CHECKSUM=1` override still leaves the production
  restore guard active.
- [x] Local restore-script regression verifies checksum sidecars are bound to
  the selected backup path itself; a sidecar containing another dump's valid
  hash fails before reading release env or reaching Docker/`pg_restore`.
- [ ] Run migrations and `/api/v1/health` against the restored database.
- [ ] Confirm restored data is sufficient for the P0 report/provenance/deletion
  checks and contains no unexpected secret material.

## Review And Signoff

- [ ] Run an independent `/review` in a host that exposes the required
  AskUserQuestion workflow, or explicitly approve a documented substitute.
- [ ] Resolve or record all high/medium findings before marking P11 verified.
- [ ] Update `docs/progress.md` and `docs/handoffs/P11-release-handoff.md` with
  exact commands, exit codes, target devices, and remaining risks.
- [ ] Do not mark P11 `VERIFIED` until real target-device P0 E2E, backup restore,
  deletion proof, HTTPS deployment, and review evidence all exist.
