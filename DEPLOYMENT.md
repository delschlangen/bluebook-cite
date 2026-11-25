# Deployment

The frontend and backend deploy separately. `/health` reports which build and
which host answered, so a mismatch is diagnosable rather than guessable:

```bash
curl -s https://<backend>/health
# {"status":"healthy","commit":"aa95432","host":"vercel","endpoints":[...]}
```

If the page calls an endpoint missing from that `endpoints` list, the backend
is behind the frontend and needs to redeploy. The UI says so in those words.

## Backend on Vercel

> **Known problem, not fixed.** The Vercel project builds and reports READY, but when last
> checked every path (including `/` and `/openapi.json`) answered `{"detail":"Not Found"}`,
> while the same app answers normally under uvicorn and through the same `api/index.py`
> entry file locally. The likely cause is the catch-all rewrite handing the app the rewritten
> path instead of the original one, but that was not confirmed. The project also had Vercel
> Authentication switched on, which blocks a browser on another origin from calling it at all.
> The live site uses the Railway backend. Treat Vercel as unsupported until this is resolved.

The project root directory must be set to `backend` in the Vercel project
settings. Everything else is in the repository:

| File | Role |
|---|---|
| `backend/api/index.py` | exports the ASGI `app` that Vercel serves |
| `backend/vercel.json` | rewrites every path to that function, bundles `app/**` |
| `backend/.vercelignore` | keeps tests and container files out of the bundle |
| `backend/requirements.txt` | installed at build time |

Two things to know. The function does not assume ASGI lifespan events fire,
because some serverless runtimes never send them; the lookup service is created
on first use instead. And `maxDuration` is set to 60 seconds, which needs Fluid
compute enabled. On a plan capped lower, reduce the budgets below to match, or
requests will be cut off mid-lookup.

Optional environment variables, all with working defaults:

| Variable | Default | Purpose |
|---|---|---|
| `LOOKUP_READ_TIMEOUT` | `8` | seconds per outbound lookup |
| `COMPLETION_BUDGET_SECONDS` | `25` | total lookup budget for one document |
| `REPAIR_BUDGET_SECONDS` | `20` | total budget for one `/api/repair` call |
| `MAX_UPLOAD_MB` | `10` | upload size cap |
| `MAX_TEXT_CHARS` | `1500000` | longest document text, any format |
| `MAX_PDF_PAGES` | `400` | longest PDF, read from the file before any page is processed |
| `ANALYSIS_DEADLINE_SECONDS` | `90` | total time for one analysis, then a readable 504 |
| `MAX_QUEUED_ANALYSES` | `2` | analyses allowed to wait behind the running one, then a 503 |
| `MAX_CITATIONS_RETURNED` | `2000` | citations in one response (the true total is still reported) |
| `MAX_CLAIMS_RETURNED` | `500` | unsourced claims in one response |
| `MAX_REPAIR_CHARS` | `2000` | paste size cap |
| `MAX_SMALL_BODY_KB` | `64` | request body for every endpoint except upload and analyze |
| `MAX_FIELD_CHARS` | `2000` | longest text field those endpoints accept (one citation, a case name, a search phrase); longer is a 413 that names the field |
| `MAX_CITATIONS_ANALYZED` | `50000` | citations one analysis will build; more is a 413 |
| `MAX_CLAIMS_FOR_SOURCES` | `25` | claims the legacy source-finding endpoints search outside sources for |
| `EVENT_LOOP_STALL_EXIT_S` | `45` | end the process if the event loop stalls this long, so the host restarts it (`0` = off) |
| `CPU_JOB_MAX_S` | `180` | end the process if one analysis thread runs this long (`0` = off) |
| `PARSE_CHILD_MEM_MB` | `1024` | address-space ceiling for the child process that reads one upload |
| `PARSE_CHILD_CPU_S` | `40` | processor-time ceiling for that child |
| `PARSE_WALL_S` | `35` | wall-clock limit for that child, then it is killed and the page is told the document is too complex |
| `PARSE_MAX_CONCURRENT` / `PARSE_MAX_QUEUE` | `2` / `3` | uploads read at once / allowed to wait, then a 503 with `Retry-After` |

The upload endpoint starts `python -m app.services.parse_worker` as a child process, so the host
must allow the server to start processes (a container host does; check it on a serverless one).

## Backend on a container host (Railway)

Still supported and unchanged. There are two Docker build contexts and they are
not interchangeable, so pick one:

| Root directory | Uses | Build context |
|---|---|---|
| `/` | `Dockerfile` + `railway.json` | copies `backend/requirements.txt` and `backend/app` |
| `/backend` | `backend/Dockerfile` + `backend/railway.json` | copies `requirements.txt` and `app` |

Both bind `${PORT:-8000}`, so a mismatched pair can no longer produce a
container listening on the wrong port. Health check is `GET /health`.

## Pointing the frontend at a backend

Set a **repository** variable named `API_URL` under Settings, Secrets and
variables, Actions, Variables. Not an environment variable: an environment
variable needs `environment:` on the build job, which is what silently broke
this before. With nothing set, the Railway URL is used.

The next push to `main` rebuilds the site against it.

## Running locally

```bash
# Backend
cd backend
pip install -r requirements-dev.txt
uvicorn app.main:app --reload

# Frontend, in a second shell
cd frontend
npm install
npm run dev
```

Put `VITE_API_URL=http://localhost:8000` in `frontend/.env.local`. Both
`localhost:5173` and `localhost:3000` are already in the backend's CORS
allowlist.

## Before pushing

```bash
cd backend && ruff check app tests && pytest
```

CI runs exactly this on every pull request, and the Pages deploy is gated
behind it.
