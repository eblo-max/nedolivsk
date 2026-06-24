# ── Этап 1: сборка React-мини-аппа (Vite) ──
FROM node:20-slim AS miniapp
WORKDIR /m
COPY miniapp/package.json miniapp/package-lock.json ./
RUN npm ci
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
