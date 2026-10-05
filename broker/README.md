# Broker

The Community Edition broker is upstream NEC Scorpio, in-memory
all-in-one build, run as a plain compose service:

```yaml
scorpio:
  image: scorpiobroker/all-in-one-runner:java-6.0.1
  platform: linux/amd64
  environment:
    DBHOST: scorpio-postgres
    DBPORT: "5432"
    DBNAME: ngb
    DBUSER: ngb
    DBPASS: ${SCORPIO_PG_PASSWORD:-ngb}
  ports: ["9090:9090"]
```

plus a PostGIS database (`imresamu/postgis:16-3.4`, multiarch so Apple
Silicon runs it natively).

Why this image and not something Garnet-flavored: Scorpio ships its
messaging layer as first-class build variants, visible in its release
tags as suffixes (`-java` in-memory, `-kafka`, `-sqs`, `-amqp`,
`-mqtt`). The `-java` build runs every broker service in one JVM with
in-process channels and needs no external message bus and no cloud.
Garnet used the `-sqs` variant because it deploys Scorpio as separate
Fargate containers; that was their packaging, never a Scorpio
requirement. [Certain: verified against Scorpio's release tags and by
running this image with zero AWS]

Health: `http://localhost:9090/q/health`. Entities:
`/ngsi-ld/v1/entities`. Confirm the startup log says
"Profile in-memory activated".

Version note: upstream Scorpio's newest release line is 6.0.1 (6.0.2
for some images). "6.0.10" is a third-party AWS re-packager's own image
version over roughly-6.0.1 Scorpio, not an upstream release. There is
nothing to chase. [Certain: checked upstream tags]

Scale note: if a deployment ever outgrows one JVM, the cloud-agnostic
path is Scorpio's `-kafka` variant, not a cloud queue. See
`build/README.md` for the optional from-source build.
