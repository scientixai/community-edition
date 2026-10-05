# The lake: why DuckDB, and how to swap it out

The lake replaces two AWS services with different jobs: S3 (durable
object storage for Dataset-JSON and SDTM outputs) and Athena (ad-hoc
SQL directly over those objects, schema-on-read, no load step). The
Community Edition ships filesystem-for-objects plus DuckDB-for-query.
This page records why, and gives working recipes for swapping in
Postgres, Athena, or other engines if your deployment needs them.

## Why the default is a directory plus DuckDB

**DuckDB is the honest Athena analogy.** Athena's defining trait is
that data lives as files and SQL happens over them, with no load step.
`SELECT ... FROM read_csv_auto('/lake/sdtm/vs.csv')` is that exact
model. A database-backed lake would need an ETL step (define tables,
load rows, keep them in sync with the files), which is precisely the
plumbing this edition exists to show you do not need.

**The files are the product.** SDTM datasets and Dataset-JSON are
file-shaped deliverables in clinical research: they are submitted,
exchanged, and validated as files. With the filesystem as the object
store, `ls lake/data/sdtm/` shows the actual deliverables. If the
canonical store were database tables, the files would demote to
exports.

**Zero infrastructure matches the workload.** The lake is written by
one coalesced transform worker (each run regenerates the whole SDTM
view idempotently) and read by ad-hoc queries. No concurrent writers,
no transactions, no incremental updates. Everything Postgres is good
at would go unused; its costs (schemas, migrations, another stateful
volume) would remain. The lake service holds no state at all and can
be killed and restarted with nothing to recover.

**Why not reuse the broker's Postgres?** Scorpio already runs one, so
"one fewer moving part" was a real argument. But sharing the instance
couples the pipeline's storage to the broker's internals and lifecycle
(schema, resets, `down -v`), and running a second instance forfeits
most of the argument anyway.

**When the line moves.** Concurrent or transactional writes to the
lake, incremental updates instead of idempotent regeneration, or
volumes where re-scanning files per query stops being cheap. Any of
those is the signal to move to one of the alternatives below. At demo
scale none is in sight. [Likely; revisit against real data volumes]

## The swap surface is deliberately small

Producers and consumers of the lake are decoupled by two narrow
contracts, so most of the stack never notices a swap:

**Write side.** `projection` and `transform` write plain files under
`PNE_LAKE_DIR` (compose mounts `./lake/data`). Dataset-JSON comes from
one shared helper, `pipeline/lib/dataset_json.py`. Nothing else in the
pipeline knows the lake exists.

**Read side.** The `lake` service (about 150 lines,
`lake/server.py`) exposes three endpoints the UI, the demo script, and
`lake/query.py` consume:

| Endpoint | Contract |
|---|---|
| `GET /files` | `{"files": [{"path", "bytes"}]}` |
| `GET /file?path=` | raw file content |
| `POST /sql {"sql"}` | `{"columns": [...], "rows": [[...]]}` |

Swapping the query engine means reimplementing `POST /sql` against
your engine and keeping the response shape. Swapping object storage
means changing where the two writers put files. The web UI and demo
only embed engine-specific SQL in their sample queries, so adjust
those to your engine's table names or path syntax.

## Recipe 1: Postgres as the query surface

Two variants, in increasing order of commitment.

**1a. Keep the files, query them through DuckDB's Postgres wire (no
change).** Before replacing anything, note that DuckDB can also attach
Postgres (`ATTACH 'dbname=...' AS pg (TYPE postgres)`) if you only
need to join lake files against relational data. This covers many
"we also have a database" cases without a swap. [Certain: stock
DuckDB `postgres` extension]

**1b. Load the lake into Postgres and point `/sql` at it.** Keep the
files as the canonical artifacts; treat Postgres as a query replica.

1. Add a Postgres service to `docker-compose.yaml` (or reuse an
   external instance; avoid the broker's own database):

   ```yaml
   lake-postgres:
     image: postgres:16
     environment: {POSTGRES_USER: lake, POSTGRES_PASSWORD: ${LAKE_PG_PASSWORD}, POSTGRES_DB: lake}
     volumes: ["lake-pgdata:/var/lib/postgresql/data"]
   ```

2. Add a load step at the end of the transform run. The idempotent
   full-regeneration model makes this trivial: truncate and reload on
   every run, no merge logic. Either extend
   `pipeline/transform/wrapper.py` with a `COPY`-based loader
   (psycopg, `COPY vs FROM STDIN WITH CSV HEADER`), or, with less
   code, use DuckDB as the loader since it can write to an attached
   Postgres:

   ```sql
   ATTACH 'host=lake-postgres user=lake password=${LAKE_PG_PASSWORD} dbname=lake' AS pg (TYPE postgres);
   CREATE OR REPLACE TABLE pg.vs AS SELECT * FROM read_csv_auto('/lake/sdtm/vs.csv');
   CREATE OR REPLACE TABLE pg.dm AS SELECT * FROM read_csv_auto('/lake/sdtm/dm.csv');
   ```

3. Reimplement `POST /sql` in `lake/server.py` against Postgres
   (swap the `duckdb` import for `psycopg`, connect read-only, same
   `{columns, rows}` response). Update the sample queries: table
   names (`FROM vs`) replace file paths (`FROM read_csv_auto(...)`).

Choose 1b when you want standard tooling (BI connectors, pgAdmin,
roles and grants) against the SDTM view, or when other applications
already live in Postgres.

## Recipe 2: back to the cloud (S3 + Athena)

This reintroduces exactly the services the Community Edition exists
to run without, which is a legitimate move for a production
deployment on AWS; it belongs to a specific deployment, never to the
open edition's defaults. The shape:

1. **Objects to S3.** Sync `lake/data` to a bucket after each
   transform run (`aws s3 sync /lake s3://your-lake/`), or point the
   writers at the bucket directly (mount via s3fs, or extend
   `dataset_json.py` and the wrapper to write through boto3).
   Partition if volumes warrant it (`sdtm/studyid=CARDIO-118/...`).
2. **Schema for Athena.** Declare external tables over the bucket
   with a Glue crawler or `CREATE EXTERNAL TABLE`. The CSVs carry
   headers; Dataset-JSON needs either a JSON SerDe over the `rows`
   array or, simpler, have the pipeline also emit Parquet (DuckDB can
   do the conversion: `COPY (SELECT ...) TO 'vs.parquet'`).
3. **Query surface.** Either drop the `lake` service and let users
   query Athena natively, or keep the service as a thin adapter:
   reimplement `POST /sql` with boto3's
   `start_query_execution`/`get_query_results`, mapping results to
   the same `{columns, rows}` shape so the walkthrough UI keeps
   working.

Note what does not change: the broker, the subscription listener, and
the transform stay cloud-free. S3 events could replace the "trigger
on write" hop, but the NGSI-LD subscription already covers it; do not
reintroduce SQS for a solved problem.

## Recipe 3: other engines, briefly

The same two contracts apply; pick by what you already operate.

- **ClickHouse.** Strong fit for the append-heavy, analytical shape.
  `clickhouse-local` can even query the files in place, Athena-style;
  the server flavor gives you a durable columnar store. Reimplement
  `/sql` over the HTTP interface.
- **Trino / Presto.** The self-hosted Athena. Hive connector over the
  lake directory (or MinIO, below) gives schema-on-read SQL across
  many file formats; Athena is managed Trino, so recipe 2's shape
  carries over almost verbatim. [Certain on lineage; connector
  details vary by version]
- **MinIO as S3 stand-in.** If you want the S3 API without AWS, run
  MinIO as a compose service and point either DuckDB (`httpfs`
  extension, `s3://` URLs with a custom endpoint) or Trino at it.
  This keeps the whole stack self-hosted while rehearsing the cloud
  topology.
- **BigQuery / Snowflake / Databricks.** Same pattern as recipe 2:
  land files in the vendor's staging area (GCS bucket, Snowflake
  stage, DBFS), define external or loaded tables, adapt `/sql` to the
  vendor SDK. The pipeline side still just writes files.
- **MotherDuck.** Managed DuckDB; the queries in this repo run
  unchanged, only the connection string in `lake/server.py` changes.

## Checklist for any swap

- [ ] Writers still produce the canonical files (keep this even with
      a database; the files are the deliverables).
- [ ] `POST /sql` returns `{columns, rows}` so the UI, demo script,
      and `lake/query.py` keep working.
- [ ] Sample queries in `lake/server.py` (`SAMPLE_QUERIES`), the web
      walkthrough, `infra/scripts/demo.sh`, and
      `docs/getting-started.md` updated to your engine's syntax.
- [ ] The load step (if any) lives at the end of the transform run
      and is truncate-and-reload, preserving idempotency.
- [ ] The broker, subscriptions, and transform remain untouched; a
      lake swap should never reach them.
