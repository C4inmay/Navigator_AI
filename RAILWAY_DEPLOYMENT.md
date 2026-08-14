# Railway deployment

Deploy this monorepo as two Railway services:

1. **Backend service** — root directory `backend`, Dockerfile detected automatically.
   - Health check path: `/`
   - Required variables: `GOOGLE_API_KEY`, `FRONTEND_URL`, `BROWSER_USE_HEADLESS=true`
   - Railway supplies `PORT`; do not set it manually.
2. **Frontend service** — root directory `frontend`, Dockerfile detected automatically.
   - Set `VITE_API_URL` to the public backend URL **before** the frontend build/deploy.

After Railway creates the frontend public domain, set that exact URL as `FRONTEND_URL` on the backend, then redeploy the backend to enable CORS.

`backend/data/runs/` is created automatically but Railway's normal container filesystem is not durable across redeploys or restarts. Attach a Railway Volume at `/app/data` if you need execution history to persist in production.

The backend runs Browser Use with Chromium headlessly in Railway. Local development remains headed by default; set `BROWSER_USE_HEADLESS=true` locally only when wanted.
