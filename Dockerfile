FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 APP_HOST=0.0.0.0 APP_PORT=8765 DATA_DIR=/data
ENV LEGACY_PARSER_DIR=/opt/luojia-parsers
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock && useradd --create-home --uid 10001 campus && mkdir /data && chown campus:campus /data
COPY scripts/install_legacy_parser.py /tmp/install_legacy_parser.py
RUN apt-get update \
    && apt-get install -y --no-install-recommends default-jre-headless \
    && python /tmp/install_legacy_parser.py --destination /opt/luojia-parsers \
    && rm -rf /var/lib/apt/lists/*
COPY --chown=campus:campus app ./app
COPY --chown=campus:campus static ./static
COPY --chown=campus:campus schema ./schema
COPY --chown=campus:campus skills ./skills
COPY --chown=campus:campus docs/genui ./docs/genui
COPY --chown=campus:campus manage.py .
USER campus
VOLUME ["/data"]
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request,os; r=urllib.request.Request('http://127.0.0.1:8765/api/health',headers={'Host':os.environ.get('APP_ORIGIN','http://127.0.0.1:8765').split('://')[1]}); urllib.request.urlopen(r,timeout=3)" || exit 1
CMD ["python","manage.py","serve"]
