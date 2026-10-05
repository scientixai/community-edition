# Connectors

Study definitions rarely start life on the machine running the
pipeline, and SDTM outputs rarely end there. The connector bridge
covers both directions with one optional service built on rclone,
which speaks Google Drive, OneDrive, WebDAV (Nextcloud, SharePoint),
S3 and S3-compatibles (MinIO, R2, Ceph), SFTP, FTP, and dozens more
backends. One dependency instead of four hand-built clients.

Connectors are **off by default**. The core stack stays fully
offline-capable; nothing dials anywhere until you enable the profile
and configure a remote.

## Enable

```sh
docker compose --profile connectors up -d
```

The bridge appears at `:8107` (and behind the web proxy at
`/api/bridge/...`); the setup wizard's connector section activates on
the next page load.

## Two flows

**Inbox (pull).** Copies files from a remote folder into
`lake/data/inbox/<remote>/`, then ingests anything that looks like a
USDM study definition (a JSON file with a top-level `study` object)
into the broker. Drop a study in a shared folder; it becomes entities,
and the pipeline takes it from there.

**Publish.** Copies the lake's outputs (`sdtm/`, `datasetjson/`) to a
folder on the remote, where the people who consume SDTM actually work.

## Configure

Keyed backends (WebDAV, S3, SFTP, FTP) configure straight from the
setup wizard at `http://localhost:8080/setup.html`, or via the API:

```sh
curl -X POST localhost:8107/remotes -H 'Content-Type: application/json' -d '{
  "name": "sitehub", "type": "webdav",
  "params": {"url": "https://dav.example.com", "vendor": "other",
             "user": "demo", "pass": "..."}}'

curl -X POST localhost:8107/check   -H 'Content-Type: application/json' -d '{"remote": "sitehub"}'
curl -X POST localhost:8107/pull    -H 'Content-Type: application/json' -d '{"remote": "sitehub", "path": "studies"}'
curl -X POST localhost:8107/publish -H 'Content-Type: application/json' -d '{"remote": "sitehub", "path": "pne-lake"}'
```

OAuth backends (Google Drive, OneDrive) need one browser step that a
headless container cannot perform. Run rclone's guided flow once:

```sh
docker compose --profile connectors exec bridge rclone config
```

or authorize on a workstation with `rclone authorize "drive"` and
paste the token when the guided flow asks. The remote then shows up in
the wizard and works with pull and publish like any other.

## Credentials

- rclone stores credentials obscured in its config file, in the
  `bridge-config` Docker volume; they never leave the bridge container.
- The bridge only dials out to remotes you configured; it exposes
  nothing inbound beyond your localhost port mapping.
- S3 support means any S3-compatible endpoint. Pointing it at AWS is a
  deployment's choice; the core pipeline still requires nothing from
  the cloud.
