#!/usr/bin/env node
// prepack hook: purge build/runtime residue from the bundled skill before npm
// packs it. A directory listed in package.json "files" is force-included by
// npm-packlist and its contents CANNOT be carved out by .npmignore/.gitignore,
// so the only reliable way to keep __pycache__/*.pyc and harness run artifacts
// out of the tarball is to delete them on disk first. Idempotent; only touches
// git-ignored residue, never source.
import nodeFs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath, pathToFileURL } from "node:url";

const REPO_ROOT = process.env.E2E_HARNESS_PACK_ROOT
  ? path.resolve(process.env.E2E_HARNESS_PACK_ROOT)
  : path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const ROOTS = ["skills/e2e-dev-harness", "bin", "lib", "tools"];
const DIR_NAMES = new Set(["__pycache__", ".pytest_cache", ".pytest-tmp", ".ruff_cache", ".e2e"]);
const FILE_EXTS = new Set([".pyc", ".pyo"]);

// Residue directories purged by name. Beyond the fixed set, the whole
// `.pytest-tmp*` / `.pytest-basetemp*` family is matched by prefix: workers run
// `pytest --basetemp .pytest-tmp-<id>` / `.pytest-basetemp-<id>`, so exact-name
// matching alone would leave suffixed run dirs behind in the packed tarball.
function isResidueDir(name) {
  return (
    DIR_NAMES.has(name) ||
    name.endsWith(".egg-info") ||
    name.startsWith(".pytest-tmp") ||
    name.startsWith(".pytest-basetemp")
  );
}

// Purge git-ignored residue under ROOTS. `fs` is injected so the EPERM/EACCES skip
// path can be exercised cross-platform in tests (an un-deletable dir behaves
// differently on Windows vs POSIX). Returns {removed, skipped} and never throws on
// locked residue — a publish must not abort because temp could not be deleted.
export function cleanPack({ root = REPO_ROOT, fs = nodeFs, stderr = process.stderr } = {}) {
  let removed = 0;
  let skipped = 0;

  function forceRemove(full) {
    try {
      fs.rmSync(full, { recursive: true, force: true, maxRetries: 3, retryDelay: 100 });
      return true;
    } catch (error) {
      if (!["EPERM", "EACCES"].includes(error?.code)) throw error;
    }
    try {
      fs.chmodSync(full, 0o700);
    } catch {
      // Best effort: Windows temp residue may already be partially inaccessible.
    }
    try {
      fs.rmSync(full, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
      return true;
    } catch (error) {
      if (!["EPERM", "EACCES"].includes(error?.code)) throw error;
      skipped += 1;
      stderr.write(`[clean-pack] warning: could not purge locked residue: ${full}\n`);
      return false;
    }
  }

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
        if (isResidueDir(entry.name)) {
          if (forceRemove(full)) removed += 1;
          continue;
        }
        purge(full);
      } else if (FILE_EXTS.has(path.extname(entry.name))) {
        fs.rmSync(full, { force: true });
        removed += 1;
      }
    }
  }

  for (const r of ROOTS) purge(path.join(root, r));
  return { removed, skipped };
}

// Run as a CLI when invoked directly (the npm prepack hook), not when imported.
if (process.argv[1] && pathToFileURL(process.argv[1]).href === import.meta.url) {
  const { removed, skipped } = cleanPack();
  process.stdout.write(`[clean-pack] purged ${removed} residue path(s) before packing`);
  if (skipped) process.stdout.write(`; skipped ${skipped} locked residue path(s)`);
  process.stdout.write("\n");
}
