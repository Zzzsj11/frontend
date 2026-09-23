ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}
ENV PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple
WORKDIR /service
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY control ./control
RUN useradd --uid 10002 --create-home control
USER control
EXPOSE 8012
CMD ["uvicorn","control.main:app","--host","0.0.0.0","--port","8012"]
