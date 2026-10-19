ARG BACKEND_BASE_IMAGE=python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
FROM ${BACKEND_BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple \
    PIP_TRUSTED_HOST=mirrors.cloud.tencent.com
WORKDIR /srv/mvagent
RUN sed -i 's|http://deb.debian.org|https://mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=3 update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*
COPY --chown=10001:10001 requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY --chown=10001:10001 alembic.ini ./
COPY --chown=10001:10001 migrations ./migrations
COPY --chown=10001:10001 app ./app
COPY --chown=10001:10001 scripts ./scripts
COPY --chown=10001:10001 docker-entrypoint.sh ./docker-entrypoint.sh
COPY --chown=10001:10001 worker-entrypoint.sh ./worker-entrypoint.sh
RUN chmod +x ./docker-entrypoint.sh ./worker-entrypoint.sh
RUN groupadd --gid 10001 mvagent && useradd --uid 10001 --gid mvagent --no-create-home mvagent \
    && mkdir -p /srv/mvagent/data \
    && chown 10001:10001 /srv/mvagent/data
USER 10001:10001
EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
