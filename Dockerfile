FROM python:3.11.14-slim
WORKDIR /app
COPY requirements.lock /app/
RUN pip install --no-cache-dir -r requirements.lock
COPY wallex_agent /app/wallex_agent
COPY configs /app/configs
RUN useradd --uid 10001 --create-home agent && mkdir -p /app/state /app/data /app/reports && chown -R agent:agent /app
USER agent
ENV DRY_RUN=true LIVE_TRADING=false PYTHONUNBUFFERED=1 \
    LLM_PROVIDER=boxapi TRADING_MODE=shadow ENABLE_LIVE_TRADING=false \
    WALLEX_READ_ONLY=true WALLEX_ENABLE_WITHDRAWALS=false WALLEX_ENABLE_TRANSFERS=false \
    WALLEX_PRIVATE_READS_ENABLED=false BOXAPI_MODEL=openai/gpt-5.4-mini \
    BOXAPI_BASE_URL=https://ai.boxapi.ir/ai/v1 BOXAPI_TIMEOUT_SECONDS=20 \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
ENTRYPOINT ["python", "-m", "wallex_agent.cli"]
CMD ["doctor"]
