# P11 Release Handoff

Date: 2026-06-25
Branch: `codex/p11-release`
Status: IN_PROGRESS

## Implemented

- Added Alembic revision `0010_release_privacy` for `weekly_report`,
  `privacy_deletion_request`, `privacy_audit_event`, and `appeal.target_json`.
- Added current training report API:
  `GET /api/v1/trainings/{id}/report`.
- Added unified appeal status API:
  `GET /api/v1/trainings/{id}/appeals`.
- Extended ordinary appeals to four types:
  `transcript`, `source`, `evaluation`, `defect_classification`.
- Added admin appeal list/review APIs:
  `GET /api/v1/admin/appeals`,
  `POST /api/v1/admin/appeals/{id}/review`.
- Hardened the admin appeal queue so `GET /api/v1/admin/appeals` only returns
  `OPEN` appeals, keeping reviewed appeals out of the release handling queue.
- Added deterministic weekly reports:
  scheduler generation plus `GET /api/v1/me/weekly-reports`.
- Added personal data export:
  `GET /api/v1/me/export`.
  Export now includes source bundle/source/claim metadata and privacy audit
  metadata, while excluding audio paths, audio bytes, signed URLs, model run
  private outputs, and other users' sessions. It also exports
  transcript-correction history under the owning voice attempt.
- Added single training deletion:
  `DELETE /api/v1/me/trainings/{id}`.
- Added account deletion request and proof status:
  `DELETE /api/v1/me`,
  `POST /api/v1/privacy/deletion-status`.
- Added `DELETE_ACCOUNT` worker job that removes business data, audio files,
  related AI jobs, and LangGraph checkpoint rows by session `thread_id`.
- Privacy deletion now deletes related `model_run` rows before removing matching
  `ai_job` rows, so source/question model audit records cannot be orphaned by
  `ON DELETE SET NULL`.
- Account deletion proof coverage now includes user-only `PREPARE_QUESTIONS`
  jobs and their model runs, not only session/attempt-bound jobs.
- Privacy deletion counts and removes ordinary appeals and duplicate complaints
  for both single-training deletion and account deletion, so release deletion
  proof covers these user-visible dispute records as well.
- Privacy deletion counts now also include `transcript_corrections`, so STT
  correction history is explicitly covered by P11 deletion proof instead of
  relying only on implicit cascade behavior.
- Single-training deletion proof counts now also include orphan question child
  rows: `question_claim_maps`, `question_fingerprints`, `question_rubrics`,
  `question_sources`, and `source_claims`. The regression covers both
  question-bound and session-bound rubrics.
- Account deletion proof counts now explicitly cover more user-scoped business
  tables that are removed by cascade: refresh tokens, training policies, push
  subscriptions, source bundles, question sources/claims, questions, claim maps,
  fingerprints, rubrics, dedupe checks, template denylists, defect profiles,
  weekly reports, defect occurrences, and defect evidence.
- Successful account deletion now anonymizes retained proof records: the
  deletion request clears `user_id_snapshot`, request-scoped audit events clear
  `user_id_snapshot`, and account deletion audit `target_id` values are replaced
  with the stored `user_id_hash`.
- Deletion proof status now compares stored proof hashes with
  `secrets.compare_digest`, so the unauthenticated post-deletion status endpoint
  does not use ordinary string equality for proof-code validation.
- Backup dumps now write a portable `.sha256` sidecar next to the dump, and
  restore requires the sidecar by default before running `pg_restore`. Legacy
  restore rehearsals without a sidecar require the explicit
  `RESTORE_ALLOW_MISSING_CHECKSUM=1` override.
- Restore script now refuses to run destructive `pg_restore --clean` against
  `APP_ENV=production` unless `RESTORE_ALLOW_PRODUCTION=1` is explicitly set,
  and normalizes CRLF-sourced `APP_ENV`, `RESTORE_ALLOW_PRODUCTION`,
  `POSTGRES_USER`, and `POSTGRES_DB` values before checking the guard or invoking
  `pg_restore`.
- Backup script now sets `umask 077` before creating the backup directory and
  dump, so generated backup files are private by default.
- Backup script now normalizes CRLF-sourced `POSTGRES_USER` and `POSTGRES_DB`
  values after sourcing the release env file, matching the restore script's
  Windows-edited env handling before invoking `pg_dump`.
- Backup script now prunes old `thinking-*.dump` files after a successful
  backup while retaining at least the newest 7 daily backups and 4 older weekly
  snapshots. Pruning is limited to the configured backup directory and removes
  matching `.sha256` sidecars with the pruned dump; unrecognized manual dump
  names are retained.
- Manual review hardening made report/state source summary lookup explicitly
  user-scoped when resolving `training_session.question_id`, avoiding accidental
  cross-user source summary exposure if a session is ever mis-associated with
  another user's question.
- Manual review hardening also made the remaining question lookup consumers
  explicitly user-scoped: duplicate complaint `similar_question_id` validation,
  random-strike accept, and the voice graph's question text lookup. The
  regression test now proves a corrupted session cannot expose or mark another
  user's READY question.
- Manual review hardening made source appeal target validation require the
  session question to belong to the training owner before accepting a source or
  claim target. The regression proves a corrupted session cannot validate
  another user's question source as an appeal target.
- Added production deployment artifacts:
  `infra/docker-compose.prod.yml`,
  `infra/nginx/Dockerfile`,
  `infra/nginx/default.conf`,
  `infra/env.production.example`.
- Production Nginx HTTPS responses now set baseline security headers on API,
  static asset, and SPA fallback responses:
  HSTS, `X-Content-Type-Options`, `X-Frame-Options`, and `Referrer-Policy`.
- Release configuration coverage now also locks the private-audio boundary:
  Nginx does not mount `audio_data`, does not reference `/data/audio`, and has
  no static `/audio` location.
- Release configuration coverage now locks the public port boundary: only Nginx
  publishes host ports `80` and `443`; Postgres, API, worker, and scheduler do
  not publish host ports directly.
- Added backup/restore and checkpointer setup scripts:
  `infra/scripts/backup-postgres.sh`,
  `infra/scripts/restore-postgres.sh`,
  `services/backend/scripts/setup_checkpointer.py`.
- Added release env preflight script:
  `services/backend/scripts/validate_release_env.py`. It validates the real
  `infra/env.production` shape, rejects checked-in placeholder values, and
  reuses backend auth/AI/search/push startup validators without printing secret
  values. The preflight now validates the target env file values directly, so
  host process environment variables cannot mask an invalid release env file.
  It also requires release `APP_BASE_URL` and `WEB_BASE_URL` to use HTTPS and
  rejects non-empty `WEB_PUSH_ALLOW_FAKE_IP_HOSTS`, keeping the P10 fake-IP
  proxy escape hatch out of production env files. The release URL check now
  also rejects localhost, `.local`, direct IP addresses, and URL userinfo for
  those public entrypoint URLs. The preflight now also rejects obviously short
  release secrets for `POSTGRES_PASSWORD`, `JWT_SECRET`, `LANGGRAPH_AES_KEY`,
  and `WEB_PUSH_VAPID_PRIVATE_KEY` while reporting only variable names, never
  secret values. It also fails closed on BOM or invalid UTF-8 env files before
  value validation, and rejects duplicate env variable names before applying the
  last value silently. Malformed env lines and invalid variable names also fail
  before value validation without echoing configured values or invalid
  left-hand-side text.
- Added release configuration regression coverage:
  `services/backend/tests/test_release_config_p11.py`.
  It now also asserts that the release env preflight CLI reports only variable
  names/error text and does not print configured secret values, and that the
  production Nginx/Compose files keep HTTPS redirect, TLS cert mounts, API
  proxying, upload size, audio volume, migrations, and checkpointer setup
  wired.
- The release configuration regression now also locks the production Nginx
  image boundary: the final Nginx stage copies only `default.conf` and the
  built `/dist` artifacts, not frontend source, lockfiles, or env files.
- The root `.dockerignore` now also excludes real release-only private artifacts
  from Docker build contexts: `infra/env.production`, `infra/certs/`, and
  `backups/`.
- Added frontend API wrappers and HomeView controls for report, appeals,
  weekly reports, export, training deletion, account deletion, and deletion
  status.
- Localized P11 HomeView user-facing report, appeal, weekly report, export, and
  deletion controls/status text to Chinese while leaving API enum values intact.
- Added frontend API wrapper regression tests for P11 report, appeals, weekly
  reports, export, single-training deletion, account deletion, and deletion
  proof status.
- Added backend HTTP regression tests for the P11 release endpoints. They cover
  owner-only report access, personal export redaction, cross-user training
  deletion rejection, successful training deletion through `/api/v1/me`, account
  deletion request, ADMIN self-deletion rejection with no deletion side effects,
  proof-code status without bearer auth, wrong proof rejection, post-deletion
  bearer-token rejection, admin appeal queue authorization, and admin appeal
  review invalidation behavior. They also cover user-scoped weekly report
  retrieval and the unified training appeals list that merges ordinary appeals
  with duplicate-question complaints.
- Added `docs/handoffs/P11-release-acceptance-checklist.md` as the executable
  release checklist for local gates, release env preflight, provider smoke,
  target-device P0 E2E, privacy/deletion, backup/restore, and final review
  signoff.

## Verification Run

- `pnpm install --frozen-lockfile --offline` passed and restored the existing
  frontend workspace dependencies without changing the lockfile.
- `pnpm --dir apps/web lint` passed.
- `pnpm --dir apps/web type-check` passed.
- `pnpm --dir apps/web test` passed: 11 files, 39 tests.
- `pnpm --dir apps/web test -- src/api/training.test.ts src/api/privacy.test.ts`
  passed: 2 files, 14 tests. This covers P11 report/appeal API wrappers and
  privacy API wrappers, including proof-code deletion status without bearer auth.
- `pnpm --dir apps/web build` passed.
- `cd services/backend && uv run ruff check .` passed.
- `cd services/backend && uv run ruff format --check .` passed.
- `cd services/backend && uv run mypy app` passed.
- `cd services/backend && uv run pytest -q` passed.
- `cd services/backend && uv run pytest -q tests/test_release_config_p11.py`
  passed. This verifies `infra/env.production.example` satisfies backend
  auth, AI, search, and push startup validators, and that real production env,
  certificate, and backup paths are ignored by Git. It also verifies the
  release env preflight rejects the checked-in placeholder example and accepts
  a realistic non-secret production-shaped env file.
- `cd services/backend && uv lock --check` passed.
- `cd services/backend && uv run python scripts/verify_dependency_policy.py` passed.
- Temporary pgvector database run passed:
  `uv run pytest -q tests/test_migrations_p11.py tests/test_release_privacy_p11.py`.
  This covered Alembic upgrade/downgrade/upgrade, single-training deletion,
  account deletion, checkpoint cleanup, model_run cleanup, question/source/vector
  cascade cleanup, report/weekly generation, and source appeal invalidation.
- After privacy hardening, a fresh temporary pgvector database run passed again:
  4 tests passed in `tests/test_migrations_p11.py` and
  `tests/test_release_privacy_p11.py`.
- `docker compose --env-file infra/env.production.example -f infra/docker-compose.prod.yml config --quiet`
  passed.
- Backup/restore rehearsal passed with a temporary Compose project and fake
  non-production env: probe table was backed up, dropped, restored, and queried
  back as `restored`.
- `git diff --check` passed after the final documentation update.
- `/review` checklist was read and applied manually. No critical SQL/data
  safety, enum completeness, LLM trust boundary, shell injection, or frontend
  XSS findings were found. The full interactive gstack `/review` workflow could
  not be completed because this host does not expose an AskUserQuestion tool.
- The full interactive `/review` skill was rechecked after the privacy hardening
  pass and remains blocked by the same missing AskUserQuestion tool requirement.
- After admin appeal queue hardening, `uv run ruff check
  app/repositories/defects.py tests/test_release_privacy_p11.py`,
  `uv run ruff format --check app/repositories/defects.py
  tests/test_release_privacy_p11.py`, `uv run ruff check .`,
  `uv run ruff format --check .`, `uv run mypy app`, and `uv run pytest -q`
  passed.
- With a fresh temporary pgvector container, `uv run pytest -q
  tests/test_release_privacy_p11.py` passed: 5 tests. This now also covers
  report/weekly cross-user isolation, weekly report idempotency, transcript
  appeal acceptance invalidating the report, and the admin queue excluding
  reviewed appeals. The additional export test verifies source/audit metadata
  inclusion and checks that private audio paths, fake audio bytes, signed URL
  markers, model-run private output, and another user's session are absent.
- After deletion proof hardening, `tests/test_release_privacy_p11.py` also seeds
  ordinary appeals and duplicate complaints for single-training and account
  deletion, verifies those rows are removed, and asserts their counts are
  returned in the deletion response/proof status.
- After release env output redaction, host-environment isolation, and
  Nginx/Compose wiring coverage, `uv run pytest -q
  tests/test_release_config_p11.py` passed: 8 tests.
- The same release configuration pass also completed `uv run ruff check .`,
  `uv run ruff format --check .`, `uv run mypy app`, `uv run pytest -q`, and
  `git diff --check` successfully.
- After personal export source/audit coverage, `uv run ruff check .`, `uv run
  ruff format --check .`, `uv run mypy app`, `uv run pytest -q`, `pnpm --dir
  apps/web lint`, `pnpm --dir apps/web type-check`, `pnpm --dir apps/web test`,
  `pnpm --dir apps/web build`, and `git diff --check` passed.
- Current continuation verification after the deletion proof and frontend export
  wrapper hardening passed:
  `pnpm --dir apps/web test -- src/api/privacy.test.ts`,
  `pnpm --dir apps/web type-check`,
  `cd services/backend && uv run ruff check .`,
  `cd services/backend && uv run ruff format --check .`,
  `cd services/backend && uv run mypy app`,
  `cd services/backend && uv run pytest -q`,
  `cd services/backend && uv lock --check`,
  `cd services/backend && uv run python scripts/verify_dependency_policy.py`,
  `pnpm --dir apps/web lint`,
  `pnpm --dir apps/web test`,
  `pnpm --dir apps/web build`,
  `docker compose --env-file infra/env.production.example -f infra/docker-compose.prod.yml config --quiet`,
  and `git diff --check`.
- A fresh temporary pgvector container also passed
  `uv run pytest -q tests/test_migrations_p11.py tests/test_release_privacy_p11.py`:
  6 tests passed, covering P11 Alembic upgrade/downgrade/upgrade and the
  deletion/export/report/appeal privacy integration checks. The temporary
  Docker container, volume, and network were removed after the run.
- A manual gstack checklist review pass was repeated because full `/review`
  remains blocked by the missing AskUserQuestion tool. This pass found and fixed
  the explicit user-scope gap in source summary lookup. Follow-up checks passed:
  `uv run ruff check app/repositories/source_questions.py app/repositories/reports.py app/api/v1/trainings.py tests/test_release_privacy_p11.py`,
  `uv run ruff format --check app/repositories/source_questions.py app/repositories/reports.py app/api/v1/trainings.py tests/test_release_privacy_p11.py`,
  `uv run mypy app`, a fresh temporary pgvector run of
  `uv run pytest -q tests/test_migrations_p11.py tests/test_release_privacy_p11.py`
  with 7 tests passed, `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run pytest -q`, `pnpm --dir apps/web type-check`, and `git diff --check`.
- A follow-up question lookup hardening pass found the remaining
  `get_question()` consumers and made them user-scoped. Follow-up checks passed:
  `uv run ruff format app/services/question_duplicates.py app/services/random_strike.py app/graphs/voice_training.py tests/test_random_strike_p10.py`,
  `uv run ruff check app/services/question_duplicates.py app/services/random_strike.py app/graphs/voice_training.py tests/test_random_strike_p10.py`,
  `uv run mypy app`, and a fresh temporary pgvector run of
  `uv run pytest -q tests/test_random_strike_p10.py::test_accept_rejects_cross_user_question_reference tests/test_never_repeat_p09.py::test_duplicate_complaint_invalidates_scoring_and_denies_template_family`
  with 2 tests passed. A plain local run of
  `uv run pytest -q tests/test_random_strike_p10.py tests/test_never_repeat_p09.py`
  skipped as expected without `TEST_DATABASE_URL`.
- After that pass, backend full checks passed again:
  `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy app`,
  and `uv run pytest -q`.
- A release hardening pass added portable backup checksum sidecars, restore-time
  checksum verification, the executable P11 release checklist, and Chinese
  HomeView labels/statuses for P11 report/privacy operations. Follow-up checks
  passed: `uv run pytest -q tests/test_release_config_p11.py` with 10 tests,
  `bash -n infra/scripts/backup-postgres.sh infra/scripts/restore-postgres.sh`,
  `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy app`,
  `uv run pytest -q`, `pnpm --dir apps/web lint`,
  `pnpm --dir apps/web type-check`, `pnpm --dir apps/web test`,
  `pnpm --dir apps/web build`,
  `docker compose --env-file infra/env.production.example -f infra/docker-compose.prod.yml config --quiet`,
  and `git diff --check`.
- The restore checksum regression was strengthened from static script inspection
  to an executable smoke: a deliberately bad `.sha256` sidecar now fails before
  the restore script reads `infra/env.production` or reaches Docker/`pg_restore`.
  Follow-up checks passed: `uv run pytest -q tests/test_release_config_p11.py`
  with 11 tests, `uv run ruff check tests/test_release_config_p11.py`,
  `uv run ruff format --check tests/test_release_config_p11.py`,
  `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy app`,
  `bash -n infra/scripts/backup-postgres.sh infra/scripts/restore-postgres.sh`,
  `uv run pytest -q`, and `git diff --check`.
- The restore checksum binding was hardened again: `restore-postgres.sh` now
  ignores the filename embedded in the `.sha256` sidecar and verifies the hash
  against the selected `backup_path` argument itself. A regression proves a
  sidecar containing another dump's valid hash still fails before reading the
  release env or reaching Docker/`pg_restore`. Commands run:
  `bash -n infra/scripts/backup-postgres.sh infra/scripts/restore-postgres.sh`,
  `.venv\Scripts\ruff.exe format tests\test_release_config_p11.py`,
  `.venv\Scripts\ruff.exe check tests\test_release_config_p11.py`,
  Node REPL direct run of
  `.venv\Scripts\pytest.exe -q tests\test_release_config_p11.py` with
  25 tests passed,
  Node REPL direct run of `.venv\Scripts\mypy.exe app`,
  and Node REPL direct run of `git diff --check`. A direct PowerShell pytest
  attempt failed due to the host pagefile/CLR issue before returning test
  results; the Node REPL rerun passed.
- Current deletion-proof anonymization pass verification:
  `uv run ruff format app/db/models.py app/repositories/privacy.py app/services/privacy.py tests/test_release_privacy_p11.py alembic/versions/0010_release_privacy.py`,
  `uv run ruff check app/db/models.py app/repositories/privacy.py app/services/privacy.py tests/test_release_privacy_p11.py alembic/versions/0010_release_privacy.py`,
  `uv run mypy app`,
  a fresh temporary pgvector run of
  `uv run pytest -q tests/test_migrations_p11.py tests/test_release_privacy_p11.py`
  with 7 tests passed,
  no leftover `codex-p11-pg-*` Docker containers,
  `uv run ruff check .`,
  `uv run ruff format --check .`,
  `uv lock --check`,
  `uv run python scripts/verify_dependency_policy.py`,
  `uv run pytest -q`,
  and `git diff --check`.
- Current P11 API-layer regression pass verification:
  `uv run ruff format tests/test_release_privacy_p11.py`,
  `uv run ruff check tests/test_release_privacy_p11.py`,
  a fresh temporary pgvector run of
  `uv run pytest -q tests/test_migrations_p11.py tests/test_release_privacy_p11.py`
  with 11 tests passed,
  no leftover `codex-p11-pg-*` Docker containers,
  `uv run ruff check .`,
  `uv run ruff format --check .`,
  `uv run mypy app`,
  `uv run pytest -q`,
  and `git diff --check`. A first temporary pgvector attempt reached pytest
  before Postgres had finished startup and failed with `database system is
  starting up`; it was rerun with a longer readiness wait and passed.
- The API-layer pass now includes admin appeal HTTP coverage: ordinary
  users receive 403 on `/api/v1/admin/appeals`, admins see only the open appeal,
  accepting the transcript appeal via `/api/v1/admin/appeals/{id}/review`
  returns `REVIEWED_ACCEPTED`, removes it from the queue, invalidates the
  session report, and excludes the linked defect occurrence.
- The same API-layer pass now covers `GET /api/v1/me/weekly-reports` and
  `GET /api/v1/trainings/{id}/appeals`: weekly reports are user-scoped, the
  unified appeals response contains both an ordinary evaluation appeal and a
  duplicate-question complaint, and another user receives 404 for that session's
  appeal status.
- Current release configuration image-boundary regression verification:
  `uv run ruff format tests/test_release_config_p11.py`,
  `uv run ruff check tests/test_release_config_p11.py`,
  `uv run pytest -q tests/test_release_config_p11.py` with 12 tests passed, and
  `git diff --check`.
- Current Docker build-context privacy hardening verification:
  `uv run ruff format tests/test_release_config_p11.py`,
  `uv run ruff check tests/test_release_config_p11.py`,
  `uv run pytest -q tests/test_release_config_p11.py` with 13 tests passed, and
  `git diff --check`.
- Current ADMIN account-deletion guard verification:
  `uv run ruff format tests/test_release_privacy_p11.py`,
  `uv run ruff check tests/test_release_privacy_p11.py`,
  a fresh temporary pgvector run of
  `uv run pytest -q tests/test_migrations_p11.py tests/test_release_privacy_p11.py`
  with 12 tests passed, no leftover `codex-p11-pg-*` Docker containers, and
  `git diff --check`. An earlier rerun failed only because the new assertion
  expected FastAPI's raw `detail` field instead of the project's wrapped
  `error.message`; the business behavior was already 403 and the assertion was
  corrected to the established error contract.
- Current transcript-correction export/deletion coverage verification:
  `uv run ruff format app/repositories/privacy.py app/services/privacy.py tests/test_release_privacy_p11.py`,
  `uv run ruff check app/repositories/privacy.py app/services/privacy.py tests/test_release_privacy_p11.py`,
  `uv run mypy app`, a fresh temporary pgvector run of
  `uv run pytest -q tests/test_migrations_p11.py tests/test_release_privacy_p11.py`
  with 12 tests passed, no leftover `codex-p11-pg-*` Docker containers, and
  `git diff --check`.
- Current account-deletion proof-count expansion verification:
  `uv run ruff check --fix app/repositories/privacy.py tests/test_release_privacy_p11.py`,
  `uv run ruff format app/repositories/privacy.py tests/test_release_privacy_p11.py`,
  `uv run ruff check app/repositories/privacy.py tests/test_release_privacy_p11.py`,
  `uv run mypy app`, a fresh temporary pgvector run of
  `uv run pytest -q tests/test_migrations_p11.py tests/test_release_privacy_p11.py`
  with 12 tests passed, no leftover `codex-p11-pg-*` Docker containers, and
  `git diff --check`.
- Current single-training orphan-question proof-count verification:
  `uv run ruff format app/repositories/privacy.py tests/test_release_privacy_p11.py`,
  `uv run ruff check app/repositories/privacy.py tests/test_release_privacy_p11.py`,
  `uv run mypy app`, a fresh temporary pgvector run of
  `uv run pytest -q tests/test_migrations_p11.py tests/test_release_privacy_p11.py`
  with 12 tests passed, no leftover `codex-p11-pg-*` Docker containers, and
  `git diff --check`.
- Current release artifact privacy check verification:
  `git check-ignore infra/env.production infra/certs/fullchain.pem infra/certs/privkey.pem backups/postgres/thinking-test.dump`
  passed, `pnpm --dir apps/web build` passed, `docker compose --env-file
  infra/env.production.example -f infra/docker-compose.prod.yml config --quiet`
  passed, and scanning `apps/web/dist` for common private key, signed URL,
  Qwen/DashScope/Bocha/Aliyun secret markers returned `NO_MATCH`.
- Current full local gate refresh verification passed:
  `uv lock --check`,
  `uv run python scripts/verify_dependency_policy.py`,
  `uv run ruff check .`,
  `uv run ruff format --check .`,
  `uv run mypy app`,
  `uv run pytest -q`,
  `pnpm --dir apps/web lint`,
  `pnpm --dir apps/web type-check`,
  `pnpm --dir apps/web test`,
  `pnpm --dir apps/web build`,
  `docker compose --env-file infra/env.production.example -f infra/docker-compose.prod.yml config --quiet`,
  `bash -n infra/scripts/backup-postgres.sh infra/scripts/restore-postgres.sh`,
  and `git diff --check`.
  A fresh temporary pgvector run of
  `uv run pytest -q tests/test_migrations_p11.py tests/test_release_privacy_p11.py`
  also passed with 12 tests, and no `codex-p11-pg-*` containers remained after
  cleanup. A first Compose command in this refresh used a mistyped env-file
  path (`infra.env.production.example`) and failed before loading any env; the
  intended command above was rerun and passed.
- Current manual review hardening for source appeal ownership passed:
  `.venv\Scripts\ruff.exe format app\repositories\defects.py tests\test_release_privacy_p11.py`,
  `.venv\Scripts\ruff.exe check app\repositories\defects.py tests\test_release_privacy_p11.py`,
  `.venv\Scripts\mypy.exe app`, a targeted temporary pgvector run of
  `.venv\Scripts\pytest.exe -q tests/test_release_privacy_p11.py::test_source_appeal_rejects_cross_user_question_reference`,
  and a fresh temporary pgvector run of
  `.venv\Scripts\pytest.exe -q tests/test_migrations_p11.py tests/test_release_privacy_p11.py`
  with 13 tests passed. The temporary Docker containers were removed after each
  run. Equivalent `uv run ...` checks were first attempted but timed out in this
  Windows host after parallel invocation; direct venv commands were used to
  avoid the stuck `uv` wrapper while preserving the same tool versions.
- Current account-deletion proof comparison hardening passed:
  `.venv\Scripts\ruff.exe format app\services\privacy.py tests\test_release_privacy_p11.py`,
  `.venv\Scripts\ruff.exe check app\services\privacy.py tests\test_release_privacy_p11.py`,
  `.venv\Scripts\mypy.exe app`, a targeted temporary pgvector run of
  `.venv\Scripts\pytest.exe -q tests/test_release_privacy_p11.py::test_account_deletion_disables_login_scope_then_removes_user_data`,
  and a fresh temporary pgvector run of
  `.venv\Scripts\pytest.exe -q tests/test_release_privacy_p11.py` with
  12 tests passed. The temporary Docker containers were removed after each run.
  A first targeted run used database name `codex_p11`; the test fixture refused
  to reset it because the name did not contain `test`, then the run was repeated
  with `codex_p11_test` and passed.
- Current production Nginx security-header verification passed:
  `.venv\Scripts\ruff.exe format tests\test_release_config_p11.py`,
  `.venv\Scripts\ruff.exe check tests\test_release_config_p11.py`,
  `docker compose --env-file infra/env.production.example -f infra/docker-compose.prod.yml config --quiet`,
  and `.venv\Scripts\pytest.exe -q tests/test_release_config_p11.py` with
  14 tests passed.
- Current private-audio exposure regression passed:
  `.venv\Scripts\ruff.exe format tests\test_release_config_p11.py`,
  `.venv\Scripts\ruff.exe check tests\test_release_config_p11.py`,
  `docker compose --env-file infra/env.production.example -f infra/docker-compose.prod.yml config --quiet`,
  and `.venv\Scripts\pytest.exe -q tests/test_release_config_p11.py` with
  15 tests passed.
- Current production port exposure regression passed:
  `.venv\Scripts\ruff.exe format tests\test_release_config_p11.py`,
  `.venv\Scripts\ruff.exe check tests\test_release_config_p11.py`,
  `docker compose --env-file infra/env.production.example -f infra/docker-compose.prod.yml config --quiet`,
  and `.venv\Scripts\pytest.exe -q tests/test_release_config_p11.py` with
  16 tests passed.
- Current account-deletion user-only job cleanup regression passed:
  `.venv\Scripts\ruff.exe format tests\test_release_privacy_p11.py`,
  `.venv\Scripts\ruff.exe check tests\test_release_privacy_p11.py`,
  `.venv\Scripts\mypy.exe app`, a targeted temporary pgvector run of
  `.venv\Scripts\pytest.exe -q tests/test_release_privacy_p11.py::test_account_deletion_disables_login_scope_then_removes_user_data`,
  and a fresh temporary pgvector run of
  `.venv\Scripts\pytest.exe -q tests/test_release_privacy_p11.py` with
  12 tests passed. The temporary Docker containers were removed after each run.
- Current backup permission hardening verification passed:
  `.venv\Scripts\ruff.exe format tests\test_release_config_p11.py`,
  `.venv\Scripts\ruff.exe check tests\test_release_config_p11.py`,
  `bash -n infra/scripts/backup-postgres.sh infra/scripts/restore-postgres.sh`,
  and `.venv\Scripts\pytest.exe -q tests/test_release_config_p11.py` with
  16 tests passed.
- Current release env preflight hardening verification passed:
  `.venv\Scripts\ruff.exe format scripts\validate_release_env.py tests\test_release_config_p11.py`,
  `docker compose --env-file infra/env.production.example -f infra/docker-compose.prod.yml config --quiet`,
  `.venv\Scripts\mypy.exe app`,
  `.venv\Scripts\ruff.exe check --fix tests\test_release_config_p11.py`,
  `.venv\Scripts\ruff.exe check scripts\validate_release_env.py tests\test_release_config_p11.py`,
  `.venv\Scripts\pytest.exe -q tests/test_release_config_p11.py` with
  18 tests passed, and `git diff --check`. An initial targeted ruff check found
  only an import-order issue in the test file; the auto-fix above corrected it
  before the final ruff check passed.
- Current release URL public-host hardening verification passed:
  `.venv\Scripts\ruff.exe format scripts\validate_release_env.py tests\test_release_config_p11.py`,
  `docker compose --env-file infra/env.production.example -f infra/docker-compose.prod.yml config --quiet`,
  `.venv\Scripts\ruff.exe check scripts\validate_release_env.py tests\test_release_config_p11.py`,
  `.venv\Scripts\mypy.exe app`, and
  `.venv\Scripts\pytest.exe -q tests/test_release_config_p11.py` with
  20 tests passed.
- Current backup retention hardening verification passed:
  `.venv\Scripts\ruff.exe format tests\test_release_config_p11.py`,
  `.venv\Scripts\ruff.exe check tests\test_release_config_p11.py`,
  `bash -n infra/scripts/backup-postgres.sh infra/scripts/restore-postgres.sh`,
  `.venv\Scripts\mypy.exe app`,
  `git diff --check`,
  `.venv\Scripts\pytest.exe -q tests/test_release_config_p11.py` with
  21 tests passed, and
  `docker compose --env-file infra/env.production.example -f infra/docker-compose.prod.yml config --quiet`.
  The first retention test attempts exposed that Windows/WSL bash did not
  inherit the Python subprocess `BACKUP_DIR` environment as expected; the final
  regression sets the variable inside the bash command itself and verifies the
  prune-only path against a temporary backup directory.
- Current restore production guard verification passed:
  `bash -n infra/scripts/backup-postgres.sh infra/scripts/restore-postgres.sh`,
  `.venv\Scripts\ruff.exe check tests\test_release_config_p11.py`,
  `.venv\Scripts\pytest.exe -q tests/test_release_config_p11.py` with
  22 tests passed, `.venv\Scripts\mypy.exe app`,
  `docker compose --env-file infra/env.production.example -f infra/docker-compose.prod.yml config --quiet`,
  and `git diff --check`. The regression uses a temporary CRLF-shaped
  `APP_ENV=production` env file and proves the restore script exits before
  `pg_restore` unless `RESTORE_ALLOW_PRODUCTION=1` is set.
- Current release secret-strength preflight verification passed:
  `.venv\Scripts\ruff.exe format scripts\validate_release_env.py tests\test_release_config_p11.py`,
  `.venv\Scripts\ruff.exe check scripts\validate_release_env.py tests\test_release_config_p11.py`,
  `.venv\Scripts\mypy.exe app`,
  `.venv\Scripts\pytest.exe -q tests/test_release_config_p11.py` with
  23 tests passed,
  `docker compose --env-file infra/env.production.example -f infra/docker-compose.prod.yml config --quiet`,
  `bash -n infra/scripts/backup-postgres.sh infra/scripts/restore-postgres.sh`,
  and `git diff --check`.
- Current deletion proof hardening verification passed:
  `audio_file_references` now records database audio references cleared by
  single-training and account deletion, while `audio_files` records physical
  local files actually unlinked. A regression covers the missing-file edge case:
  when the database still references an audio object but the file is already
  absent, deletion clears the business rows and reports `audio_file_references=1`
  with `audio_files=0`.
  Commands run:
  `.venv\Scripts\ruff.exe format app\services\privacy.py app\repositories\privacy.py tests\test_release_privacy_p11.py`,
  `.venv\Scripts\ruff.exe check app\services\privacy.py app\repositories\privacy.py tests\test_release_privacy_p11.py`,
  `.venv\Scripts\mypy.exe app`,
  a temporary pgvector run of
  `.venv\Scripts\pytest.exe -q tests\test_release_privacy_p11.py` with
  13 tests passed, and `git diff --check`. The temporary Docker container was
  removed after the run.
- Current invalid audio-reference deletion hardening passed:
  if a database audio reference resolves outside `audio_root`, deletion now
  skips unlinking that path, records `audio_file_invalid_references`, and still
  clears the owning business rows. This applies to both single-training deletion
  and account deletion. `audio_file_non_file_references` also records paths that
  resolve inside `audio_root` but are not regular files; the regression now
  covers an audio reference resolving to a directory and proves the directory is
  not unlinked while business rows are cleared. Commands run:
  `.venv\Scripts\ruff.exe format app\services\privacy.py tests\test_release_privacy_p11.py`,
  `.venv\Scripts\ruff.exe check app\services\privacy.py tests\test_release_privacy_p11.py`,
  `.venv\Scripts\mypy.exe app`,
  a temporary pgvector run of the two targeted invalid-reference tests with
  2 tests passed,
  a temporary pgvector run of the non-file reference target test with 1 test
  passed,
  a temporary pgvector run of
  `.venv\Scripts\pytest.exe -q tests\test_release_privacy_p11.py` with
  16 tests passed, and `git diff --check`. The first non-file target run hit a
  Postgres startup race before schema reset; it was rerun with `psql SELECT 1`
  SQL-readiness polling and passed. No `codex-p11-pg-*` containers remained
  after cleanup.
- Current account-deletion status idempotency hardening passed:
  `PrivacyService.mark_deletion_failed()` now leaves already `SUCCEEDED`
  account-deletion requests unchanged. This prevents a later worker/job-marking
  failure from downgrading the proof status after business data has already been
  deleted and the request has been anonymized. The regression simulates a
  successful deletion followed by `mark_deletion_failed()` and verifies the
  request remains `SUCCEEDED`, `error_code` stays empty, no FAILED audit is
  added, and proof-code status still reports success. Commands run:
  `.venv\Scripts\ruff.exe format app\services\privacy.py tests\test_release_privacy_p11.py`,
  `.venv\Scripts\ruff.exe check app\services\privacy.py tests\test_release_privacy_p11.py`,
  `.venv\Scripts\mypy.exe app`,
  a temporary pgvector run of the target status-idempotency test with 1 test
  passed,
  a temporary pgvector run of
  `.venv\Scripts\pytest.exe -q tests\test_release_privacy_p11.py` with
  17 tests passed, and `git diff --check`. The first target regression used an
  order-sensitive audit assertion; it was corrected to be order-independent and
  rerun successfully. No `codex-p11-pg-*` containers remained after cleanup.
- Current backup/restore rehearsal verification passed:
  a temporary Compose project started only the `postgres` service with a fake
  release-rehearsal env, inserted `p11_backup_smoke`, ran
  `infra/scripts/backup-postgres.sh` to produce a dump plus `.sha256`, dropped
  the table, ran `infra/scripts/restore-postgres.sh`, and verified
  `SELECT note FROM p11_backup_smoke WHERE id=1` returned `restored`. The
  temporary Compose project was removed with `down -v`.
- Current backup failure atomicity hardening passed:
  `backup-postgres.sh` now writes `pg_dump` output to `${output}.tmp`, moves it
  to the final `.dump` only after `pg_dump` succeeds, and removes the temp file
  through an EXIT trap on failure. Retention parameter validation also runs
  before `pg_dump`, so invalid retention settings fail before creating a new
  backup. A regression injects a fake Bash `docker` function that returns a
  `pg_dump` failure and verifies no final dump, temp dump, or checksum sidecar is
  left behind. Commands run:
  `bash -n infra/scripts/backup-postgres.sh infra/scripts/restore-postgres.sh`,
  `.venv\Scripts\ruff.exe format tests\test_release_config_p11.py`,
  `.venv\Scripts\ruff.exe check tests\test_release_config_p11.py`,
  Node REPL direct run of
  `.venv\Scripts\pytest.exe -q tests\test_release_config_p11.py` with
  26 tests passed,
  Node REPL direct run of `.venv\Scripts\mypy.exe app`,
  and Node REPL direct run of `git diff --check`.
- Current backup checksum atomicity hardening passed:
  `backup-postgres.sh` now requires `sha256sum`, writes a temporary checksum
  sidecar for the temporary dump, and only then publishes the final `.dump` and
  `.sha256`. If checksum generation fails, the script removes the temporary dump
  and temporary sidecar; if a final dump has already been published but no final
  sidecar exists, the EXIT trap removes that final dump too. A regression
  injects a fake successful `docker` function and a failing `sha256sum` function
  and verifies no final dump, temp dump, or sidecar remains. Commands run:
  `bash -n infra/scripts/backup-postgres.sh infra/scripts/restore-postgres.sh`,
  `.venv\Scripts\ruff.exe format tests\test_release_config_p11.py`,
  `.venv\Scripts\ruff.exe check tests\test_release_config_p11.py`,
  Node REPL direct run of
  `.venv\Scripts\pytest.exe -q tests\test_release_config_p11.py` with
  27 tests passed,
  Node REPL direct run of `.venv\Scripts\mypy.exe app`,
  and Node REPL direct run of `git diff --check`.
- Current backup/restore env hardening verification passed:
  the first local rehearsal attempt exposed that a UTF-8 BOM env file generated
  by Windows PowerShell makes bash `source` misread the first variable. The
  backup and restore scripts now reject BOM env files before touching
  `pg_dump`, `pg_restore`, or Docker. Commands run:
  `.venv\Scripts\ruff.exe format tests\test_release_config_p11.py`,
  `.venv\Scripts\ruff.exe check tests\test_release_config_p11.py`,
  `bash -n infra/scripts/backup-postgres.sh infra/scripts/restore-postgres.sh`,
  `.venv\Scripts\pytest.exe -q tests/test_release_config_p11.py` with
  24 tests passed,
  `docker compose --env-file infra/env.production.example -f infra/docker-compose.prod.yml config --quiet`,
  and `git diff --check`.
- Current backup retention and restore checksum verification passed:
  Re-ran the local backup/restore gate for retention and checksum ordering.
  `test_backup_script_prune_only_retains_daily_and_weekly_snapshots` proves the
  script retains at least the newest 7 daily dumps and 4 older weekly snapshots,
  preserves unrecognized manual dump names, and prunes matching stale `.sha256`
  sidecars. `test_restore_script_verifies_checksum_before_restore`,
  `test_restore_script_rejects_bad_checksum_before_env_or_docker`, and
  `test_restore_script_verifies_checksum_against_selected_backup_path` prove the
  restore checksum sidecar is checked before `pg_restore`, bad hashes fail
  before reading the release env or reaching Docker, and sidecar hashes are
  bound to the selected dump path itself. Commands run:
  `bash -n infra/scripts/backup-postgres.sh infra/scripts/restore-postgres.sh`,
  `.venv\Scripts\pytest.exe -q` with those 4 targeted tests, and
  `.venv\Scripts\pytest.exe -q tests\test_release_config_p11.py` with 43 tests
  passed.
- Current backend gate refresh after worker error-code hardening:
  bare `uv lock --check` failed in online mode after resolving 138 packages in
  a shell with no `UV_*` variables because uv wanted to rewrite `uv.lock`
  registry URL/metadata entries (`mirrors.aliyun.com` to
  `pypi.tuna.tsinghua.edu.cn`, plus package size/upload-time metadata). That
  893-line lockfile noise was reverted and is not part of P11. The committed
  lockfile is pinned to `https://mirrors.aliyun.com/pypi/simple`; rerunning the
  online gate with `UV_DEFAULT_INDEX` set to that registry passed with status 0
  and left `services/backend/uv.lock` clean. `UV_INDEX_URL` was also tested and
  is not equivalent for this lock consistency check. `uv lock --check --offline`
  passed afterward without modifying the lockfile. The remaining backend gates
  passed:
  `uv run python scripts\verify_dependency_policy.py`,
  `.venv\Scripts\ruff.exe check .`,
  `.venv\Scripts\ruff.exe format --check .`,
  `.venv\Scripts\mypy.exe app`, and
  `.venv\Scripts\pytest.exe -q`. The pytest run exited 0 with the existing
  Starlette TestClient deprecation warning and expected skipped tests for
  database/live-service-gated cases. Final P11 signoff should run the
  `UV_DEFAULT_INDEX`-pinned online lock gate in the target release shell.
- Current frontend deletion-status privacy verification passed:
  HomeView renders the deletion proof lookup as a password field with
  `autocomplete="off"` and `spellcheck="false"`. The privacy API regression
  verifies deletion status is queried without a bearer token, and that the proof
  code is not placed in the URL. A lightweight SFC raw-import regression locks
  the proof input attributes without adding a frontend test dependency.
  Commands run:
  `pnpm --dir apps/web test -- src/api/privacy.test.ts src/views/HomeView.privacy.test.ts`
  with 4 tests passed,
  `pnpm --dir apps/web lint`,
  `pnpm --dir apps/web type-check`,
  `pnpm --dir apps/web build`, and `git diff --check`. An initial
  `type-check` failed because the first test version imported `node:fs` under
  the app tsconfig; the test now uses `HomeView.vue?raw` and the rerun passed.
- Current frontend pending-audio deletion hardening passed:
  account deletion and single-training deletion now best-effort clear the
  IndexedDB `pending-audio` store plus the in-memory/local pending-attempt
  reference after the destructive API call succeeds. This prevents browser-side
  pending recording blobs from surviving a P11 privacy deletion flow while
  keeping local cache failures non-blocking. Commands run:
  `pnpm --dir apps/web test -- src/audio/pendingAudioStore.test.ts src/views/HomeView.privacy.test.ts`
  with 2 files and 5 tests passed,
  `pnpm --dir apps/web lint`,
  `pnpm --dir apps/web type-check`,
  `pnpm --dir apps/web build`,
  `pnpm --dir apps/web scan-dist-secrets`, and `git diff --check`.
- Current frontend build artifact secret gate passed:
  `pnpm --dir apps/web scan-dist-secrets` scans `apps/web/dist` for forbidden
  server-side secret env names and, when present in the current process
  environment, their actual values. It also flags common Aliyun OSS and
  S3-compatible signed URL markers. The scanner reports only variable names,
  marker labels, and file paths, not secret values or signed URLs. It now
  supports a `WEB_DIST_SCAN_DIR` override for isolated local regression tests
  while keeping the default `apps/web/dist` scan path for release gates.
  Commands run:
  `pnpm --dir apps/web build`,
  `pnpm --dir apps/web scan-dist-secrets`,
  `pnpm --dir apps/web lint`,
  `pnpm --dir apps/web type-check`, and
  `pnpm --dir apps/web test -- src/api/privacy.test.ts src/views/HomeView.privacy.test.ts`
  with 4 tests passed. An initial lint run failed because the new Node script
  needed explicit `console`/`process`/`URL` globals; the file-level declaration
  fixed it and the rerun passed.
- Current LangGraph checkpointer release setup verification passed:
  `tests/test_release_checkpointer_p11.py` covers the release setup script URL
  conversion and, when `TEST_DATABASE_SYNC_URL` is present, runs
  `setup_checkpointer()` twice against a temporary pgvector database. The test
  verifies `checkpoint_migrations`, `checkpoints`, `checkpoint_blobs`, and
  `checkpoint_writes` exist after setup, proving the release script can create
  LangGraph internal tables without hand-written DDL and is safe to rerun.
  Commands run:
  `.venv\Scripts\ruff.exe check --fix tests\test_release_checkpointer_p11.py`,
  `.venv\Scripts\ruff.exe format tests\test_release_checkpointer_p11.py`,
  `.venv\Scripts\ruff.exe check tests\test_release_checkpointer_p11.py`,
  a temporary pgvector run of
  `.venv\Scripts\pytest.exe -q tests\test_release_checkpointer_p11.py` with
  2 tests passed, and `git diff --check`. The first temporary database attempt
  hit a startup race before the test reached checkpointer setup; the final run
  waited for `psql SELECT 1` and passed. The temporary Docker container was
  removed.
- Current error-response redaction verification passed:
  `app.core.errors` now filters sensitive scalar extras from HTTPException
  detail mappings before building the unified error envelope. Keys containing
  proof, token, authorization, audio, signed URL, secret, API key, and related
  terms are removed, while safe public extras are preserved. The regression in
  `tests/test_health.py` proves `proof_code`, `refresh_token`, `audio_path`,
  `signed_url`, and `Authorization` values do not appear in the response body.
  Commands run:
  `.venv\Scripts\ruff.exe format app\core\errors.py tests\test_health.py`,
  `.venv\Scripts\ruff.exe check app\core\errors.py tests\test_health.py`,
  `.venv\Scripts\pytest.exe -q tests\test_health.py` with 8 tests passed,
  `.venv\Scripts\mypy.exe app`, and `git diff --check`. Pytest emitted only the
  existing Starlette TestClient deprecation warning.
- Current account-deletion failure audit redaction passed:
  `PrivacyService.mark_deletion_failed()` now only persists deletion failure
  error codes matching the safe `[A-Z][A-Z0-9_]{0,63}` shape. Unsafe exception
  strings, URLs, paths, tokens, or proof-code-shaped values collapse to
  `DELETION_FAILED` before being written to `privacy_deletion_request` or
  `privacy_audit_event`. The regression injects an unsafe deletion error string
  containing the one-time proof code, a refresh-token-shaped value, the stored
  audio path, an S3-compatible signed URL/signature, and an API-key-shaped value;
  the persisted request/audit error fields contain only `DELETION_FAILED`.
  Commands run:
  `.venv\Scripts\ruff.exe format app\services\privacy.py tests\test_release_privacy_p11.py`,
  `.venv\Scripts\ruff.exe check app\services\privacy.py tests\test_release_privacy_p11.py`,
  `.venv\Scripts\mypy.exe app`,
  a temporary pgvector run of
  `tests\test_release_privacy_p11.py::test_account_deletion_failed_error_code_is_redacted_for_audit`
  with 1 test passed,
  a temporary pgvector run of three account-deletion tests with 3 tests passed,
  `docker ps -a --filter name=codex-p11-pg-redaction- --format {{.Names}}`
  showing no residual containers, and `git diff --check`. An initial target run
  skipped because the env variables were not visible to pytest through `cmd.exe`;
  a second run failed because the sync URL used the default `psycopg2` driver;
  the final runs used PowerShell `$env:` variables and
  `postgresql+psycopg://...` for the sync URL.
- Current worker error-code redaction passed:
  `app.workers.main._error_code()` now persists only safe error codes matching
  `[A-Z][A-Z0-9_]{0,63}`. Unsafe exception `code` or `error_code` values that
  contain proof-code-shaped strings, refresh-token-shaped values, audio paths,
  signed URLs, signature values, or API-key-shaped values fall back to the
  exception class name instead of being written into job failure fields. Commands
  run:
  `.venv\Scripts\ruff.exe format app\workers\main.py tests\test_worker_errors_p11.py`,
  `.venv\Scripts\ruff.exe check app\workers\main.py tests\test_worker_errors_p11.py`,
  `.venv\Scripts\mypy.exe app`, and
  `.venv\Scripts\pytest.exe -q tests\test_worker_errors_p11.py` with 7 tests
  passed. A target run of
  `.venv\Scripts\pytest.exe -q tests\test_release_privacy_p11.py::test_account_deletion_failed_error_code_is_redacted_for_audit`
  skipped in the current shell because `TEST_DATABASE_URL` and
  `TEST_DATABASE_SYNC_URL` were not set, so it is not counted as passing
  evidence for this continuation.
- Current temporary pgvector P11 privacy verification passed:
  A fresh temporary container `codex-p11-pg-1782380240000` from
  `pgvector/pgvector:pg16` started a local `thinking_p11_test` database, waited
  for `pg_isready`, and ran
  `.venv\Scripts\pytest.exe -q tests\test_migrations_p11.py tests\test_release_privacy_p11.py`
  with `TEST_DATABASE_URL` and `TEST_DATABASE_SYNC_URL` pointed at the temporary
  database. Result: 19 tests passed. This covers P11 Alembic
  upgrade/downgrade/upgrade plus the report/export/appeal/account deletion,
  single-training deletion, proof-code status, deletion anonymization,
  source/user isolation, and deletion failure redaction integration cases. The
  only output warning was the existing Alembic `path_separator` deprecation
  warning. The temporary container was removed with
  `docker rm -f codex-p11-pg-1782380240000`; a follow-up
  `docker ps -a --filter name=codex-p11-pg-1782380240000 --format {{.Names}}`
  returned no container names.
- Current restore missing-checksum hardening passed:
  `restore-postgres.sh` now refuses to restore a dump without its `.sha256`
  sidecar before reading the release env or reaching Docker/`pg_restore`, unless
  `RESTORE_ALLOW_MISSING_CHECKSUM=1` is explicitly set for an approved legacy
  rehearsal. The override does not bypass the production guard:
  `APP_ENV=production` still requires `RESTORE_ALLOW_PRODUCTION=1`.
  Commands run:
  `bash -n infra/scripts/backup-postgres.sh infra/scripts/restore-postgres.sh`,
  `.venv\Scripts\ruff.exe format tests\test_release_config_p11.py`,
  `.venv\Scripts\ruff.exe check tests\test_release_config_p11.py`,
  Node REPL direct run of
  `.venv\Scripts\pytest.exe -q tests\test_release_config_p11.py` with
  29 tests passed,
  Node REPL direct run of `.venv\Scripts\mypy.exe app`,
  and Node REPL direct run of `git diff --check`.
- Current release env encoding preflight hardening passed:
  `validate_release_env.py` now rejects BOM and invalid UTF-8 env files before
  parsing values, avoiding misleading missing-variable reports and keeping
  configured secret values out of validation output. Commands run:
  `.venv\Scripts\ruff.exe format scripts\validate_release_env.py tests\test_release_config_p11.py`,
  `.venv\Scripts\ruff.exe check scripts\validate_release_env.py tests\test_release_config_p11.py`,
  Node REPL direct run of
  `.venv\Scripts\pytest.exe -q tests\test_release_config_p11.py` with
  31 tests passed,
  Node REPL direct run of `.venv\Scripts\mypy.exe app`,
  and Node REPL direct run of `git diff --check`. An initial ruff run found the
  default UTF-8 `.encode()` style issue in the new test; it was fixed and the
  final ruff check passed.
- Current release env duplicate-name preflight hardening passed:
  `validate_release_env.py` now rejects duplicate variable names before value
  validation, avoiding silent "last value wins" behavior in the release
  preflight. The regression covers duplicate `JWT_SECRET` entries and proves
  neither configured value appears in output. Commands run:
  `.venv\Scripts\ruff.exe format scripts\validate_release_env.py tests\test_release_config_p11.py`,
  `.venv\Scripts\ruff.exe check scripts\validate_release_env.py tests\test_release_config_p11.py`,
  Node REPL direct run of
  `.venv\Scripts\pytest.exe -q tests\test_release_config_p11.py` with
  32 tests passed,
  Node REPL direct run of `.venv\Scripts\mypy.exe app`,
  and Node REPL direct run of `git diff --check`.
- Current release env malformed-line preflight hardening passed:
  `validate_release_env.py` now rejects malformed env lines and invalid variable
  names before value validation, including shell-style `export NAME=value` lines
  that Docker Compose env files would not parse as intended. Invalid-name errors
  now report only the line number, not the invalid left-hand-side text, so a
  secret accidentally written before `=` is not echoed. The regressions verify
  configured secret-looking values are not echoed in errors. Commands run:
  `.venv\Scripts\ruff.exe format scripts\validate_release_env.py tests\test_release_config_p11.py`,
  `.venv\Scripts\ruff.exe check scripts\validate_release_env.py tests\test_release_config_p11.py`,
  Node REPL direct run of
  `.venv\Scripts\pytest.exe -q tests\test_release_config_p11.py` with
  34 tests passed,
  Node REPL direct run of `.venv\Scripts\mypy.exe app`,
  and Node REPL direct run of `git diff --check`.
- Current release manifest verification passed:
  Added `services/backend/scripts/release_manifest.py`, a non-secret JSON
  manifest generator for release signoff. It records the supplied image tag,
  Git commit/short commit/worktree status, current Alembic head, and SHA-256
  hashes for production Compose/Nginx/backend/web release artifacts. With
  `--output`, it writes the same JSON to a caller-selected evidence file while
  still printing stdout. It does not read `infra/env.production`, TLS
  certificates, backup dumps, or any secret-bearing env values. The regression
  proves the manifest records `0010_release_privacy`, preserves the supplied
  image tag, emits 64-character artifact hashes, writes a matching output file,
  and does not contain common secret env names or private artifact names.
  Commands run:
  `.venv\Scripts\ruff.exe check --fix tests\test_release_config_p11.py`,
  `.venv\Scripts\ruff.exe format scripts\release_manifest.py tests\test_release_config_p11.py`,
  `.venv\Scripts\ruff.exe check scripts\release_manifest.py tests\test_release_config_p11.py`,
  `.venv\Scripts\mypy.exe app scripts\release_manifest.py`,
  `.venv\Scripts\pytest.exe -q tests\test_release_config_p11.py::test_release_manifest_records_migration_head_and_image_tag_without_secrets`,
  `.venv\Scripts\pytest.exe -q tests\test_release_config_p11.py` with
  37 tests passed, and
  `.venv\Scripts\python.exe scripts\release_manifest.py --image-tag thinking-coach:test-release-tag --output <temp-release-manifest.json>`.
  The first ruff check found import ordering in the updated test; `--fix`
  corrected it and the rerun passed. The temporary manifest output was removed
  after confirming it contained image tag `thinking-coach:test-release-tag`,
  Alembic head `0010_release_privacy`, and 5 artifact hashes.
- Current release manifest output-safety hardening passed:
  `release_manifest.py` now rejects blank image tags, image tags containing
  whitespace, non-`.json` output paths, output paths that would overwrite the
  release source/config artifacts it hashes, and output paths under private
  release artifact locations such as `infra/certs`, `backups`, or `secrets`.
  The regression proves rejected outputs do not create the requested file and
  do not modify `apps/web/package.json`. Commands run:
  `.venv\Scripts\ruff.exe format scripts\release_manifest.py tests\test_release_config_p11.py`,
  `.venv\Scripts\ruff.exe check scripts\release_manifest.py tests\test_release_config_p11.py`,
  `.venv\Scripts\mypy.exe app scripts\release_manifest.py`,
  target release-manifest pytest selection with 7 tests passed, and
  `.venv\Scripts\pytest.exe -q tests\test_release_config_p11.py` with
  43 tests passed.
- Current backup CRLF env hardening passed:
  `backup-postgres.sh` now strips carriage returns from `POSTGRES_USER` and
  `POSTGRES_DB` after sourcing a Windows-edited env file, before invoking
  `pg_dump`. A regression uses a CRLF env file and a fake Bash `docker`
  function that fails if any argument still contains `\r`; the backup succeeds,
  writes one dump, and creates the checksum sidecar. Commands run:
  `bash -n infra/scripts/backup-postgres.sh infra/scripts/restore-postgres.sh`,
  `.venv\Scripts\ruff.exe format tests\test_release_config_p11.py`,
  `.venv\Scripts\ruff.exe check tests\test_release_config_p11.py`,
  Node REPL direct run of
  `.venv\Scripts\pytest.exe -q tests\test_release_config_p11.py` with
  35 tests passed,
  Node REPL direct run of `.venv\Scripts\mypy.exe app`,
  and Node REPL direct run of `git diff --check`. An initial ruff run found a
  long Bash snippet line in the new test; it was split and the final ruff check
  passed.
- Current restore production-override CRLF hardening passed:
  `restore-postgres.sh` now strips carriage returns from
  `RESTORE_ALLOW_PRODUCTION` before evaluating the production restore guard,
  matching its existing cleanup for `APP_ENV`, `POSTGRES_USER`, and
  `POSTGRES_DB`. A regression uses a CRLF env file with
  `APP_ENV=production` and `RESTORE_ALLOW_PRODUCTION=1`, plus a fake Bash
  `docker` function that fails if any argument still contains `\r`; the restore
  passes the guard and reaches the fake restore without leaking carriage returns
  into arguments. Commands run:
  `bash -n infra/scripts/backup-postgres.sh infra/scripts/restore-postgres.sh`,
  `.venv\Scripts\ruff.exe format tests\test_release_config_p11.py`,
  `.venv\Scripts\ruff.exe check tests\test_release_config_p11.py`,
  Node REPL direct run of
  `.venv\Scripts\pytest.exe -q tests\test_release_config_p11.py` with
  36 tests passed,
  Node REPL direct run of `.venv\Scripts\mypy.exe app`,
  and Node REPL direct run of `git diff --check`.
- Current frontend dist secret-scan regression passed:
  `scripts/scan-dist-secrets.test.ts` runs the scanner against temporary dist
  directories. It verifies a real `JWT_SECRET` value present in a built asset is
  reported as `contains value from JWT_SECRET` without printing the secret
  itself, verifies Aliyun OSS v1, Aliyun OSS v4, and S3-compatible signed URLs
  are reported by marker without printing the URL or signature value, and
  verifies a clean dist passes.
  Commands run:
  `pnpm --dir apps/web exec vitest run scripts/scan-dist-secrets.test.ts` with
  1 file and 5 tests passed,
  `pnpm --dir apps/web test -- scripts/scan-dist-secrets.test.ts` with
  13 frontend test files and 47 tests passed, including 5
  `scripts/scan-dist-secrets.test.ts` cases,
  `pnpm --dir apps/web lint`,
  `pnpm --dir apps/web type-check`,
  `pnpm --dir apps/web scan-dist-secrets`,
  and `git diff --check`. Direct PowerShell attempts to run the first two
  frontend commands timed out before producing results; the final evidence above
  comes from `cmd.exe /c` runs launched through Node.

## Remaining

- Run P0 end-to-end release acceptance on the target device/browser with the
  intended release environment.
- Run a full interactive independent `/review` in a host that exposes the
  required AskUserQuestion workflow, or explicitly approve a non-interactive
  review substitute.
- Optional before shipping: run a production image build smoke. Current evidence
  covers Compose config, Nginx final-stage static artifact regression, and
  Postgres backup/restore rehearsal, not full image build/push/deploy.

## Notes

- No production `.env`, TLS cert, private audio, backup dump, or secret was
  added to the repository.
- The production compose expects real values through an env file such as
  `infra/env.production`, which is ignored by Git.
- Account deletion proof codes are returned once by API; only proof hashes and
  non-PII user hashes are retained after a successful deletion.
