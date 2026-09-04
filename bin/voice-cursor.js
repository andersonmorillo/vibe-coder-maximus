#!/usr/bin/env node
"use strict";

const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

const SUBCOMMANDS = new Set(["start", "doctor", "listen-test"]);

function packageRoot() {
  return path.resolve(__dirname, "..");
}

function pythonBin() {
  const override = (process.env.VOICE_CURSOR_PYTHON || "").trim();
  if (override) return override;
  const root = packageRoot();
  const venv =
    process.platform === "win32"
      ? path.join(root, ".venv", "Scripts", "python.exe")
      : path.join(root, ".venv", "bin", "python");
  if (fs.existsSync(venv)) return venv;
  return process.platform === "win32" ? "python" : "python3";
}

function hasFlag(args, flag) {
  return args.some((arg) => arg === flag || arg.startsWith(`${flag}=`));
}

function startFlags(args, cwd) {
  const out = [];
  if (!hasFlag(args, "--engine")) out.push("--engine", "firstmate");
  if (!hasFlag(args, "--cwd")) out.push("--cwd", cwd);
  out.push(...args);
  return out;
}

function pythonArgs(userArgv, cwd) {
  const rest = [...userArgv];
  if (rest[0] === "start") {
    return ["-m", "voice_cursor", "start", ...startFlags(rest.slice(1), cwd)];
  }
  if (rest[0] && SUBCOMMANDS.has(rest[0])) {
    return ["-m", "voice_cursor", ...rest];
  }
  return ["-m", "voice_cursor", "start", ...startFlags(rest, cwd)];
}

function main() {
  const cwd = process.cwd();
  const py = pythonBin();
  const args = pythonArgs(process.argv.slice(2), cwd);
  const child = spawn(py, args, { cwd, stdio: "inherit", env: process.env });
  child.on("error", (err) => {
    console.error(
      `voice-cursor: could not start Python (${err.message}). ` +
        "Install Python 3.11+ and run npm install -g from the voice-cursor repo.",
    );
    process.exit(1);
  });
  child.on("exit", (code, signal) => {
    if (signal) process.exit(1);
    process.exit(code ?? 1);
  });
}

if (require.main === module) {
  main();
}

module.exports = { pythonArgs, startFlags, pythonBin };
