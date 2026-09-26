# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

FROM base AS deps
COPY requirements.txt /tmp/requirements.txt
RUN pip install --prefix=/install -r /tmp/requirements.txt

FROM base AS runtime
LABEL org.opencontainers.image.title="codestra-document-intelligence" \
      org.opencontainers.image.source="https://github.com/ingtrader21-spec/Codestra-Document-Intelligence"
RUN groupadd --system --gid 10001 docintel && useradd --system --uid 10001 --gid docintel --no-create-home docintel
COPY --from=deps /install /usr/local
WORKDIR /srv
COPY app ./app
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=2).status==200 else 1)"
CMD ["uvicorn", "app.main:build_default_app", "--factory", "--host", "0.0.0.0", "--port", "8080", \
     "--no-server-header", "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1", "--timeout-graceful-shutdown", "20"]
