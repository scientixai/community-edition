# NGSI-LD subscription listener (the SQS/SNS replacement).
# Standard library only: builds offline.
FROM python:3.12-slim
WORKDIR /app
COPY lib/ /app/lib/
COPY subscriptions/server.py /app/
COPY subscriptions/watched-types.json /app/
ENV PYTHONPATH=/app/lib
EXPOSE 8103
CMD ["python3", "/app/server.py"]
