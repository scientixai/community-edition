# HTTP API contracts

Community Edition publishes versioned HTTP contracts for its runtime
services under [`docs/api/`](api/).

## Published contract

The OpenAPI 3.1 document [`docs/api/openapi.yaml`](api/openapi.yaml)
describes **API version 1** (`info.version` `1.0.0`,
`x-api-version: "1"`). It covers the CE-owned HTTP surfaces that ship
in this tree: lake objects and SQL, USDM load, projection, subscriptions
notify, transform run, adaptive construct and commit, and the connector
bridge, plus the web health endpoint and same-origin `/api` proxy shape.

Lake write and query behavior also has a narrative guide in
[`docs/lake-api.md`](lake-api.md).

## Calling the runtime

Paths in the OpenAPI document are shown through the web proxy
(`http://localhost:8080/api/<service>/...`). Each service also listens on
its Compose port with the same path suffix (for example lake
`POST /objects` on port `8105`). Getting-started examples use those
direct ports.

Clients may send `X-API-Version: 1` to pin this published contract.
The runtime serves the v1 surface whether or not the header is present.

## Compatibility

Changes to these HTTP contracts default to **backward compatible**.

When a change would break existing callers, the change ships with a
**migration note in this document** and advances the published API
version. The migration note describes how callers move forward — for
example a `/v1/...` path prefix on the affected service, or a required
version header — so existing integrations can plan the switch.

## Verifying the document against the tree

`scripts/prove-openapi-routes.py` statically compares every path in
`docs/api/openapi.yaml` to the route registrations in the service
sources on the current tip. Run it from the repository root:

```sh
python3 scripts/prove-openapi-routes.py
```
