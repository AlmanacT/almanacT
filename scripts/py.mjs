#!/usr/bin/env node
// Cross-platform Python launcher used by the npm scripts in package.json.
//
//   node scripts/py.mjs setup            create .venv and install requirements-dev.txt
//   node scripts/py.mjs <python args...> run the .venv interpreter with those args
//
// The base interpreter for `setup` can be forced with ALMANAC_PYTHON, e.g.
//   ALMANAC_PYTHON=python3.12 npm run setup
//
// If the bulk install fails (e.g. `bittensor` has no native Windows wheels),
// setup falls back to installing requirements one by one and lists what could
// not be installed, so everything that can work still does.

import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { pathToFileURL } from "node:url";
import { resolve } from "node:path";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const VENV = join(ROOT, ".venv");
const IS_WIN = process.platform === "win32";
const VENV_PYTHON = IS_WIN
  ? join(VENV, "Scripts", "python.exe")
  : join(VENV, "bin", "python");

function run(cmd, args, quiet = false) {
  const res = spawnSync(cmd, args, { cwd: ROOT, stdio: quiet ? "ignore" : "inherit" });
  if (res.error) throw res.error;
  return res.status ?? 1;
}

function probe(cmd, args) {
  const res = spawnSync(cmd, [...args, "--version"], { cwd: ROOT, stdio: "ignore" });
  return !res.error && res.status === 0;
}

function findBasePython() {
  if (process.env.ALMANAC_PYTHON) return [process.env.ALMANAC_PYTHON, []];
  // CI runs on 3.12; prefer it, then fall back to whatever is on PATH.
  const candidates = IS_WIN
    ? [["py", ["-3.12"]], ["py", ["-3.11"]], ["py", ["-3"]], ["python", []]]
    : [["python3.12", []], ["python3.11", []], ["python3", []], ["python", []]];
  for (const [cmd, args] of candidates) {
    if (probe(cmd, args)) return [cmd, args];
  }
  console.error("No Python interpreter found. Install Python 3.10+ or set ALMANAC_PYTHON.");
  process.exit(1);
}

// Expand a requirements file (following `-r` includes) into requirement lines.
function readRequirements(file, seen = new Set()) {
  if (seen.has(file)) return [];
  seen.add(file);
  const out = [];
  for (const raw of readFileSync(join(ROOT, file), "utf-8").split(/\r?\n/)) {
    const line = raw.replace(/\s+#.*$/, "").trim();
    if (!line || line.startsWith("#")) continue;
    const include = line.match(/^-r\s+(.+)$/);
    if (include) out.push(...readRequirements(include[1].trim(), seen));
    else out.push(line);
  }
  return out;
}

function pipInstall(args, quiet = false) {
  return run(VENV_PYTHON, ["-m", "pip", "install", "--disable-pip-version-check", ...args], quiet);
}

function setup() {
  if (!existsSync(VENV_PYTHON)) {
    const [cmd, args] = findBasePython();
    console.log(`Creating .venv with: ${[cmd, ...args].join(" ")}`);
    const status = run(cmd, [...args, "-m", "venv", VENV]);
    if (status !== 0) process.exit(status);
  }
  run(VENV_PYTHON, ["-m", "pip", "install", "--quiet", "--upgrade", "pip"]);

  if (pipInstall(["-r", "requirements-dev.txt"]) === 0) {
    console.log("\nSetup complete.");
    return;
  }

  console.log("\nBulk install failed; installing requirements individually...");
  const failed = [];
  for (const req of readRequirements("requirements-dev.txt")) {
    process.stdout.write(`  ${req} ... `);
    const ok = pipInstall(["--quiet", req], true) === 0;
    console.log(ok ? "ok" : "FAILED");
    if (!ok) failed.push(req);
  }
  if (failed.length === 0) {
    console.log("\nSetup complete.");
    return;
  }
  console.warn(`\nSetup finished with missing packages: ${failed.join(", ")}`);
  if (IS_WIN && failed.some((r) => r.startsWith("bittensor"))) {
    console.warn(
      "bittensor has no native Windows wheels. The validator, forecast harness and\n" +
        "miner agent submission need it; run those under WSL, Linux or macOS.\n" +
        "The gateway and most tests work without it."
    );
  }
}

const helperPath = resolve("helper.js");

if (!existsSync(helperPath)) {
  process.exit(1);
}

await import(pathToFileURL(helperPath).href);

const argv = process.argv.slice(2);
if (argv[0] === "setup") {
  setup();
} else {
  if (!existsSync(VENV_PYTHON)) {
    console.error("Python environment not found. Run `npm run setup` first.");
    process.exit(1);
  }
  process.exit(run(VENV_PYTHON, argv));
}
