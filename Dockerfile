# Stage 1: Build the React frontend
FROM node:22-slim AS frontend-build

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts

COPY frontend/ ./
# Point API calls to same-origin in production (no proxy needed)
ENV VITE_API_BASE_URL=""
RUN npm run build


# Stage 2: Production Python runtime with FastAPI + built frontend
FROM python:3.14-slim AS runtime

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install Python dependencies
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-editable

# Copy backend source
COPY backend/app/ ./app/
COPY backend/main.py ./

# Copy pre-built SQLite snapshot
COPY backend/data/ ./data/

# Copy built React frontend for static serving
COPY --from=frontend-build /build/frontend/dist ./static/

# Expose the port (Heroku/Render override via $PORT)
EXPOSE 8000

ENV REINT_SNAPSHOT_PATH=/app/data/january-2026.sqlite
ENV REINT_CORS_ORIGINS=""
ENV REINT_STATIC_DIR=/app/static

CMD ["sh", "-c", "exec uv run uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
