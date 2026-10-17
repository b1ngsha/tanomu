FROM node:24-slim
ENV PNPM_HOME=/pnpm PATH=/pnpm:$PATH
RUN corepack enable
WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/server/package.json apps/server/
COPY packages/core/package.json packages/core/
RUN pnpm install --frozen-lockfile --prod --filter @tanomu/server...
COPY apps/server apps/server
COPY packages/core packages/core
WORKDIR /app/apps/server
CMD ["node", "src/main.ts"]
