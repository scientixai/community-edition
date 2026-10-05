# Dataset-JSON projection service. Standard library only: builds offline.
FROM python:3.12-slim
WORKDIR /app
COPY lib/ /app/lib/
COPY projection/server.py /app/
ENV PYTHONPATH=/app/lib
EXPOSE 8102
CMD ["python3", "/app/server.py"]
