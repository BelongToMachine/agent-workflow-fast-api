FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

ARG PYPI_INDEX_URL=https://pypi.org/simple
ENV PIP_INDEX_URL=${PYPI_INDEX_URL} \
    UV_INDEX_URL=${PYPI_INDEX_URL}

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN pip install --no-cache-dir "uv>=0.6,<1.0" \
    && uv sync --frozen --no-dev --no-install-project \
    && pip uninstall -y uv

COPY app ./app

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
