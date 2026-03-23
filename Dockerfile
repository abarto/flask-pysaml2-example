FROM python:3.12-slim-bullseye

ENV PYTHONUNBUFFERED=1
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

RUN DEBIAN_FRONTEND=noninteractive apt-get --yes update && \
    apt-get --yes install --no-install-recommends xmlsec1 libffi-dev && \
    rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.10.4 /uv /uvx /bin/

ENV PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY uv.lock pyproject.toml ./
RUN uv sync --frozen --no-dev

COPY . /app

RUN uv sync --frozen --no-dev

EXPOSE 5000

CMD ["uv", "run", "gunicorn", "--bind", "0.0.0.0:5000", "flask_pysaml2_example:create_app()"]
