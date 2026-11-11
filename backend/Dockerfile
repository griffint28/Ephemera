# Development image. Milestone 6 adds a production image.
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY . .
# No server until the API milestone; keep the container up for `docker compose exec/run`.
CMD ["sleep", "infinity"]
