FROM node:24-bookworm
RUN npm install --global pnpm@11.20.0 --no-audit --no-fund
WORKDIR /workspace
