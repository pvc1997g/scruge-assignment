# Build context is the repository root (see compose.yaml) so the explainer doc in /docs is available.

FROM node:22-alpine AS deps
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

FROM node:22-alpine AS build
WORKDIR /app/frontend
ENV NEXT_TELEMETRY_DISABLED=1
# Where the Next.js server proxies /api/* to. Baked in at build time; "backend" is the compose service name.
ARG BACKEND_URL=http://backend:8000
ENV BACKEND_URL=${BACKEND_URL}
COPY --from=deps /app/frontend/node_modules ./node_modules
COPY frontend/ ./
COPY docs/ /app/docs/
RUN npm run build

FROM node:22-alpine AS run
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
COPY --from=build --chown=node:node /app/frontend/.next/standalone ./
COPY --from=build --chown=node:node /app/frontend/.next/static ./.next/static
COPY --from=build --chown=node:node /app/frontend/public ./public
COPY --chown=node:node docs/ ./docs/
USER node
EXPOSE 3000
CMD ["node", "server.js"]
