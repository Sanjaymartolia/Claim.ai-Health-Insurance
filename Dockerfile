# BASE: python:3.12-slim for a clean build. A code-only rebuild of the real image can start from
# the last one (CLAIMSENSE_DOCKER_BASE=claimsense-insurance-api-real): every package and both
# search models are already in it, so nothing is downloaded.
ARG BASE=python:3.12-slim
FROM ${BASE}
# stub (default): the free image. real: adds the hybrid policy search and builds its index, so the
# API can run with CLAIMSENSE_TOOLS=real or mcp (docker-compose.real.yml passes TOOLS=real).
ARG TOOLS=stub
WORKDIR /app
# Every package is pinned (docker/constraints-api.txt, from the last working image): a new release
# on PyPI never forces a download, and a rebuild installs what was tested. Downloads are kept in
# BuildKit caches, and the biggest one (torch) comes before the code.
COPY docker/constraints-api.txt /tmp/constraints.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    if [ "$TOOLS" = "real" ]; then \
        pip install --retries 10 --timeout 300 -c /tmp/constraints.txt torch \
            --index-url https://download.pytorch.org/whl/cpu; \
    fi
COPY pyproject.toml ./
COPY src ./src
COPY config ./config
# The synthetic claims behind /demo/claims (dev and red-team only, never the held-out set).
COPY eval/golden_dev/claims.jsonl eval/golden_dev/claims.jsonl
COPY eval/redteam/claims.jsonl eval/redteam/claims.jsonl
# Real tools read these: the policy knowledge base (search), the synthetic tariffs, and the eval
# harness's fixture mapping that seed_dev_policies uses to write the dev policies into claims-db.
COPY data/knowledge_base ./data/knowledge_base
COPY data/tariffs ./data/tariffs
COPY eval/__init__.py eval/__init__.py
COPY eval/harness ./eval/harness
# Editable, so the retrieval and tariff code find data/ and chroma-data/ under /app.
# observability: tracing with CLAIMSENSE_OTEL=otlp.
RUN --mount=type=cache,target=/root/.cache/pip \
    if [ "$TOOLS" = "real" ]; then EXTRAS="agents,mcp,observability,retrieval"; \
    else EXTRAS="agents,mcp,observability"; fi \
    && pip install --retries 10 --timeout 300 -c /tmp/constraints.txt -e ".[$EXTRAS]"
# The search index, and both search models copied out of their download cache into the image, so
# the container runs offline (HF_HUB_OFFLINE=1) and a rebuild needs no model download.
RUN --mount=type=cache,target=/hf-cache \
    if [ "$TOOLS" = "real" ]; then \
        if [ -d /root/.cache/huggingface ] && [ -z "$(ls -A /hf-cache)" ]; then \
            cp -a /root/.cache/huggingface/. /hf-cache/; \
        fi \
        && export HF_HOME=/hf-cache \
        && python -m claimsense.retrieval.index \
        && python -c "from claimsense.mcp_servers import policy_kb; policy_kb.warm_up()" \
        && mkdir -p /root/.cache && rm -rf /root/.cache/huggingface \
        && cp -a /hf-cache /root/.cache/huggingface; \
    fi
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"
CMD ["uvicorn", "claimsense.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
