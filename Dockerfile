# Container for hosting the API + UI + worker together (Render, Fly, any Docker host).
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements-supabase.txt backend/requirements-supabase.txt
RUN pip install --no-cache-dir -r backend/requirements-supabase.txt
COPY backend backend
COPY frontend frontend
ENV PROCESS_INLINE=true
CMD ["sh", "-c", "uvicorn supabase_api:app --app-dir backend --host 0.0.0.0 --port ${PORT:-8000}"]
