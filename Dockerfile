# ── Этап 1: сборка React-мини-аппа (Vite) ──
# ВАЖНО: NODE_ENV=production. При NODE_ENV=development `vite build` собирает
# бандл с import.meta.env.DEV=true и React в dev-режиме — тогда в проде
# показывалась демо-таверна (fallback завязан на DEV) и тормозил React.
FROM node:20-slim AS miniapp
ENV NODE_ENV=production
WORKDIR /m
COPY miniapp/package.json miniapp/package-lock.json ./
# npm install (не ci): lock сгенерён на Windows и не содержит linux-вариантов
# платформенных optional-deps (@emnapi/* от oxlint) — строгий npm ci на них падает.
# --include=dev ФОРСИТ vite/typescript даже при NODE_ENV=production (иначе devDeps
# пропустятся) — поэтому dev-зависимости ставятся, а сборка остаётся продакшен-режима.
RUN npm install --include=dev --no-audit --no-fund
COPY miniapp/ ./
RUN npm run build      # → /m/dist (отдаётся питоном под /app)

# ── Этап 2: бот + веб-сервер ──
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot/ bot/
COPY assets/ assets/
COPY --from=miniapp /m/dist miniapp/dist

CMD ["python", "-m", "bot.main"]
