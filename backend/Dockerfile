ARG BACKEND_BASE_IMAGE=python:3.13-slim
FROM ${BACKEND_BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /srv/mvagent
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
# Some reusable base images expose an application virtualenv while `pip` still
# installs globally. Mirror installed packages so either Python path is valid.
RUN if [ -d /app/.venv/lib/python3.14/site-packages ]; then \
      cp -a /usr/local/lib/python3.14/site-packages/. /app/.venv/lib/python3.14/site-packages/; \
    fi
COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
COPY docker-entrypoint.sh ./docker-entrypoint.sh
RUN chmod +x ./docker-entrypoint.sh
EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
