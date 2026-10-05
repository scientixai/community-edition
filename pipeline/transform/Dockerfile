# sdtm.oak transformation microservice.
#
# Base is rocker/r-ver (Ubuntu LTS + pinned R); sdtm.oak is the real
# open-source CDISC/pharmaverse SDTM transformation engine, installed from
# the default rocker repository (Posit Public Package Manager binaries, so
# no compilation). A thin standard-library Python wrapper exposes it as an
# HTTP service and handles broker I/O.
FROM rocker/r-ver:4.4.1

# Corporate proxy / TLS-inspection support: drop your proxy's CA
# certificates (*.crt) into pipeline/transform/build-support/ca/ before
# building and they are trusted for the R package download. The directory
# ships empty; this is a no-op on a normal network.
COPY transform/build-support/ca/ /usr/local/share/ca-certificates/pne/
RUN update-ca-certificates

# Fetch apt over HTTPS (also keeps proxies that only tunnel TLS happy)
RUN sed -i 's|http://|https://|g' /etc/apt/sources.list /etc/apt/sources.list.d/*.list 2>/dev/null || true
# python3 runs the HTTP wrapper; the -dev libraries cover sdtm.oak's
# dependency chain (xml2, stringi, fs) whether the packages arrive as
# Posit binaries or are compiled from source.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 libxml2-dev libicu-dev libuv1-dev pkg-config zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

RUN R -q -e 'install.packages("sdtm.oak"); library(sdtm.oak); cat("sdtm.oak", as.character(packageVersion("sdtm.oak")), "OK\n")'

WORKDIR /app
COPY lib/ /app/lib/
COPY transform/wrapper.py transform/oak_transform.R /app/

ENV PYTHONPATH=/app/lib
EXPOSE 8104
CMD ["python3", "/app/wrapper.py"]
