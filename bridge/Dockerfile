# Connector bridge: rclone + a thin standard-library Python wrapper.
#
# One optional service covers Google Drive, OneDrive, WebDAV, S3, SFTP,
# and every other rclone backend, instead of four hand-built clients.
# Off by default (compose profile "connectors"); the core stack stays
# fully offline-capable without it.
#
# rclone is a static Go binary; copying it from the pinned official
# image keeps this build free of package installs entirely.
FROM rclone/rclone:1.69 AS rclone

FROM python:3.12-slim
COPY --from=rclone /usr/local/bin/rclone /usr/local/bin/rclone
WORKDIR /app
COPY server.py /app/
ENV RCLONE_CONFIG=/config/rclone.conf
EXPOSE 8107
CMD ["python3", "/app/server.py"]
