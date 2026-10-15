FROM node:22-bookworm-slim AS ui
WORKDIR /work/frontend
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend ./
RUN npm run build
FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends unixodbc && rm -rf /var/lib/apt/lists/*
COPY requirements.lock pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.lock
COPY backend backend
RUN pip install --no-cache-dir --no-deps .
COPY scripts/install_drawio.py scripts/install_drawio.py
RUN python scripts/install_drawio.py
COPY examples examples
COPY --from=ui /work/frontend/dist frontend/dist
RUN mkdir /app/data && chown 10001:10001 /app/data
ENV FLOW_DATA=/app/data
USER 10001
EXPOSE 8080
CMD ["uvicorn","flowstudio.app:app","--app-dir","/app/backend","--host","0.0.0.0","--port","8080"]
