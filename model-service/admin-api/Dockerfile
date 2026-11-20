ARG PYTHON_IMAGE=python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
FROM ${PYTHON_IMAGE}
ENV PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple
WORKDIR /service
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY control ./control
RUN useradd --uid 10002 --create-home control
USER control
EXPOSE 8012
CMD ["uvicorn","control.main:app","--host","0.0.0.0","--port","8012"]
