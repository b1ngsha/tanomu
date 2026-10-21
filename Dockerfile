FROM node:24-slim AS admin-build
ENV PNPM_HOME=/pnpm PATH=/pnpm:$PATH
RUN corepack enable
WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/admin/package.json apps/admin/
RUN pnpm install --frozen-lockfile --filter @tanomu/admin
COPY apps/admin apps/admin
COPY tsconfig.base.json ./
RUN pnpm --filter @tanomu/admin build

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
COPY --from=admin-build /app/apps/admin/dist apps/admin/dist
ENV NODE_ENV=production
WORKDIR /app/apps/server
CMD ["node", "src/main.ts"]
