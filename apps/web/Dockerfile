ARG NODE_IMAGE=docker.m.daocloud.io/library/node:22-bookworm-slim
FROM ${NODE_IMAGE}

ARG APT_MIRROR=http://mirrors.tuna.tsinghua.edu.cn/debian
ARG APT_SECURITY_MIRROR=http://mirrors.tuna.tsinghua.edu.cn/debian-security
ARG NPM_CONFIG_REGISTRY=https://registry.npmmirror.com
ARG PNPM_VERSION=10.26.1

ENV NPM_CONFIG_REGISTRY=${NPM_CONFIG_REGISTRY}

RUN sed -i \
      -e "s#http://deb.debian.org/debian#${APT_MIRROR}#g" \
      -e "s#http://deb.debian.org/debian-security#${APT_SECURITY_MIRROR}#g" \
      -e "s#http://security.debian.org/debian-security#${APT_SECURITY_MIRROR}#g" \
      /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g "pnpm@${PNPM_VERSION}" --registry="${NPM_CONFIG_REGISTRY}"

WORKDIR /workspace

COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY apps/web/package.json ./apps/web/package.json
RUN pnpm install --filter @thinking-coach/web --frozen-lockfile

COPY apps/web ./apps/web

EXPOSE 5173

CMD ["pnpm", "--dir", "apps/web", "dev"]
