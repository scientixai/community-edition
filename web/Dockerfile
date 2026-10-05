# Walkthrough UI + context host + same-origin API proxy.
# Standard library only: builds offline, no package installs. The seed
# batches are baked in so the browser can drive the whole scenario.
FROM python:3.12-slim
WORKDIR /app
COPY web/server.py /app/
COPY pipeline/lib/pnehttp.py /app/
COPY web/public/ /app/public/
COPY infra/seed/enrollment-batch.json infra/seed/visit-batch-baseline.json infra/seed/visit-batch-week4.json /app/public/seed/
EXPOSE 8080
CMD ["python3", "/app/server.py"]
