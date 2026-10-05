# USDM ingest service. Standard library only: builds offline.
FROM python:3.12-slim
WORKDIR /app
COPY lib/ /app/lib/
COPY usdm/server.py /app/
COPY usdm/usdm-study.json /app/
ENV PYTHONPATH=/app/lib
EXPOSE 8101
CMD ["python3", "/app/server.py"]
