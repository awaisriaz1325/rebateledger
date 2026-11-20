# Web image (Phase 11, ADR 0018).
# RL_API_ORIGIN is read by next.config at BUILD time (the /api rewrite is resolved then),
# so it is a build argument; a build without it would proxy to 127.0.0.1:8000.
# UNVERIFIED: node:26.13.0-slim matches the locally verified runtime; the first build confirms it.
FROM node:26.13.0-slim AS build
RUN npm install -g pnpm@12.16.1
WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc ./
COPY patches ./patches
RUN pnpm install --frozen-lockfile
COPY . .
ARG RL_API_ORIGIN
ARG NEXT_PUBLIC_SITE_URL
# NEXT_PUBLIC_SITE_URL is inlined at build time (canonical links, sitemap, robots); without it
# the public pages would point at http://localhost:3000.
RUN test -n "$RL_API_ORIGIN" || (echo "RL_API_ORIGIN build arg is required" && exit 1)
RUN test -n "$NEXT_PUBLIC_SITE_URL" || (echo "NEXT_PUBLIC_SITE_URL build arg is required" && exit 1)
ENV RL_API_ORIGIN=$RL_API_ORIGIN NEXT_PUBLIC_SITE_URL=$NEXT_PUBLIC_SITE_URL NEXT_TELEMETRY_DISABLED=1
# shortcut: dev dependencies stay (next.config.ts may need typescript at start); prune once a build proves it safe.
RUN pnpm build

FROM node:26.13.0-slim
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
COPY --from=build --chown=node:node /app /app
USER node
CMD ["node_modules/.bin/next", "start", "-p", "3000"]
