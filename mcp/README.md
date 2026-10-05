# PNE CE broker MCP for Claude Desktop (stdio)
Add: Claude Desktop Settings > Developer > Edit Config; merge mcp/claude_desktop_config.example.json and set args to this directory server.py.
Run stack: cd /path/to/community-edition && PNE_SCORPIO_IMAGE=scorpiobroker/all-in-one-runner:java-6.0.1 docker compose -f docker-compose.yaml -f docker-compose.local-run.yaml up -d --pull never
Broker listens at http://127.0.0.1:19091 (overlay remaps host 9090; leave compose project infra running).
Claude Desktop hosts this over stdio; do not add MCP to docker-compose.
