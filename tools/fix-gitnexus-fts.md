# fix-gitnexus-fts — GitNexus Windows FTS 修复工具

## 问题现象

在 Windows 环境下使用 GitNexus MCP 工具查询时，返回结果中附带警告：

```
"warning": "FTS indexes missing — keyword search degraded. Run: gitnexus analyze --force to rebuild indexes."
```

即使执行 `gitnexus analyze --force` 重建索引后，问题依然存在。BM25 关键词搜索不可用，查询结果为空。

## 根因分析

GitNexus 1.6.5 的 MCP 连接池模块 (`pool-adapter.js`) 在初始化数据库连接时，**在 Windows 上硬编码跳过了 LadybugDB FTS 扩展的加载**。

相关代码位于全局包路径：

```
%APPDATA%\npm\node_modules\gitnexus\dist\core\lbug\pool-adapter.js
```

共有两处 Windows 守卫代码（约第 350 行和第 416 行），模式如下：

```js
if (process.platform === 'win32') {
    shared.ftsLoaded = true;  // 直接跳过，不尝试加载
} else {
    shared.ftsLoaded = await loadFTSExtension(available[0], { policy: 'load-only' });
}
```

**跳过原因：** LadybugDB 的 FTS 扩展在 Windows 上，如果本地未安装扩展二进制文件，`LOAD EXTENSION fts` 会触发 SIGSEGV 崩溃（C++ 层面的段错误），JS 的 try/catch 无法捕获，会导致整个进程崩溃。

**实际问题：** 当前环境的 LadybugDB 已经成功安装了 FTS 扩展（通过 `INSTALL fts`），`LOAD EXTENSION fts` 可以正常执行。GitNexus 的代码过于保守，没有尝试就跳过了。

### 影响范围

- `gitnexus query` CLI 查询：BM25 关键词搜索返回空结果，仅依赖向量/精确扫描
- MCP 工具（`gitnexus_query`）：同样返回空结果 + 警告
- 图查询（`gitnexus_context`、`gitnexus_impact` 等）：**不受影响**，正常工作
- `gitnexus analyze`：**不受影响**，FTS 索引在 analyze 时正常创建

## 修复方案

将硬编码的 Windows 跳过改为 try-catch 安全降级：尝试加载 FTS 扩展，成功则启用，失败则降级。

**修改前：**
```js
if (process.platform === 'win32') {
    shared.ftsLoaded = true;
} else {
    shared.ftsLoaded = await loadFTSExtension(available[0], { policy: 'load-only' });
}
```

**修改后：**
```js
try {
    shared.ftsLoaded = await loadFTSExtension(available[0], { policy: 'load-only' });
} catch {
    shared.ftsLoaded = true;  // 加载失败才降级
}
```

需修改同一文件中的两处（`doInitLbug` 函数和 `initLbugWithDb` 函数）。

## 使用方法

### 一键修复

```bash
node ~/.claude/tools/fix-gitnexus-fts.js
```

输出示例：

```
=== GitNexus Windows FTS 修复工具 ===

[已修复] doInitLbug 函数中的 FTS 加载
[已修复] initLbugWithDb 函数中的 FTS 加载 (1 处)

[备份] ...pool-adapter.js.bak

修复完成（共 2 处）。请重启 Claude Code 使 MCP server 加载新代码。
```

### 还原

```bash
node ~/.claude/tools/fix-gitnexus-fts.js --restore
```

### 验证修复

修复并重启 Claude Code 后，通过 MCP 工具测试：

```
gitnexus_query({ query: "支付", repo: "jeepay", limit: 3 })
```

- 修复前：返回空结果 + `"warning": "FTS indexes missing ..."`
- 修复后：返回匹配结果，无 warning 字段，timing 中 bm25 耗时 > 0

## 注意事项

1. **重启 Claude Code**：修复后必须重启 Claude Code，MCP server 进程才会加载修补后的代码。CLI 路径（`npx gitnexus query`）立即生效。

2. **GitNexus 升级后需重新运行**：`npm update -g gitnexus` 会覆盖修补后的文件，需重新执行修复脚本。

3. **安全性**：修复使用 try-catch 保护，如果 LadybugDB FTS 扩展确实不可用（未安装），会安全降级到原有行为（BM25 不可用，图查询正常），不会崩溃。

4. **备份**：首次修复时会自动创建 `.bak` 备份文件。`--restore` 命令可随时还原。

5. **版本适配**：脚本针对 GitNexus 1.6.5 编写。如果版本不同，代码模式可能不匹配，脚本会提示跳过。

## 脚本位置

```
~/.claude/tools/fix-gitnexus-fts.js
```

## 修复原理流程图

```
                  MCP 查询请求
                      │
              ┌───────┴───────┐
              │ pool-adapter  │
              │  doInitLbug   │
              └───────┬───────┘
                      │
              ┌───────┴───────┐
              │ 是 Windows？  │
              └───┬───────┬───┘
                  │       │
         修复前   │       │  修复后
                  │       │
        ┌─────────┴──┐  ┌─┴──────────┐
        │ 直接跳过    │  │ try-catch   │
        │ ftsLoaded=1 │  │ 尝试 LOAD   │
        │ 不加载 FTS  │  │ FTS 扩展    │
        └────────────┘  └──┬─────┬────┘
                           │     │
                      成功 │     │ 失败（降级）
                           │     │
                    ┌──────┴─┐ ┌─┴──────────┐
                    │ FTS 可用│ │ 标记已加载  │
                    │ BM25生效│ │ BM25 降级   │
                    └────────┘ └────────────┘
```
