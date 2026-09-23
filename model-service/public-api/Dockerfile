ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}
ENV PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple
WORKDIR /service
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY gateway ./gateway
RUN useradd --uid 10001 --create-home service
USER service
EXPOSE 8011
CMD ["uvicorn","gateway.main:app","--host","0.0.0.0","--port","8011"]
