#!/usr/bin/env node
// GitNexus Windows FTS 修复工具
// 用法：node fix-gitnexus-fts.js          # 修复
//       node fix-gitnexus-fts.js --restore # 还原
// 适用：GitNexus 1.6.5

const fs = require("fs");
const path = require("path");

const globalModulesDir = path.join(
  process.env.APPDATA || "", "npm", "node_modules", "gitnexus"
);
const targetFile = path.join(
  globalModulesDir, "dist", "core", "lbug", "pool-adapter.js"
);

const REPLACEMENT = [
  "if (!shared.ftsLoaded) {",
  "        try {",
  "            shared.ftsLoaded = await loadFTSExtension(available[0], { policy: 'load-only' });",
  "        }",
  "        catch {",
  "            shared.ftsLoaded = true;",
  "        }",
  "    }",
].join("\n");

function main() {
  console.log("=== GitNexus Windows FTS 修复工具 ===\n");

  if (!fs.existsSync(targetFile)) {
    console.error("错误：找不到 " + targetFile);
    process.exit(1);
  }

  let content = fs.readFileSync(targetFile, "utf8");
  const hasWin32Guard = content.includes("process.platform === 'win32'");
  const hasPatched = content.includes("loadFTSExtension(available[0], { policy: 'load-only' })")
    && content.includes("catch {");

  // 如果没有 win32 守卫且已有 try-catch，说明已修复
  if (!hasWin32Guard && hasPatched) {
    console.log("当前已是修补后状态，无需修复。");
    return;
  }
  if (!hasWin32Guard && !hasPatched) {
    console.log("未找到目标代码模式，可能 GitNexus 版本不是 1.6.5。");
    return;
  }

  let patched = 0;

  // 模式1：带多行注释的版本（doInitLbug 函数）
  const p1 = /if \(!shared\.ftsLoaded\) \{\s*\/\/ Windows guard:[\s\S]*?if \(process\.platform === 'win32'\) \{\s*shared\.ftsLoaded = true;\s*\}\s*else \{\s*shared\.ftsLoaded = await loadFTSExtension\(available\[0\], \{ policy: 'load-only' \}\);\s*\}\s*\}/;
  if (p1.test(content)) {
    content = content.replace(p1, REPLACEMENT);
    patched++;
    console.log("[已修复] doInitLbug 函数中的 FTS 加载");
  }

  // 模式2：简短版本（initLbugWithDb 函数）
  const p2 = /if \(!shared\.ftsLoaded\) \{\s*if \(process\.platform === 'win32'\) \{\s*shared\.ftsLoaded = true;\s*\}\s*else \{\s*shared\.ftsLoaded = await loadFTSExtension\(available\[0\], \{ policy: 'load-only' \}\);\s*\}\s*\}/g;
  const m2 = content.match(p2);
  if (m2) {
    content = content.replace(p2, REPLACEMENT);
    patched += m2.length;
    console.log("[已修复] initLbugWithDb 函数中的 FTS 加载 (" + m2.length + " 处)");
  }

  if (patched > 0) {
    const bak = targetFile + ".bak";
    if (!fs.existsSync(bak)) {
      fs.copyFileSync(targetFile, bak);
      console.log("\n[备份] " + bak);
    }
    fs.writeFileSync(targetFile, content, "utf8");
    console.log("\n修复完成（共 " + patched + " 处）。请重启 Claude Code 使 MCP server 加载新代码。");
  }
}

function restore() {
  const bak = targetFile + ".bak";
  if (fs.existsSync(bak)) {
    fs.copyFileSync(bak, targetFile);
    fs.unlinkSync(bak);
    console.log("已还原为原始文件。");
  } else {
    console.log("未找到备份文件，无法还原。");
  }
}

if (process.argv.includes("--restore")) {
  restore();
} else {
  main();
}
