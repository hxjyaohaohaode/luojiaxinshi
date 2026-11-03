FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 APP_HOST=0.0.0.0 APP_PORT=7860
ENV LEGACY_PARSER_DIR=/opt/luojia-parsers
WORKDIR /app
COPY application.tar.gz /tmp/application.tar.gz
RUN tar -xzf /tmp/application.tar.gz -C /app \
    && rm /tmp/application.tar.gz \
    && pip install --no-cache-dir -r requirements.lock \
    && apt-get update \
    && apt-get install -y --no-install-recommends default-jre-headless \
    && python scripts/install_legacy_parser.py --destination /opt/luojia-parsers \
    && groupadd --gid 10001 campus \
    && useradd --uid 10001 --gid 10001 --create-home campus
COPY studio_entrypoint.py /app/studio_entrypoint.py
EXPOSE 7860
CMD ["python", "/app/studio_entrypoint.py"]
