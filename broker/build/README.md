# Optional: build the broker from source (Tier B)

The published `scorpiobroker/all-in-one-runner:java-6.0.1` image is the
default and needs no build. Build from source only to produce a
Scientix-branded image or to control the supply chain.

Recipe outline, grounded against the upstream repository
(`github.com/ScorpioBroker/ScorpioBroker`, a Quarkus/Maven multi-module
project):

1. Clone the repository and check out the 6.0.1 line:
   `git clone https://github.com/ScorpioBroker/ScorpioBroker && git checkout 6.0.1`
2. Build the AllInOneRunner module with the in-memory messaging
   profile. Scorpio's build docs and its `docker/` assembly show the
   exact Maven invocation; the shape is
   `mvn clean package -DskipTests -Pin-memory -pl AllInOneRunner -am`.
   Prefer the JVM build over native-image to start; GraalVM adds
   toolchain risk for no demo benefit.
3. Build a JVM image from the produced runner jar (the upstream
   `docker/` Dockerfiles are the reference) and tag it, for example
   `scientixai/pne-scorpio:6.0.1-inmemory`.
4. Verify: the container boots with "Profile in-memory activated" in
   the log and serves `GET /ngsi-ld/v1/entities` and `GET /q/health`.
5. Point the stack at it: `PNE_SCORPIO_IMAGE=scientixai/pne-scorpio:6.0.1-inmemory docker compose up -d`.

Effort estimate: roughly half a day for someone comfortable with
Quarkus/Maven; the main risks are the Java version pin and Maven
dependency resolution through a proxy. [Likely; not exercised in this
repo, which ships on the published image by decision 5 in
docs/decisions.md]

Do not attempt to reproduce a "6.0.10": there is no upstream 6.0.10,
and matching a re-packager's tag has no value.
