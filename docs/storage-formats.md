# 各 Coding Agent 本地聊天记录存储格式调研

本文是 `PLAN.md` 的附录，记录四个数据源（Cursor 有 IDE 与 CLI 两套互不相通的存储）的落盘位置与结构。
这些格式除 Codex 外**均无官方文档**，属于逆向结论，会随版本漂移；适配器必须按"宽容解析 + 保留原始 JSON"的原则实现。

> 状态说明：本文基于公开资料与社区逆向整理，**尚未在装有真实数据的机器上逐条验证**。
> 实施第一步（见 `PLAN.md` 的 M0）是跑探测脚本 `scripts/probe_stores.py`，把每项标为"已验证/需修正"。

---

## 1. Codex CLI（唯一有官方 schema 的）

### 位置

```
$CODEX_HOME/sessions/YYYY/MM/DD/rollout-<YYYY-MM-DDThh-mm-ss>-<uuid>.jsonl
$CODEX_HOME/archived_sessions/...            # 归档
$CODEX_HOME/history.jsonl                    # 全局 prompt 历史，非会话源
```

`CODEX_HOME` 未设置时默认 `~/.codex`。文件名中的时间戳把 `:` 换成了 `-`；`<uuid>` 是会话 id（UUIDv7，本身即时间有序）。
`~/.codex/` 下另有 `logs_*.sqlite`、`state_*.sqlite`、`memories_*.sqlite` 等，**是缓存和应用状态，不是会话真源**，不要读。

### 行格式（RolloutLine）

每行一个独立 JSON 对象，append-only，按时间递增：

```jsonc
{ "timestamp": "2026-08-10T13:02:51.123Z", "ordinal": 12, "type": "response_item", "payload": { ... } }
```

`type` 取值与含义：

| type | 含义 |
|---|---|
| `session_meta` | 首行头记录：`id`、`cwd`、`originator`、`cli_version`、`model_provider`、`base_instructions`、`git{commit_hash,branch,repository_url}`、`source` |
| `turn_context` | 一个 turn 的上下文边界（模型、审批策略、sandbox 等） |
| `response_item` | **协议日志**：模型真实收发的 item（`message` / `reasoning` / `function_call` / `function_call_output` / `local_shell_call` 等） |
| `event_msg` | **展示日志**：TUI 回放用的事件，与 `response_item` 内容大量重叠 |

解析策略：**以 `response_item` 为主干**构建消息树，`event_msg` 只用来补 `response_item` 里没有的信息（例如 token 用量、任务完成事件）。两条日志交错在同一文件里，不去重会出现内容翻倍。

### 子 Agent

子 agent 是**同一日期目录下的独立 rollout 文件**。父子关系通过 `session_meta` 里的 `parent_thread_id`，以及 `source` 为 `{ "subagent": { "thread_spawn": ... } }` 来判断；另有 `agent_nickname`、`agent_role`。列表页应把子会话折叠进父会话。

### 实现要点

- 列表页只需读每个文件的**前若干行**直到拿到 `session_meta`，不要全量解析。没有 `session_meta` 的文件不算会话，id 可回退到文件名里的 uuid。
- 新版 Codex 支持 rollout 压缩，需要同时处理压缩与明文两种路径。
- 权威 schema 可用 `codex app-server generate-internal-json-schema` 生成 `RolloutLine.json`，建议在 CI 里拿它做一次校验。
- 目录遍历不跟随符号链接目录（防环）。

---

## 2. Cursor CLI（`cursor-agent`）

### 位置

```
~/.cursor/chats/<md5(绝对工作区路径)>/<session-uuid>/
├── store.db              # SQLite：blobs(id, data) + meta(key, value)
├── meta.json             # title / createdAtMs / updatedAtMs
└── prompt_history.json   # 用户 prompt 字符串数组
~/.cursor/acp-sessions/<id>/store.db   # ACP 会话，结构同上
```

无环境变量可覆盖根目录。

### 结构

- `meta` 表：key `"0"` → **hex 编码**的 JSON agent 记录（`agentId`、`latestRootBlobId`、`name`、`mode`、`createdAt`、`lastUsedModel`）。
- `blobs` 表：内容寻址，`id = sha256(data)`。其中
  - **JSON blob** 承载消息（role: user / assistant / tool）；
  - **protobuf blob** 承载 turn graph（user msg → steps → turns → root）。

### 实现要点（这是最难的一个适配器）

1. **顺序重建**：正确顺序在 protobuf 的 turn graph 里，从 `latestRootBlobId` 出发遍历。首版可以只解 JSON blob、按内部时间戳排序，接受"顺序近似"，并在 UI 上标注；后续再补 protobuf。
2. **工作区路径不可逆**：目录名是路径的 md5，无法反推。做法是维护一张**反向索引**——对候选路径集合（`~/.cursor/projects/*` 解码出的路径、用户在设置里配置的项目根、最近打开过的目录）逐一算 md5 去匹配；匹配不上就显示为"未知工作区"，并允许用户手动绑定。
3. CLI 运行时会有 `store.db-wal` / `-shm`，必须只读打开（见下面第 5 节的安全读取）。
4. 恢复命令：`cursor-agent --resume <session-uuid>`（需要先 `cd` 到工作区），可以作为 UI 上的"复制恢复命令"按钮。

---

## 3. Cursor IDE（Composer / Agent 面板）

**与 CLI 完全不同的另一套存储，两者不互通、没有共享 session id。**

### 位置

用户根目录 `<UserRoot>`：

| 平台 | 路径 |
|---|---|
| macOS | `~/Library/Application Support/Cursor/User` |
| Linux | `~/.config/Cursor/User`（存在 `$XDG_CONFIG_HOME` 时优先） |
| Windows | `%APPDATA%\Cursor\User` |

```
<UserRoot>/globalStorage/state.vscdb                 # 全局：会话内容真源
<UserRoot>/workspaceStorage/<hash>/state.vscdb       # 每工作区：会话索引
<UserRoot>/workspaceStorage/<hash>/workspace.json    # 工作区文件夹 URI（= cwd）
~/.cursor/projects/<encoded-path>/agent-transcripts/*.jsonl   # IDE agent 转录（旁路数据）
```

两个库都是 SQLite，都有 `ItemTable(key, value)` 与 `cursorDiskKV(key, value)` 两张表。

### globalStorage 的 key 约定

| key 模式 | 内容 |
|---|---|
| `composerData:{composerId}` | 会话元数据：`name`、`createdAt`、`lastUpdatedAt`、`status`、`isAgentic`、`_v`、`latestConversationSummary`，以及顺序数组 `fullConversationHeadersOnly: [{bubbleId, type, serverBubbleId?}]`（老 `_v` 则是内联的 `conversation` 数组） |
| `bubbleId:{composerId}:{bubbleId}` | 单条消息：`type`（1=user，2=assistant）、`text`、`richText`（Lexical JSON）、`rawText`、`thinking:{text}`、`toolFormerData`（一次工具调用+结果）、`tokenCount:{inputTokens,outputTokens}` |
| `checkpointId:{composerId}:{checkpointId}` | 每个 agent turn 的工作区快照 / 文件 diff |
| `messageRequestContext:{composerId}:{messageId}` | 发给模型的完整请求上下文 |
| `composer.content.{hash}` | 内容寻址 blob（跨会话共享） |
| `composer.composerHeaders`（ItemTable，Cursor 3.0+） | 全局会话索引 |

### 工作区归属

扫描每个 `workspaceStorage/<hash>/state.vscdb` 的 `ItemTable['composer.composerData']`
→ `{allComposers: [{composerId, name, createdAt, ...}]}`，建立 `composerId → cwd` 映射（cwd 取自同目录 `workspace.json`）。
实测约有两成会话关联不到任何工作区，这些仍要展示，只是 `cwd = null`。

### 兼容性

- `_v` 在同一台机器上能见到 1 到 10+，字段增删频繁 → 缺字段一律跳过，禁止让单个字段缺失导致整个会话解析失败。
- 老版本把聊天塞在**工作区库**的 `ItemTable['workbench.panel.aichat.view.aichat.chatdata']` 里，需要兼容这种旧形态。
- SQLite 单值有 64 KiB 上限的历史限制，超长内容会被拆分/外链到 `composer.content.{hash}`。

---

## 4. opencode

有**两个时代**的存储，需要同时支持并按存在性自动判别。

### 4.1 新版（1.2.0+）：SQLite

```
~/.local/share/opencode/opencode.db
```

Drizzle 定义的表（关键列）：

| 表 | 列 |
|---|---|
| `session` | `id`、`directory`、`path`、`title`、`share_url`、`agent`、`model`、`mode`、父会话引用、时间戳 |
| `message` | `id`、`session_id`(FK)、`time_created`、`data`(JSON) |
| `part` | `id`、`message_id`(FK)、`session_id`、`data`(JSON) |
| `session_message` | `id`、`session_id`、`type`、`data`(JSON) |

`data` 列就是原 JSON 文件的 payload，字段语义与旧版一致，所以**归一化逻辑可以两版共用**，只换取数据的 I/O 层。
排序索引是 `(session_id, time_created, id)`，part 是 `(message_id, id)`。

### 4.2 旧版：JSON 文件

```
~/.local/share/opencode/storage/
├── project/{projectID}.json
├── session/{projectID}/{sessionID}.json
├── message/{sessionID}/{messageID}.json
├── part/{messageID}/{partID}.json
├── session_diff/{sessionID}.json
└── todo/{sessionID}.json
```

另有按项目隔离的 `~/.local/share/opencode/project/<project-slug>/storage/...`，遍历时不能只看全局目录。

### 4.3 数据模型

- **Session**：`id`（`ses_` 前缀）、`projectID`（或 `"global"`）、`directory`、`parentID`（非空即子 agent 会话）、`title`、`time{created,updated}`。
- **Message**（仅元数据，无正文）：`id`（`msg_`）、`sessionID`、`role`（user/assistant）、`parentID`、`modelID`、`providerID`、`tokens{input,output,cacheRead,cacheWrite,reasoning}`、`cost`、`time{created,completed}`、`error`、`summary`。
- **Part**（正文所在，`prt_` 前缀，**按 id 字典序排序**即为展示顺序）。part 的判别联合类型：
  `text` / `reasoning` / `file` / `tool` / `step-start` / `step-finish` / `snapshot` / `patch` / `agent` / `subtask` / `compaction` / `retry`。
  `tool` part 带 `state`：`pending | running | completed | error`，含 `input`、`output`、`title`、`metadata`、`time{start,end}`。

opencode 的 part 模型信息最全，**适合作为统一模型的设计原型**（见 `PLAN.md` 第 3 节）。

---

## 5. 跨适配器的公共问题

### 5.1 安全读取正在被写入的 SQLite

Cursor 和 opencode 的库在应用运行时处于 WAL 模式并持有锁。直接 `mode=ro` 打开可能读到撕裂状态，`immutable=1` 在有 WAL 时会读到陈旧数据，`nolock=1` 更危险。

**统一做法**：把 `xxx.db` 连同 `-wal`、`-shm` 一起复制到临时目录，再对副本执行 `PRAGMA journal_mode`/查询，用完即删。副本按 `(路径, mtime, size)` 缓存，避免每次请求都拷。**任何情况下都不得写回原库。**

### 5.2 宽容解析

每个适配器都要遵守：

1. 单条记录解析失败 → 记一条 warning，跳过该条，**不影响整个会话**；
2. 单个会话解析失败 → 在列表里仍然显示，标记为"解析异常"，可查看原始内容；
3. 无法归类的结构 → 落到 `UnknownPart`，原样保留 JSON，UI 用原始查看器渲染；
4. 所有归一化后的对象都带 `raw` 字段（或指向原始记录的定位信息），保证"归一化视图"和"原始视图"可以双向对照。

### 5.3 隐私

这些存储里包含 prompt 正文、源码片段、命令行参数、环境路径，甚至凭据。因此：只监听 `127.0.0.1`；不外发任何数据；导出功能提供可选脱敏；日志里不打印消息正文。
