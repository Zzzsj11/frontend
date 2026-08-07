# MV Agent Python Backend

FastAPI backend for the MV storyboard frontend. The first integration slice contains:

- OpenAI-compatible streaming chat sessions with SSE events
- Yinghe asynchronous image generation
- Yinghe/Seedance asynchronous video generation
- unified generation-job polling and SSE progress
- local development storage and Volcengine TOS storage
- remote generated-media archival, so expiring provider URLs are not exposed to the UI
- PostgreSQL persistence for chat sessions, messages, and generation jobs
- Redis hot cache, progress-event stream, and cross-process pub/sub

## Run locally

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
docker compose up -d
alembic upgrade head
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

In another terminal, start the Vue frontend with `npm run dev`. Vite proxies `/api` and `/media` to port 8000.

## Run the complete stack with Docker

From the repository root, `docker compose up -d --build` starts the Vue/Nginx frontend, FastAPI backend, PostgreSQL, and Redis. The frontend is available at `http://127.0.0.1:5173`; backend traffic is routed through Nginx.

The local unified AIGC credential is mounted as the Compose secret `provider_config`. It is used by Chat, image generation, and video generation unless `LLM_API_KEY`, `IMAGE_API_KEY`, or `VIDEO_API_KEY` explicitly overrides it. Secret files are excluded from both Git and Docker build contexts.

## Configuration

The browser never receives provider or TOS credentials. Put them in `backend/.env` only.

- `LLM_*`: OpenAI-compatible chat model
- `IMAGE_*`: Yinghe image task API
- `VIDEO_*`: Yinghe Seedance task API
- `DATABASE_URL`: PostgreSQL SQLAlchemy async connection URL
- `REDIS_URL`: Redis connection URL
- `STORAGE_BACKEND=local`: saves under `backend/data/media`
- `STORAGE_BACKEND=tos`: archives references and generated assets to TOS

TOS settings follow the conventions used by `chouka-tools`: separate reference/video buckets and prefixes, with `TOS_PUBLIC_BUCKET_DOMAIN` producing stable public URLs.

PostgreSQL is the source of truth for durable business data. Redis only stores hot job state and transient SSE/pub-sub events; restarting or flushing Redis does not delete persisted jobs or conversations. To avoid common local port conflicts, the included Compose file exposes PostgreSQL on `5433` and Redis on `6380` by default and keeps both in named Docker volumes. Override them with `POSTGRES_PORT` and `REDIS_PORT` when needed.

For schema changes, create and apply Alembic migrations instead of editing the database manually:

```bash
alembic revision --autogenerate -m "describe change"
alembic upgrade head
```

## Main endpoints

- `GET /api/health`
- `POST /api/uploads`
- `POST /api/uploads/import`
- `POST /api/generations/images`
- `POST /api/generations/videos`
- `GET /api/generations/{job_id}`
- `GET /api/generations/{job_id}/events`
- `POST /api/chat/sessions`
- `POST /api/chat/{session_id}/messages`
- `GET /api/chat/{session_id}/events`
- `POST /api/chat/{session_id}/interrupt`

## Reference images containing real faces

TOS URLs work for ordinary illustrations and generated characters. For identifiable real-person references, the upstream video provider may reject a direct public URL as sensitive privacy content. The production path should create an upstream image asset first and send `asset://<asset_id>` to video generation. That asset workflow is intentionally kept separate from the generic upload endpoint and is the next integration step.
