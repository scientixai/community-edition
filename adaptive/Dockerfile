# The adaptive layer: NL -> NGSI-LD entity, through the broker.
# Standard library only (the Anthropic Messages API is called over plain
# HTTPS): builds offline, runs keyless in stub mode.
FROM python:3.12-slim
WORKDIR /app
COPY pipeline/lib/pnehttp.py /app/lib/
COPY adaptive/server.py /app/
COPY adaptive/allowed.json /app/
ENV PYTHONPATH=/app/lib
EXPOSE 8106
CMD ["python3", "/app/server.py"]
