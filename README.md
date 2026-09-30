# CareCloud · Patient registration, in conversation

A focused full-stack take-home: a voice assistant collects patient demographics, reads **every value** back, and creates a patient only after explicit confirmation. Staff can review, search, add, update, and soft-delete registrations in a responsive dashboard.

**Synthetic-data demonstration only. This is not a production clinical system or a claim of HIPAA compliance. Do not enter real patient data.**

## What is included

- FastAPI REST API with one shared Pydantic validation contract
- SQLAlchemy persistence: SQLite for local development, PostgreSQL for deployment
- Polished, responsive, same-origin dashboard with no frontend build step
- Vapi Function tool webhook, assistant prompt and importable tool definitions
- Durable voice drafts, revision-bound review tokens, transcript-confirmation checks, atomic saves and idempotent retries
- Automated API and voice regression tests, restart persistence checks, a synthetic HTTP smoke script
- Docker/Railway configuration and unique-secret setup helper

## Quick start (Python 3.11+)

Run from this project directory. On macOS/Linux:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/setup_env.py
.venv/bin/python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Windows PowerShell (no activation-policy changes needed):

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts\setup_env.py
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000. Open your private `.env` file locally, copy `API_BEARER_TOKEN`, and use the dashboard's Connect button. The token stays in tab memory and is discarded on refresh. Never share it in a public README, screenshot, or video. Interactive API documentation is at `/docs`; send `Authorization: Bearer <API_BEARER_TOKEN>` to every `/patients` endpoint.

The API fails closed if `API_BEARER_TOKEN` is missing. The voice webhook has a separate secret and also fails closed. `/health`, `/config`, and static dashboard assets are public; they return no patient data. Vapi's public browser key and assistant ID are intentionally browser-visible; its private API key and the webhook secret never reach frontend code.

## Deployment and persistence

Recommended Railway setup:

1. Deploy this repository with its Dockerfile and add a PostgreSQL service.
2. Set `DATABASE_URL` to the PostgreSQL service's connection URL. `postgres://`, `postgresql://`, and `postgresql+psycopg://` are accepted.
3. Set unique `API_BEARER_TOKEN` and `VAPI_WEBHOOK_SECRET` values, generated locally or with your provider's secret generator. Keep these in service variables, never source control.
4. Set `ENVIRONMENT=production`, then publish an HTTPS domain. The container honors Railway's `PORT`; health check is `/health`.
5. After Vapi setup, set `VAPI_PUBLIC_KEY` and `VAPI_ASSISTANT_ID`, then redeploy.

SQLite alternative: attach a **persistent volume at `/app/data`** and keep `DATABASE_URL=sqlite:///./data/patients.db`. Railway mounts volumes as root, so this image’s non-root user cannot write a default Railway volume without an operator-approved permission/runtime change. [Railway documents a root runtime override](https://docs.railway.com/volumes#permissions); that is a security-relevant operator choice, is not applied by this project, and should not be enabled automatically. Prefer PostgreSQL on Railway to retain non-root execution. Local Docker named volumes support the non-root default. A normal unmounted container filesystem is ephemeral; a redeploy can erase it. SQLite is appropriate for this small single-instance demo, not horizontally scaled production. Prefer PostgreSQL when hosted. Only one app worker is needed. Verify persistence by creating a synthetic patient, restarting/redeploying the same service, and retrieving its UUID.

Docker local:

```sh
docker build -t carecloud-registration .
docker run --rm --env-file .env -p 8000:8000 -v carecloud-data:/app/data carecloud-registration
```

The image runs as a non-root user. A bind-mounted host directory must be writable by UID 10001. A Docker-managed named volume inherits the image directory permissions.

## Vapi setup (real voice)

See [voice/SETUP.md](voice/SETUP.md). No custom speech server or separate LLM key is required when using Vapi-managed providers. The app can be fully tested without Vapi; live speech/call behavior still needs a configured account and an actual test call.

The three tools are intentionally sequential:

1. `update_registration`: merge new/corrected/out-of-order fields into a draft; `reset=true` starts over
2. `review_registration`: validate the complete draft, freeze its current revision, generate a short-lived token, return a deterministic full readback
3. `confirm_registration`: require the current token and a new explicit affirmative user transcript, then atomically save the patient, saved-call marker, and receipt

Every edit/reset invalidates the old review. A call can save at most one patient. A repeated successful tool delivery returns its receipt; a new confirm call with the same reviewed token returns the same patient ID. The assistant never reports success before the database commit succeeds. All optional fields are offered, may be declined, and are included in the full review (with “not provided” when empty).

## API

All patient routes require `Authorization: Bearer <API_BEARER_TOKEN>`.

| Route | Result |
| --- | --- |
| `POST /patients` | Create, HTTP 201 |
| `GET /patients` | Active patients, newest first; `last_name`, `date_of_birth`, `phone_number` filters; `limit` 1–100 and `offset` |
| `GET /patients/{patient_id}` | Fetch active UUID or 404 |
| `PUT /patients/{patient_id}` | Partial update; omitted fields unchanged; optional fields can be cleared with null |
| `DELETE /patients/{patient_id}` | Soft delete, HTTP 200; hidden from future reads/searches |
| `POST /voice/webhook` | Vapi tool envelope; separate webhook bearer secret |
| `GET /health` | Database connectivity check |

Successful patient responses: `{"data": ..., "error": null}`. Lists add `meta: {total, limit, offset}`. Errors: `{"data": null, "error": {"code": "...", "message": "...", "details": [...]}}` (details when useful). Malformed JSON returns 400; missing active record 404; field validation 422; storage/unexpected errors 500 with safe messages. Auth errors use 401; missing server credentials use 503. `PUT {}` is rejected with 400. Provider tool-level failures use Vapi's required HTTP-200 `results[].error` string envelope; transport/auth errors use appropriate HTTP status.

### Field rules

- Required first/last name: 1–50 letters, hyphens, apostrophes; Unicode alphabetic letters accepted
- Required date of birth: valid nonfuture `MM/DD/YYYY`; ISO `YYYY-MM-DD` also accepted for native date inputs; public API returns `MM/DD/YYYY`
- Required sex: `Male`, `Female`, `Other`, `Decline to Answer`
- Required US phone: ten digits; familiar punctuation and optional initial `+1` normalize to ten digits
- Required address line 1 (1–200), city (1–100), valid two-letter state or DC, five-digit ZIP or ZIP+4
- Optional valid email, address line 2, insurance provider, alphanumeric insurance member ID, preferred language (English by default), emergency contact name and ten-digit US phone
- Blank optional strings normalize to null. Required fields cannot be null or blank. Unexpected fields are rejected
- UUID patient IDs; UTC ISO-8601 creation/update timestamps; soft-delete timestamp retained internally

Database constraints reinforce required values, lengths, enum/state membership, nonfuture birth date, and phone/ZIP lengths. Pydantic supplies detailed format validation consistently across REST and voice. Names and dates are not inferred from caller ID. There is deliberately no voice patient-search/disclosure tool.

## Test and inspect

```sh
.venv/bin/python -m pytest
.venv/bin/python -m ruff check app tests scripts
.venv/bin/python scripts/smoke_voice.py http://127.0.0.1:8000
```

On Windows replace `.venv/bin/python` with `.\.venv\Scripts\python.exe`. The smoke script creates one fictional patient, prints every readback value and final saved JSON, retrieves the record, and verifies an identical retry returns the same ID. It sends synthetic Vapi-shaped HTTP messages; **it does not prove live speech recognition or telephone connectivity**.

For assessment payload observability, set `DEMO_LOG_PAYLOADS=true` **only with fictional data**. Committed REST/voice registrations are then logged as final JSON-like payloads, with an explicit synthetic-only warning. It is off by default. Tool drafts, transcripts, credentials, and raw database errors are not logged by the app. Vapi recording/transcript storage is disabled in the template; live tool-message transcript evidence is still needed for confirmation.

Suggested live demo: give details out of order, correct the phone, decline some optional values, verify the full readback, say “yes, please save,” then refresh the dashboard. Also test “no, change my city,” “start over,” invalid dates, and a declined save. See [DEMO.md](DEMO.md).

## Architecture and tradeoffs

```text
Browser staff dashboard ── bearer-auth REST ─┐
                                           ├─ FastAPI → validation → SQLAlchemy → PostgreSQL/SQLite
Vapi STT → conversational LLM → custom tools ┘
    draft → full review + nonce → new explicit consent → atomic commit
```

Core modules: `schemas.py` shared validation; `models.py` patient schema; `services.py` persistence/serialization; `main.py` routes/error boundaries; `voice.py` durable tool protocol; `static/` dashboard. The deterministic server protocol makes corrections/retries safer than relying solely on a system prompt. The language model still controls the spoken interaction; an end-to-end audio test is essential to check that it reads every value and waits for the caller.

Scope choices: no appointments, diagnoses, insurance verification, duplicate patient auto-linking, return-caller identity matching, or multilingual conversation. These would expand safety and identity requirements without improving this registration task. Repeated patients across different calls are permitted because duplicate matching can incorrectly merge people; idempotency prevents retries within one call from duplicating a save.

Production work intentionally left out: staff SSO/RBAC, patient identity verification, tenant isolation, rate limiting/WAF, comprehensive audit trails, encryption/key-management policies, data-retention/erasure policy, clinical consent/legal review, BAA/vendor review, database migrations/backups and disaster recovery. `create_all` is convenient for this fresh assessment database; use versioned migrations for schema evolution. Drafts and receipts persist and need an explicit retention policy before any real deployment.

## Assessment notes

Managed voice infrastructure and AI-assisted development were used. The deliverable remains inspectable: prompt, tool contracts, validation, persistence, tests, and limitations are in this repository. API/contract tests and a live audio call are different verification stages; only claim live success after observing a real configured call create a record.
