"""CDISC Dataset-JSON v1.1 writer.

Produces the flat row-oriented Dataset-JSON structure (one file per
dataset) used across the pipeline: the projection service emits SDTM
trial-design domains from broker state, and the transform service wraps
sdtm.oak output. Reference: CDISC Dataset-JSON v1.1.
"""

from __future__ import annotations

import datetime
import json
import pathlib

SOURCE_SYSTEM = {"name": "pne-community-edition", "version": "0.1.2"}


def _column(name: str, label: str, data_type: str, item_group: str) -> dict:
    col = {
        "itemOID": f"IT.{item_group}.{name}",
        "name": name,
        "label": label,
        "dataType": data_type,
    }
    if data_type == "integer":
        col["targetDataType"] = "integer"
    return col


def build_dataset_json(
    name: str,
    label: str,
    columns: list[tuple[str, str, str]],
    rows: list[list],
) -> dict:
    """Build a Dataset-JSON document.

    columns: list of (NAME, Label, dataType) tuples; dataType is a
    Dataset-JSON type ("string", "integer", "float", "date", "datetime").
    rows: list of row value lists, ordered like columns.
    Returns the Dataset-JSON document as a dict.
    """
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "datasetJSONCreationDateTime": now,
        "datasetJSONVersion": "1.1.0",
        "fileOID": f"www.scientix.ai/pne-ce/{name}/{now}",
        "originator": "PNE Community Edition",
        "sourceSystem": SOURCE_SYSTEM,
        "itemGroupOID": f"IG.{name}",
        "records": len(rows),
        "name": name,
        "label": label,
        "columns": [_column(n, l, t, name) for n, l, t in columns],
        "rows": rows,
    }


def write_dataset_json(
    out_path: str | pathlib.Path,
    name: str,
    label: str,
    columns: list[tuple[str, str, str]],
    rows: list[list],
) -> dict:
    """Write one Dataset-JSON file (local filesystem helper).

    columns: list of (NAME, Label, dataType) tuples; dataType is a
    Dataset-JSON type ("string", "integer", "float", "date", "datetime").
    rows: list of row value lists, ordered like columns.
    """
    doc = build_dataset_json(name, label, columns, rows)
    out_path = pathlib.Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(doc, indent=2) + "\n")
    return {"path": str(out_path), "name": name, "records": len(rows)}
