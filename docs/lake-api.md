# Lake Write Contract

The lake service owns all writes to the lake data directory. Other services write through the lake's HTTP API, not by direct filesystem access.

## Write API

### `POST /objects`

Write one file to the lake.

**Request:**
```json
{
  "path": "sdtm/vs.csv",
  "content": "STUDYID,DOMAIN,USUBJID,VSSEQ,...\nCARDIO-118,VS,..."
}
```

**Parameters:**
- `path` (string, required): Relative path within the lake directory. Must not contain `..` or other traversal patterns.
- `content` (string | object | array, required): File content. Objects and arrays are serialized as pretty-printed JSON. Strings are written as-is.

**Response:**
```json
{
  "path": "sdtm/vs.csv",
  "bytes": 1234
}
```

**Status codes:**
- `200`: Write succeeded
- `400`: Invalid path, missing content, or content type not supported
- `500`: Write operation failed

## Read API

The lake provides read and query operations for stored files:

### `GET /files`

List all files in the lake with their paths and sizes.

**Response:**
```json
{
  "lake": "/lake",
  "files": [
    {"path": "datasetjson/ts.json", "bytes": 523},
    {"path": "sdtm/vs.csv", "bytes": 8192}
  ]
}
```

### `GET /file?path=<path>`

Fetch the content of one file.

**Parameters:**
- `path` (query string, required): Relative path to the file

**Response:** Raw file content with appropriate `Content-Type`

### `POST /sql`

Execute a DuckDB SQL query over lake files.

**Request:**
```json
{
  "sql": "SELECT * FROM read_csv_auto('/lake/sdtm/vs.csv') LIMIT 10"
}
```

**Response:**
```json
{
  "columns": ["STUDYID", "DOMAIN", "USUBJID", ...],
  "rows": [
    ["CARDIO-118", "VS", "CARDIO-118-001", ...],
    ...
  ],
  "truncatedAt": null
}
```

## Usage Examples

### From Python (pipeline services)

```python
import pnehttp

LAKE_URL = os.environ.get("PNE_LAKE_URL", "http://lake:8105")

def lake_write(rel_path: str, content) -> dict:
    """Write content to the lake via the write API."""
    status, body = pnehttp.request(
        "POST",
        f"{LAKE_URL}/objects",
        body={"path": rel_path, "content": content},
    )
    if status != 200:
        raise RuntimeError(f"lake write failed: {status} {body}")
    return body or {}

# Write a CSV file
lake_write("sdtm/vs.csv", csv_content)

# Write a JSON document
lake_write("datasetjson/ts.json", {"name": "TS", "rows": [...]})
```

### From curl

```bash
# Write a file
curl -X POST http://localhost:8080/lake/objects \
  -H "Content-Type: application/json" \
  -d '{
    "path": "test/example.json",
    "content": {"hello": "world"}
  }'

# Read it back
curl "http://localhost:8080/lake/file?path=test/example.json"

# List all files
curl http://localhost:8080/lake/files
```

## Design Rationale

### Why a write API?

The lake directory is the local filesystem replacement for object storage (S3). In a multi-service architecture, shared filesystem access creates ownership ambiguity: which component is responsible for ensuring writes are valid, atomic, and recorded?

By routing all writes through an HTTP contract:

1. **Clear ownership**: The lake service is the single writer. Its volume mount proves this in `docker-compose.yaml`.
2. **Auditable**: Write operations are HTTP requests with request/response logging, not silent filesystem mutations.
3. **Evolvable**: The API can add validation, versioning, or write gates without changing producer code structure.
4. **Testable**: Services that write can be tested without mounting a real volume.

### Authority

The lake write contract separates capability from authority:

- **Capability**: Pipeline services construct file content (Dataset-JSON, CSV, raw extracts).
- **Authority**: Only the lake service commits those bytes to durable storage.

The write API enforces this separation. Services that produce data call `POST /objects`; the lake validates the path, creates parent directories, and writes atomically. Path validation prevents directory traversal attacks.

## Volume Mounts (Proof of Ownership)

The `docker-compose.yaml` mounts prove this contract:

```yaml
# Only lake has RW access
lake:
  volumes:
    - ./lake/data:/lake

# Producers have NO mount; they call the HTTP API
projection:
  environment:
    PNE_LAKE_URL: http://lake:8105
  # no volumes

transform:
  environment:
    PNE_LAKE_URL: http://lake:8105
  # no volumes

bridge:
  environment:
    PNE_LAKE_URL: http://lake:8105
  # no volumes
```

To verify this in a running stack:

```bash
./scripts/prove-lake-ownership.sh
```

The proof script checks that producers have no `/lake` mount, the lake has RW access, writes go through the API, and read/query paths continue to work.
