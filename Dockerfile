FROM python:3.11-slim-bullseye

ENV PYTHONUNBUFFERED=1

RUN DEBIAN_FRONTEND=noninteractive apt-get --yes update && \
    apt-get --yes install xmlsec1 libffi-dev

ENV POETRY_VERSION=1.5.1
ENV POETRY_VENV=/opt/poetry-venv

RUN python3 -m venv $POETRY_VENV \
    && $POETRY_VENV/bin/pip install -U pip setuptools \
    && $POETRY_VENV/bin/pip install poetry==${POETRY_VERSION}

ENV PATH="${PATH}:${POETRY_VENV}/bin"

WORKDIR /app

COPY poetry.lock pyproject.toml ./
RUN poetry install

COPY . /app
WORKDIR /app

CMD ["poetry", "run", "gunicorn", "--bind", "127.0.0.1:5000", "flask_pysaml2_example:create_app()"]
