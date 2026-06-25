# myhouse 클라우드(읽기 전용) 이미지 — React SPA + FastAPI 만. Playwright 브라우저·수집기·봇 없음.
# 데이터는 R2 에서 받은 SQLite 스냅샷을 ro 로 서빙한다(CLOUD_READONLY=1).

# ── 1) 프론트엔드(React/Vite) 빌드 ──────────────────────────────────────────
FROM node:20-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# vite outDir = ../src/myhouse/web/dist (vite.config.ts) → /app/src/myhouse/web/dist 생성
RUN npm run build

# ── 2) 파이썬 런타임 ────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MYHOUSE_CONFIG=config.yaml \
    CLOUD_READONLY=1

# 의존성 + 패키지(editable 설치라 소스트리의 web/dist 를 그대로 서빙)
COPY pyproject.toml ./
COPY src ./src
RUN pip install -e .

# 빌드된 SPA 산출물 주입
COPY --from=frontend /app/src/myhouse/web/dist ./src/myhouse/web/dist
# 서빙에 필요한 설정(추적 단지 목록 등 — 비밀 아님). 비밀은 Fly secrets 로 주입.
COPY config.yaml ./

EXPOSE 8080
# Fly/프록시가 X-Forwarded-* 를 붙이므로 --proxy-headers 로 scheme/secure 쿠키를 정확히 인식.
CMD ["uvicorn", "myhouse.web.app:create_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8080", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
