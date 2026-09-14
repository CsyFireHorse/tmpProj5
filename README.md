# Agent Chat Viewer

本地运行的 coding agent 聊天记录查看器。把 Cursor、Codex、opencode 散落在本机、格式各异的会话记录，
归一化成同一套模型，用一个 Web 界面浏览、搜索、对比和导出。

**只读、只监听 127.0.0.1、不外发任何数据。**

```bash
just install          # 装后端 venv + 前端依赖
just demo             # 用合成数据起服务（不需要装任何 agent）
# 另开一个终端
just web              # http://localhost:5173
```

不想装 agent 也想看界面时用 `just demo`；要看自己机器上的真实记录就用 `just serve`。
生产模式下 `just build` 会把前端产物打进 Python 包，`agent-chat-viewer` 一条命令同源托管前后端。

## 支持的数据源

需求里是三家，但 **Cursor 实际有两套互不相通的本地存储**（IDE 的 Composer 面板和 `cursor-agent` CLI，
没有共享的 session id），所以工程上是四个适配器：

| 适配器 | 位置 | 说明 |
|---|---|---|
| `codex` | `$CODEX_HOME/sessions/YYYY/MM/DD/rollout-*.jsonl` | 唯一有官方 schema 的格式。`response_item`（协议日志）与 `event_msg`（展示日志）在同一文件里交错，转录只用前者，后者只补 token 用量 / turn diff / 错误 |
| `cursor-ide` | `<UserRoot>/globalStorage/state.vscdb` | `composerData:` / `bubbleId:` 键；工作区归属靠扫 `workspaceStorage/*`；兼容老版本内联 conversation 和 `aichat.chatdata` |
| `cursor-cli` | `~/.cursor/chats/<md5(工作区)>/<uuid>/store.db` | 内容寻址 blob；顺序在未解码的 protobuf turn graph 里，UI 明示"顺序近似"；工作区路径靠候选 md5 反查，查不到可手动绑定 |
| `opencode` | `~/.local/share/opencode/opencode.db` 或 `storage/**/*.json` | 1.2+ 的 SQLite 与旧版 JSON 文件树共用同一套归一化逻辑 |

各家落盘结构的详细调研见 [`docs/storage-formats.md`](docs/storage-formats.md)，实施计划见 [`PLAN.md`](PLAN.md)。

## 三条设计原则

1. **格式漂移只降级，不丢数据。** 除 Codex 外这些格式都没有文档、版本churn 剧烈。单条记录解析失败只记一条
   warning，无法归类的结构落到 `UnknownPart` 原样保留 JSON，UI 渲染成可展开的原始记录，会话本身照常显示。
2. **源存储绝不写入。** Cursor / opencode 运行时数据库处于 WAL 且加锁。所有 SQLite 读取都走
   `util/sqlite_ro.py`：先用 SQLite 在线备份 API（失败则连 `-wal`/`-shm` 一起复制）做一份私有快照，
   再对快照查询，连接上还加了 `PRAGMA query_only`。代码层面不存在指向源文件的写路径。
3. **不确定的事要说出来。** Cursor CLI 的消息顺序是近似的，就在会话页顶部写明；工作区 md5 反查不到，
   就显示"未知工作区"并给出绑定入口，而不是猜一个路径。

## 架构

```
packages/server   Python 3.12 + FastAPI，承担全部本地能力（读文件/SQLite、建索引、导出、探测）
packages/web      Vite 7 + React 19 + TypeScript + Tailwind v4
```

前后端只通过 HTTP 交互。前端类型不手写：后端导出 OpenAPI → `openapi-typescript` 生成
`src/api/schema.d.ts`，`just check` 会验证它没过期。

**统一数据模型**是整个项目的核心——会话 → 消息 → part 三层，part 是判别联合：
`text` / `reasoning` / `tool` / `file` / `patch` / `snapshot` / `step` / `todo` / `subtask` /
`compaction` / `error` / `unknown`。四个适配器都向它映射，每个 part 保留指回原始记录的 locator，
所以"归一化视图"和"原始视图"可以逐条对照。

**索引**在 `~/.local/state/agent-chat-viewer/index.db`（SQLite + FTS5），按源文件的
`(mtime, size)` 增量失效，启动时后台扫描并通过 SSE 推进度。它是纯缓存，删掉只是重扫一遍。

## 功能

- 四个来源的会话并排在一个列表里，可按 provider、项目、时间、子 agent 过滤与排序
- 转录渲染：markdown + 代码高亮、工具调用折叠成一行摘要（名称/参数/耗时/状态色）、推理默认折叠、
  patch 渲染成带增删计数的彩色 diff、附件与用量内联
- `⌘K` 跨会话跨 provider 全文检索，命中高亮，点击直达对应消息
- 右侧面板：会话元信息、原始 JSONL/KV 记录查看器、选中 part 的原始 JSON 与源定位
- 导出 Markdown / JSON，可选脱敏（掩盖常见 token 形态与 `$HOME`）
- 用量统计：按 provider / 模型 / 日期的会话数、token、成本
- 复制恢复命令（`codex resume` / `cursor-agent --resume` / `opencode --session`），**由用户自己执行，服务端从不代跑**

## 开发

```bash
just test      # pytest + vitest
just lint      # ruff + tsc + oxlint
just check     # lint + test + 校验生成的 TS 类型没过期
just probe     # 探测本机真实存储，用来核对 docs/storage-formats.md
just fixtures  # 把合成存储写到 fixtures/ 里手工翻看
```

测试全部跑在**合成存储**上（`packages/server/src/agent_chat_viewer/demo.py` 生成，同时也是 `--demo` 的数据源）。
真实聊天记录含隐私且 CI 上不存在，一律不入库。合成数据里**故意混入了坏记录**——截断的 JSONL 行、
未知的 item 类型、悬空的 bubble 引用、非 JSON 的二进制 blob——所以容错是默认被测的，而不是事后补的。

## 隐私

这些存储里有 prompt 正文、源码片段、命令行参数、环境路径，甚至凭据。因此：默认只绑 `127.0.0.1`
（`--host` 会打印警告）；`/api/actions/reveal` 限制在已检测到的 provider 根目录内；日志不打印消息正文；
没有任何遥测或外发。
