# 빌드 컨텍스트는 저장소 루트 (docker-compose.yml 참고)
FROM python:3.11-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
# DB 파일 불러오기에 pg_restore / psql 이 필요하다 (덤프를 만든 pg_dump 17과 같은 버전 이상)
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/opt/venv PYTHONUNBUFFERED=1
COPY backend/pyproject.toml backend/uv.lock backend/
RUN cd backend && uv sync --frozen --no-dev
COPY backend backend
EXPOSE 8000
CMD ["/opt/venv/bin/uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
