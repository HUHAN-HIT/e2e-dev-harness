#!/usr/bin/env node
// prepack hook: purge build/runtime residue from the bundled skill before npm
// packs it. A directory listed in package.json "files" is force-included by
// npm-packlist and its contents CANNOT be carved out by .npmignore/.gitignore,
// so the only reliable way to keep __pycache__/*.pyc and harness run artifacts
// out of the tarball is to delete them on disk first. Idempotent; only touches
// git-ignored residue, never source.
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const ROOTS = ["skills/e2e-dev-harness", "bin", "lib", "tools"];
const DIR_NAMES = new Set(["__pycache__", ".pytest_cache", ".ruff_cache", ".e2e"]);
const FILE_EXTS = new Set([".pyc", ".pyo"]);

let removed = 0;

function purge(dir) {
  let entries;
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch {
    return; // missing dir — nothing to purge
  }
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (DIR_NAMES.has(entry.name) || entry.name.endsWith(".egg-info")) {
        fs.rmSync(full, { recursive: true, force: true });
        removed += 1;
        continue;
      }
      purge(full);
    } else if (FILE_EXTS.has(path.extname(entry.name))) {
      fs.rmSync(full, { force: true });
      removed += 1;
    }
  }
}

for (const root of ROOTS) purge(path.join(REPO_ROOT, root));
process.stdout.write(`[clean-pack] purged ${removed} residue path(s) before packing\n`);
