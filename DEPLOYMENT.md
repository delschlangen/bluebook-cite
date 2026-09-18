# Deployment

## Backend (Railway)

There are two Docker build contexts in this repository and they are not
interchangeable. Pick one and leave the other alone.

| Railway root directory | Uses | Build context |
|---|---|---|
| `/` (repository root) | `Dockerfile` + `railway.json` | copies `backend/requirements.txt` and `backend/app` |
| `/backend` | `backend/Dockerfile` + `backend/railway.json` | copies `requirements.txt` and `app` |

The root pair is the one currently deployed. Both now bind to `${PORT:-8000}`,
so a mismatch no longer produces a container that listens on the wrong port and
fails every health check.

Health check: `GET /health`.

## Frontend (GitHub Pages)

Built and published by `.github/workflows/deploy.yml` on every push to `main`,
gated behind the backend test job.

The backend URL is set at build time via the `VITE_API_URL` environment
variable in that workflow. A fork pointing at its own backend needs to change
that one value.

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

With the backend on `localhost:8000`, set `VITE_API_URL=http://localhost:8000`
in `frontend/.env.local`. Both `localhost:5173` and `localhost:3000` are already
in the backend's CORS allowlist.

## Before pushing

```bash
cd backend && ruff check app tests && pytest
```

CI runs exactly this on every pull request.
