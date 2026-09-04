#!/usr/bin/env node
"use strict";

const { spawnSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const root = path.resolve(__dirname, "..");
const FIRSTMATE_MARKERS = [
  "AGENTS.md",
  path.join("bin", "fm-inbox.sh"),
  path.join("bin", "fm-sessionstart-cursor.sh"),
  path.join(".cursor", "hooks.json"),
];

function venvPython() {
  return process.platform === "win32"
    ? path.join(root, ".venv", "Scripts", "python.exe")
    : path.join(root, ".venv", "bin", "python");
}

function run(command, args) {
  const result = spawnSync(command, args, {
    cwd: root,
    stdio: "inherit",
    env: process.env,
  });
  if (result.error) {
    console.error(`voice-cursor: ${result.error.message}`);
    process.exit(1);
  }
  if (result.status !== 0) process.exit(result.status ?? 1);
}

function findPython() {
  const candidates =
    process.platform === "win32"
      ? [
          ["py", ["-3.12"]],
          ["py", ["-3.13"]],
          ["python", []],
          ["python3", []],
        ]
      : [
          ["python3.12", []],
          ["python3.13", []],
          ["python3.11", []],
          ["python3", []],
          ["python", []],
        ];
  const uv = spawnSync("uv", ["python", "find", "3.12"], {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "ignore"],
  });
  const uvPython = (uv.stdout || "").trim().split(/\r?\n/).pop();
  if (uv.status === 0 && uvPython && fs.existsSync(uvPython)) {
    candidates.unshift([uvPython, []]);
  }
  for (const [command, prefix] of candidates) {
    const probe = spawnSync(
      command,
      [
        ...prefix,
        "-c",
        "import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 14) else 1)",
      ],
      { stdio: "ignore" },
    );
    if (probe.status === 0) return { command, prefix };
  }
  console.error(
    "voice-cursor: Python 3.11-3.13 is required for WhisperX. " +
      "Install Python 3.12 (or uv), then rerun: npm install -g .",
  );
  process.exit(1);
}

function supportedVenv() {
  const probe = spawnSync(
    venvPython(),
    [
      "-c",
      "import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 14) else 1)",
    ],
    { stdio: "ignore" },
  );
  return probe.status === 0;
}

function installPythonDeps(venv) {
  const cpuTorch = [
    "--index-url",
    "https://download.pytorch.org/whl/cpu",
    "torch==2.8.0+cpu",
  ];
  const uvCpuTorch = [...cpuTorch, "--no-progress", "--link-mode", "copy"];
  const uv = spawnSync("uv", ["--version"], { stdio: "ignore" });
  if (uv.status === 0) {
    run("uv", ["pip", "install", "--python", venv, ...uvCpuTorch]);
    run("uv", [
      "pip",
      "install",
      "--python",
      venv,
      "--index-url",
      "https://download.pytorch.org/whl/cpu",
      "--extra-index-url",
      "https://pypi.org/simple",
      "--index-strategy",
      "unsafe-best-match",
      "--no-progress",
      "--link-mode",
      "copy",
      "-e",
      ".[voice,talk]",
    ]);
    return;
  }
  run(venv, ["-m", "pip", "install", "-q", ...cpuTorch]);
  run(venv, ["-m", "pip", "install", "-q", "-e", ".[voice,talk]"]);
}

function ensureTalkEnv() {
  const home = path.join(os.homedir(), ".voice-cursor");
  const dest = path.join(home, ".env");
  const example = path.join(root, ".env.example");
  fs.mkdirSync(home, { recursive: true });
  if (fs.existsSync(dest) || !fs.existsSync(example)) return;
  fs.copyFileSync(example, dest);
  console.log(`voice-cursor: wrote ${dest} — add OPENROUTER_API_KEY`);
}

function looksLikeFirstmate(candidate) {
  return FIRSTMATE_MARKERS.every((marker) =>
    fs.existsSync(path.join(candidate, marker)),
  );
}

function findFirstmateRoot(start) {
  let candidate = path.resolve(start);
  while (true) {
    if (looksLikeFirstmate(candidate)) return candidate;
    const parent = path.dirname(candidate);
    if (parent === candidate) return null;
    candidate = parent;
  }
}

function configuredFirstmateRoot() {
  return (
    process.env.VOICE_CURSOR_FIRSTMATE_ROOT ||
    process.env.FIRSTMATE_ROOT ||
    ""
  ).trim();
}

function firstmateConfigHome() {
  const configured = (process.env.VOICE_CURSOR_HOME || "").trim();
  return configured
    ? path.resolve(configured)
    : path.join(os.homedir(), ".voice-cursor");
}

function ensureFirstmateRoot(options = {}) {
  const home = options.home || firstmateConfigHome();
  const origin = options.origin || process.env.INIT_CWD || root;
  const configured = configuredFirstmateRoot();
  const discovered = configured
    ? path.resolve(configured)
    : findFirstmateRoot(origin);
  if (!discovered || !looksLikeFirstmate(discovered)) {
    if (configured) {
      console.warn(
        `voice-cursor: configured Firstmate root is not a checkout: ${discovered}`,
      );
    }
    return null;
  }

  const dest = path.join(home, ".env");
  fs.mkdirSync(home, { recursive: true });
  const existing = fs.existsSync(dest)
    ? fs.readFileSync(dest, "utf8")
    : "";
  const lines = existing.split(/\r?\n/);
  const key =
    /^\s*(?:export\s+)?(VOICE_CURSOR_FIRSTMATE_ROOT|FIRSTMATE_ROOT)\s*=(.*)$/;
  const index = lines.findIndex((line) => key.test(line));
  if (index >= 0 && lines[index].replace(key, "$2").trim()) return discovered;
  if (index >= 0) {
    lines[index] = `VOICE_CURSOR_FIRSTMATE_ROOT=${discovered}`;
  } else {
    if (lines.length && lines[lines.length - 1] !== "") lines.push("");
    lines.push(`VOICE_CURSOR_FIRSTMATE_ROOT=${discovered}`);
  }
  fs.writeFileSync(dest, `${lines.join("\n").replace(/\n+$/, "")}\n`, {
    encoding: "utf8",
    mode: 0o600,
  });
  console.log(`voice-cursor: Firstmate root configured as ${discovered}`);
  return discovered;
}

function main() {
  if (process.env.SKIP_VOICE_CURSOR_POSTINSTALL === "1") return;
  const venv = venvPython();
  if (!fs.existsSync(venv) || !supportedVenv()) {
    const py = findPython();
    if (fs.existsSync(venv)) fs.rmSync(path.dirname(venv), { recursive: true, force: true });
    run(py.command, [...py.prefix, "-m", "venv", ".venv"]);
  }
  installPythonDeps(venv);
  ensureTalkEnv();
  ensureFirstmateRoot();
  console.log(
    "voice-cursor: Python runtime ready. From any project: voice-cursor   or   npx voice-cursor",
  );
}

if (require.main === module) main();

module.exports = {
  findFirstmateRoot,
  ensureFirstmateRoot,
  looksLikeFirstmate,
};
