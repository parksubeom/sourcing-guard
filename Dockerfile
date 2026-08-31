# 안심 소싱 돋보기 — 배포 이미지
#
# Python 3.11+ 필수. 코드가 런타임에 평가되는 `X | None` 표기를 쓴다.
# CI 와 같은 3.12 를 쓴다 (.github/workflows/test.yml).

FROM python:3.12-slim

# 로그가 버퍼에 갇히면 Fly 대시보드에서 실시간으로 안 보인다.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 의존성을 먼저 깔아 레이어 캐시를 살린다. 코드만 바뀌면 재설치하지 않는다.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY sourcing_guard/ ./sourcing_guard/
COPY scripts/ ./scripts/

# 루트로 돌리지 않는다. 볼륨 마운트 지점(/data)의 소유권을 넘겨야
# SQLite 가 쓰기에 실패하지 않는다.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /data \
    && chown -R app:app /app /data
USER app

EXPOSE 8080

# 워커 1개. SQLite 를 여러 프로세스가 쓰면 잠금 경합이 생기고, 데모 트래픽에는
# 1개로 충분하다. 늘려야 하면 먼저 저장소를 Postgres 로 옮긴다.
CMD ["uvicorn", "sourcing_guard.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
