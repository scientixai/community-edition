#!/usr/bin/env node
/**
 * npx pne-community-edition [install|up|down|demo|status]
 *
 * Thin wrapper with zero npm dependencies: checks Docker, downloads the
 * pinned release tarball, and drives docker compose. The canonical
 * installer is install.sh in the repository; this exists for the npx
 * crowd and does the same things.
 *
 * Env overrides: PNE_VERSION, PNE_REPO, PNE_DIR.
 */
"use strict";

const { execFileSync, spawnSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const VERSION = process.env.PNE_VERSION || "0.1.0";
const REPO = process.env.PNE_REPO || "scientixai/community-edition";
const DIR = path.resolve(process.env.PNE_DIR || "./pne-community-edition");

const say = (msg) => console.log(`\x1b[1m[pne]\x1b[0m ${msg}`);
const fail = (msg) => {
  console.error(`\x1b[1;31m[pne]\x1b[0m ${msg}`);
  process.exit(1);
};

function checkDocker() {
  const probe = (args) =>
    spawnSync("docker", args, { stdio: "ignore" }).status === 0;
  if (!probe(["--version"]))
    fail("Docker is required. Install it from https://docs.docker.com/get-docker/");
  if (!probe(["info"]))
    fail("Docker is installed but the daemon is not reachable. Start Docker and retry.");
  if (!probe(["compose", "version"]))
    fail("Docker Compose v2 is required (the 'docker compose' subcommand).");
}

function compose(args, opts = {}) {
  const result = spawnSync("docker", ["compose", ...args], {
    cwd: DIR,
    stdio: "inherit",
    ...opts,
  });
  if (result.status !== 0) process.exit(result.status ?? 1);
}

async function download() {
  if (fs.existsSync(path.join(DIR, "docker-compose.yaml"))) {
    say(`Using existing install at ${DIR}`);
    return;
  }
  const url = `https://github.com/${REPO}/archive/refs/tags/v${VERSION}.tar.gz`;
  say(`Downloading ${url}`);
  const resp = await fetch(url, { redirect: "follow" });
  if (!resp.ok)
    fail(`Download failed (${resp.status}). Does tag v${VERSION} exist on github.com/${REPO}?`);
  fs.mkdirSync(DIR, { recursive: true });
  const tarball = path.join(DIR, ".pne-release.tar.gz");
  fs.writeFileSync(tarball, Buffer.from(await resp.arrayBuffer()));
  execFileSync("tar", ["-xzf", tarball, "-C", DIR, "--strip-components=1"]);
  fs.unlinkSync(tarball);
}

async function waitForBroker() {
  say("Waiting for the broker (JVM startup takes a moment)...");
  for (let i = 0; i < 60; i++) {
    try {
      const resp = await fetch("http://localhost:9090/q/health");
      if (resp.ok) return;
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 5000));
  }
  fail("Broker did not become healthy in 5 minutes. Inspect: docker compose logs scorpio");
}

async function main() {
  const command = process.argv[2] || "install";
  checkDocker();
  switch (command) {
    case "install":
      await download();
      say("Pulling prebuilt images where available...");
      spawnSync("docker", ["compose", "pull", "--ignore-buildable"], {
        cwd: DIR,
        stdio: "ignore",
      });
      say("Starting the stack (compose builds any image that could not be pulled)...");
      compose(["up", "-d"]);
      await waitForBroker();
      say("");
      say("Open the walkthrough:    http://localhost:8080");
      say("First-run setup wizard:  http://localhost:8080/setup.html");
      break;
    case "up":
      compose(["up", "-d"]);
      break;
    case "down":
      compose(["down"]);
      break;
    case "status":
      compose(["ps"]);
      break;
    case "demo": {
      const script = path.join(DIR, "infra", "scripts", "demo.sh");
      if (!fs.existsSync(script)) fail(`No install found at ${DIR}. Run: npx pne-community-edition install`);
      const result = spawnSync(script, { cwd: DIR, stdio: "inherit" });
      process.exit(result.status ?? 1);
    }
    default:
      fail(`Unknown command '${command}'. Use: install | up | down | demo | status`);
  }
}

main().catch((err) => fail(String(err)));
