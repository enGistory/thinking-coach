ARG PYTHON_IMAGE=docker.m.daocloud.io/library/python:3.12.13-slim-bookworm
FROM ${PYTHON_IMAGE}

ARG APT_MIRROR=http://mirrors.tuna.tsinghua.edu.cn/debian
ARG APT_SECURITY_MIRROR=http://mirrors.tuna.tsinghua.edu.cn/debian-security
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple
ARG UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    UV_INDEX_URL=${UV_INDEX_URL} \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:${PATH}"

RUN sed -i \
      -e "s#http://deb.debian.org/debian#${APT_MIRROR}#g" \
      -e "s#http://deb.debian.org/debian-security#${APT_SECURITY_MIRROR}#g" \
      -e "s#http://security.debian.org/debian-security#${APT_SECURITY_MIRROR}#g" \
      /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir "uv==0.11.23"

WORKDIR /app

COPY services/backend/pyproject.toml services/backend/.python-version services/backend/uv.lock ./
RUN uv sync --locked --all-groups

COPY services/backend/alembic.ini ./alembic.ini
COPY services/backend/alembic ./alembic
COPY services/backend/app ./app
COPY services/backend/scripts ./scripts
COPY services/backend/tests ./tests

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
