FROM node:20-slim AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY --from=web /web/dist ./frontend/dist
CMD alembic upgrade head && uvicorn codeflux.app:app --host 0.0.0.0 --port ${PORT:-10000} --workers 1