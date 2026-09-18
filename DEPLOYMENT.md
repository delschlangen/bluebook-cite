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
| `MAX_REPAIR_CHARS` | `2000` | paste size cap |

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
