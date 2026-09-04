"use strict";

const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { pythonArgs } = require("../bin/voice-cursor.js");
const {
  ensureFirstmateRoot,
  findFirstmateRoot,
} = require("../bin/install-python.js");

test("bare command starts Cursor in the current project", () => {
  assert.deepEqual(pythonArgs([], "/tmp/proj"), [
    "-m",
    "voice_cursor",
    "start",
    "--engine",
    "cursor",
    "--cwd",
    "/tmp/proj",
  ]);
});

test("extra flags pass through", () => {
  const args = pythonArgs(["--text", "--no-tts"], "/tmp/proj");
  assert.equal(args.at(-2), "--text");
  assert.equal(args.at(-1), "--no-tts");
});

test("explicit engine is not overridden", () => {
  const args = pythonArgs(["--engine", "firstmate"], "/tmp/proj");
  assert.ok(args.includes("firstmate"));
  assert.ok(!args.includes("cursor"));
});

test("doctor is a passthrough", () => {
  assert.deepEqual(pythonArgs(["doctor", "--cwd", "/x"], "/tmp/proj"), [
    "-m",
    "voice_cursor",
    "doctor",
    "--cwd",
    "/x",
  ]);
});

test("explicit start still defaults cwd", () => {
  const args = pythonArgs(["start", "--text"], "/work/app");
  assert.deepEqual(args.slice(0, 7), [
    "-m",
    "voice_cursor",
    "start",
    "--engine",
    "cursor",
    "--cwd",
    "/work/app",
  ]);
});

test("global installer finds a Firstmate ancestor", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "voice-cursor-firstmate-"));
  for (const marker of [
    "AGENTS.md",
    path.join("bin", "fm-inbox.sh"),
    path.join("bin", "fm-sessionstart-cursor.sh"),
    path.join(".cursor", "hooks.json"),
  ]) {
    const file = path.join(root, marker);
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, "");
  }
  const project = path.join(root, "vibe-coder-maximus", "nested");
  fs.mkdirSync(project, { recursive: true });

  assert.equal(findFirstmateRoot(project), root);
  fs.rmSync(root, { recursive: true, force: true });
});

test("global installer persists the discovered root", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "voice-cursor-firstmate-"));
  for (const marker of [
    "AGENTS.md",
    path.join("bin", "fm-inbox.sh"),
    path.join("bin", "fm-sessionstart-cursor.sh"),
    path.join(".cursor", "hooks.json"),
  ]) {
    const file = path.join(root, marker);
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, "");
  }
  const project = path.join(root, "vibe-coder-maximus");
  fs.mkdirSync(project, { recursive: true });
  const home = fs.mkdtempSync(path.join(os.tmpdir(), "voice-cursor-home-"));
  delete process.env.VOICE_CURSOR_FIRSTMATE_ROOT;
  delete process.env.FIRSTMATE_ROOT;

  assert.equal(ensureFirstmateRoot({ origin: project, home }), root);
  assert.ok(
    fs
      .readFileSync(path.join(home, ".env"), "utf8")
      .includes(`VOICE_CURSOR_FIRSTMATE_ROOT=${root}`),
  );
  fs.rmSync(root, { recursive: true, force: true });
  fs.rmSync(home, { recursive: true, force: true });
});

test("global installer preserves an existing root alias", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "voice-cursor-firstmate-"));
  for (const marker of [
    "AGENTS.md",
    path.join("bin", "fm-inbox.sh"),
    path.join("bin", "fm-sessionstart-cursor.sh"),
    path.join(".cursor", "hooks.json"),
  ]) {
    const file = path.join(root, marker);
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, "");
  }
  const project = path.join(root, "vibe-coder-maximus");
  fs.mkdirSync(project, { recursive: true });
  const home = fs.mkdtempSync(path.join(os.tmpdir(), "voice-cursor-home-"));
  const configured = path.join(root, "configured-firstmate");
  fs.writeFileSync(
    path.join(home, ".env"),
    `FIRSTMATE_ROOT=${configured}\n`,
  );
  delete process.env.VOICE_CURSOR_FIRSTMATE_ROOT;
  delete process.env.FIRSTMATE_ROOT;

  ensureFirstmateRoot({ origin: project, home });
  assert.equal(
    fs.readFileSync(path.join(home, ".env"), "utf8"),
    `FIRSTMATE_ROOT=${configured}\n`,
  );
  fs.rmSync(root, { recursive: true, force: true });
  fs.rmSync(home, { recursive: true, force: true });
});
