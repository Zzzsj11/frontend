ARG BACKEND_BASE_IMAGE=python:3.12-alpine3.24@sha256:c5ba3deef00c7758561a0f03c26f44f10589263d40e732b8748e0d1f38f6dd89
FROM ${BACKEND_BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    IMAGEIO_FFMPEG_EXE=/usr/bin/ffmpeg
WORKDIR /srv/mvagent
RUN sed -i 's|https://dl-cdn.alpinelinux.org/alpine|https://mirrors.cloud.tencent.com/alpine|' /etc/apk/repositories \
    && apk upgrade --no-cache \
    && apk add --no-cache ffmpeg font-noto-cjk
ENV PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple
COPY --chown=10001:10001 requirements.lock ./
# crcmod builds a C accelerator; the other pinned native packages supply musllinux wheels.
RUN apk add --no-cache --virtual .build-deps gcc musl-dev \
    && pip install --no-cache-dir -r requirements.lock \
    && apk del .build-deps
COPY --chown=10001:10001 alembic.ini ./
COPY --chown=10001:10001 migrations ./migrations
COPY --chown=10001:10001 app ./app
COPY --chown=10001:10001 scripts ./scripts
COPY --chown=10001:10001 docker-entrypoint.sh ./docker-entrypoint.sh
COPY --chown=10001:10001 worker-entrypoint.sh ./worker-entrypoint.sh
RUN chmod +x ./docker-entrypoint.sh ./worker-entrypoint.sh
RUN addgroup -S -g 10001 mvagent && adduser -S -D -H -u 10001 -G mvagent mvagent \
    && mkdir -p /srv/mvagent/data \
    && chown 10001:10001 /srv/mvagent/data
USER 10001:10001
EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
