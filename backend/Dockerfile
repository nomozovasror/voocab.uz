FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV UV_PROJECT_ENVIRONMENT=/opt/venv

# Optional dependency groups to install, space separated (`--extra` each).
# Empty for the API image, which must not grow; the worker image builds with
# `EXTRAS=tts` (docker-compose.yml) and so carries Kokoro, torch (CPU) and
# spaCy's English model -- see pyproject.toml.
ARG EXTRAS=""

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev $(for extra in $EXTRAS; do printf -- '--extra %s ' "$extra"; done)

# The Kokoro-82M weights, baked in at build time so the worker never downloads
# at runtime (and keeps working with the network off): the model, its config
# and the one voice we use, bf_emma. They land in the Hugging Face cache under
# HF_HOME; HF_HUB_OFFLINE then makes any attempt to reach the hub an error
# rather than a silent 330 MB download on first use. Only when `tts` is among
# the extras.
ENV HF_HOME=/opt/hf
RUN if echo " $EXTRAS " | grep -q " tts "; then \
      /opt/venv/bin/python -c "\
from huggingface_hub import hf_hub_download; \
[hf_hub_download('hexgrad/Kokoro-82M', f) for f in ('config.json', 'kokoro-v1_0.pth', 'voices/bf_emma.pt')]"; \
      echo 1 > /opt/hf/.baked; \
    fi
ENV HF_HUB_OFFLINE=1

COPY . .

CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
