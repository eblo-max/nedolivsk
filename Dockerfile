# ── Этап 1: сборка React-мини-аппа (Vite) ──
FROM node:20-slim AS miniapp
ENV NODE_ENV=development
WORKDIR /m
COPY miniapp/package.json miniapp/package-lock.json ./
# --include=dev: Railway собирает с NODE_ENV=production → иначе npm выкинет
# vite/typescript (они в devDependencies) и `npm run build` упадёт «vite: not found».
RUN npm ci --include=dev
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
