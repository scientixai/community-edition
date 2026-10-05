# Lake query surface: DuckDB over the lake directory (the Athena
# replacement, with zero infrastructure).
FROM python:3.12-slim

# Corporate proxy / TLS-inspection support: drop your proxy's CA
# certificates (*.crt) into lake/build-support/ca/ before building.
# The directory ships empty; this is a no-op on a normal network.
COPY build-support/ca/ /usr/local/share/ca-certificates/pne/
RUN update-ca-certificates
ENV PIP_CERT=/etc/ssl/certs/ca-certificates.crt

RUN pip install --no-cache-dir duckdb==1.1.3
WORKDIR /app
COPY server.py /app/
EXPOSE 8105
CMD ["python3", "/app/server.py"]
