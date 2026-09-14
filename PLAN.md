# Coding Agent 聊天记录查看器 — 实施计划

## 0. 目标与范围

做一个**本地运行**的聊天记录查看器，把 Cursor、Codex、opencode 三家 coding agent 散落在本机各处、格式各异的会话记录，统一成一套数据模型，用一个 Web 界面浏览、搜索、对比和导出。

**必须满足的约束**（来自需求）：

- 前后端分离：后端纯 HTTP API，前端独立构建，二者无模板耦合。
- 后端提供"本地能力"：读本地文件系统 / SQLite、监听文件变化、建索引、导出文件、调起本地命令（如 `cursor-agent --resume`）。这些是浏览器做不到的，因此必须放在后端。
- 前端用 Vite。
- 支持 Cursor、Codex、opencode。其中 **Cursor 实际是两个数据源**（IDE Composer 与 `cursor-agent` CLI，存储完全不通），所以一共 **4 个适配器**。

**范围内**：只读浏览、搜索、统计、导出。
**范围外（首版不做）**：编辑/删除原始记录、云端同步、多用户、把会话续写下去（只提供"复制恢复命令"）。

---

## 1. 技术选型

| 层 | 选型 | 理由 |
|---|---|---|
| 后端 | Python 3.12 + FastAPI + uvicorn | 项目约定用 Python；FastAPI 自带 OpenAPI，能直接生成前端 TS 类型 |
| 后端数据模型 | Pydantic v2 | 判别联合（discriminated union）原生支持，正好匹配 part 模型 |
| 索引/搜索 | 标准库 `sqlite3` + FTS5 | 零额外依赖，全文检索够用 |
| 包管理 | `uv` | 快，锁文件可复现（环境里没有，需在 M0 装上） |
| 前端 | Vite 7 + React 19 + TypeScript | 需求指定 Vite |
| 路由/数据 | TanStack Router + TanStack Query | 会话详情天然适合按 URL 深链 + 查询缓存 |
| 样式 | Tailwind v4 + shadcn/ui | 三栏布局和暗色模式成本最低 |
| 长列表 | `@tanstack/react-virtual` | 单会话上万条 part 必须虚拟化 |
| 渲染 | `react-markdown` + `remark-gfm` + `shiki` | 代码高亮质量 |
| Diff | `diff2html`（或自绘 unified diff） | 渲染 patch/snapshot part |
| 测试 | pytest + vitest + Playwright（少量 e2e） | — |

前后端类型同步：后端导出 OpenAPI → `openapi-typescript` 生成 `packages/web/src/api/schema.d.ts`，纳入 CI 校验，**禁止手写重复的 TS 接口**。

---

## 2. 仓库结构

```
.
├── PLAN.md
├── docs/
│   ├── storage-formats.md        # 已完成：四个数据源的落盘格式调研
│   └── api.md                    # 生成的 API 文档
├── packages/
│   ├── server/                   # Python 后端
│   │   ├── pyproject.toml
│   │   └── src/agent_chat_viewer/
│   │       ├── main.py           # FastAPI app / CLI 入口
│   │       ├── config.py         # 路径解析、用户配置
│   │       ├── models.py         # 统一数据模型（Pydantic）
│   │       ├── api/              # 路由
│   │       ├── adapters/
│   │       │   ├── base.py       # Provider 协议 + 注册表
│   │       │   ├── codex.py
│   │       │   ├── cursor_cli.py
│   │       │   ├── cursor_ide.py
│   │       │   └── opencode.py
│   │       ├── index/            # 缓存索引 + FTS5
│   │       ├── export/           # md / json / html 导出
│   │       └── util/
│   │           ├── sqlite_ro.py  # 安全只读快照
│   │           └── jsonl.py      # 容错 JSONL 流式读取
│   └── web/                      # Vite 前端
│       ├── vite.config.ts
│       └── src/{api,routes,components,features,lib}
├── fixtures/                     # 各 provider 的合成测试数据
├── scripts/
│   ├── probe_stores.py           # 探测本机真实存储，校验调研结论
│   └── make_fixtures.py          # 生成 fixtures
└── tests/
```

单仓双包，根目录放 `Makefile`/`justfile` 统一命令（`dev` / `test` / `lint` / `build`）。

---

## 3. 统一数据模型（整个项目的核心）

四家格式各不相同，但都能归约到「会话 → 消息 → part」三层。opencode 的 part 模型信息最全，**以它为原型**，其余适配器向它映射。

```python
# packages/server/src/agent_chat_viewer/models.py  (示意)

ProviderId = Literal["codex", "cursor-cli", "cursor-ide", "opencode"]

class SessionSummary(BaseModel):
    provider: ProviderId
    id: str                       # provider 内唯一
    uid: str                      # f"{provider}:{id}"，全局唯一，用于 URL
    title: str | None
    cwd: str | None               # 工作区绝对路径，Cursor CLI 可能为 None
    project: str | None           # cwd 的展示名
    created_at: datetime | None
    updated_at: datetime | None
    message_count: int
    model: str | None
    git_branch: str | None
    parent_uid: str | None        # 子 agent 会话指向父会话
    kind: Literal["main", "subagent"]
    tokens: TokenUsage | None
    cost: float | None
    source_path: str              # 原始文件/库路径，用于失效判断和"在 Finder 中显示"
    parse_status: Literal["ok", "partial", "error"]

class Message(BaseModel):
    id: str
    role: Literal["user", "assistant", "system", "tool"]
    created_at: datetime | None
    parts: list[Part]
    tokens: TokenUsage | None
    cost: float | None
    error: str | None

# Part 为判别联合，discriminator = "type"
TextPart        # text
ReasoningPart   # text，默认折叠
ToolPart        # name, input, output, status, error, started_at, ended_at, metadata
FilePart        # path, mime, size, url?（附件/图片）
PatchPart       # 文件 diff（unified diff 或结构化 hunks）
SnapshotPart    # 工作区快照引用（Cursor checkpoint / opencode snapshot）
StepPart        # step-start / step-finish，带用量与耗时
TodoPart        # 任务清单
SubtaskPart     # 指向子会话的 uid
CompactionPart  # 上下文压缩/摘要
UnknownPart     # 兜底：原样保留 JSON
```

三条硬规则：

1. **每个 Part / Message 都能回溯到原始记录**（保留 `raw` 或 `(file, line)` / `(db, key)` 定位），UI 提供"查看原始 JSON"。
2. **不认识的东西一律进 `UnknownPart`，绝不丢弃**。格式漂移时最坏也只是渲染成折叠的 JSON。
3. 归一化只做结构映射，**不做语义改写**（不重排、不合并、不补全），保证"看到的就是记录里的"。

---

## 4. 后端设计

### 4.1 适配器协议

```python
class Provider(Protocol):
    id: ClassVar[ProviderId]

    def detect(self) -> ProviderStatus:
        """返回是否检测到、根路径、版本线索、错误原因。"""

    def iter_sessions(self) -> Iterator[SessionSummary]:
        """只读头部/索引，不解析正文。必须快。"""

    def load_session(self, session_id: str) -> Session:
        """全量解析单个会话。"""

    def raw_records(self, session_id: str) -> Iterator[dict]:
        """原始记录流，供调试视图使用。"""
```

注册表按 id 分发；新增一家 agent 只需加一个文件 + 注册一行。

### 4.2 索引与缓存

全量扫描（尤其 Codex 成千上万个 JSONL）不能放在请求路径上。

- 缓存库：`~/.local/state/agent-chat-viewer/index.db`（遵循 XDG；macOS 用 `~/Library/Application Support/`）。
- 表：`sessions`（summary 全字段）、`messages_fts`（FTS5：会话 uid + 角色 + 纯文本，用于全文检索）、`sources`（`path, mtime, size, hash` 用于失效判断）。
- 启动时后台增量扫描，只重解析 `(mtime, size)` 变了的源；进度通过 SSE 推给前端，前端显示"正在索引 N/M"。
- `watchfiles` 监听各 provider 根目录，有变化就增量更新并通过 SSE 推 `session.updated`，实现"边跑 agent 边看记录"。

### 4.3 API

全部挂在 `/api` 下，返回 JSON。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/providers` | 各 provider 检测结果、根路径、会话数、错误 |
| GET | `/api/projects` | 按 cwd 聚合的项目列表（跨 provider） |
| GET | `/api/sessions` | 列表。参数：`provider[]`、`project`、`q`、`since`、`until`、`kind`、`sort`、`cursor`、`limit`（游标分页） |
| GET | `/api/sessions/{uid}` | 完整归一化会话；`?offset=&limit=` 支持超长会话分段拉取 |
| GET | `/api/sessions/{uid}/raw` | 原始记录（调试视图） |
| GET | `/api/search` | 跨会话全文检索，返回带高亮片段的命中列表 |
| GET | `/api/sessions/{uid}/export` | `format=md\|json\|html`，`redact=true` 可脱敏 |
| GET | `/api/stats` | 用量聚合：按天/模型/provider/工具的消息数、token、成本 |
| GET | `/api/events` | SSE：索引进度、会话新增/更新 |
| POST | `/api/actions/reveal` | 在系统文件管理器中定位原始文件（本地能力） |
| GET | `/api/sessions/{uid}/resume-command` | 返回可复制的恢复命令，**不代为执行** |
| GET | `/api/health` | 健康检查 |

约定：错误统一 `{"error": {"code", "message", "detail"}}`；列表响应带 `{"items", "next_cursor", "total_estimate"}`。

### 4.4 安全

- 默认只绑 `127.0.0.1`，随机端口 + 启动时打印带一次性 token 的 URL；跨机访问需显式 `--host`。
- 对源存储**只读**：统一走 `util/sqlite_ro.py` 的快照复制方案（见 `docs/storage-formats.md` 5.1），永不写回。
- 文件访问路径限制在已检测到的 provider 根目录 + 用户显式配置的目录内，防目录穿越。
- CORS 只允许 Vite dev server origin；生产模式下前端产物由后端同源托管，不需要 CORS。
- 无遥测、无外发；日志不打印消息正文。

---

## 5. 前端设计

### 5.1 布局

三栏：

- **左**：provider / 项目 / 时间的过滤树 + 会话列表（虚拟滚动，显示标题、时间、provider 徽标、消息数、模型、子会话折叠）。
- **中**：转录主体。按消息渲染，工具调用默认折叠为一行摘要（工具名 + 参数摘要 + 耗时 + 状态色），点击展开完整 input/output；reasoning 默认折叠；patch 渲染成 diff；图片/附件内联。
- **右**（可收起）：会话元信息（cwd、git 分支、模型、token、成本、原始文件路径）、当前选中 part 的原始 JSON、会话内跳转目录（用户消息作为锚点的时间线）。

### 5.2 关键交互

- URL 即状态：`/s/:provider/:id?msg=:messageId`，可深链、可分享、刷新不丢。
- 会话内搜索（`/`）+ 全局搜索（`Cmd/Ctrl+K`），命中高亮 + 上下条跳转。
- 过滤：角色、是否含工具调用、是否报错、时间范围。
- 键盘导航：`j/k` 切消息，`J/K` 切会话，`o` 展开全部工具调用，`r` 复制恢复命令。
- 导出：单会话 Markdown / JSON / 自包含 HTML；选中片段复制为 Markdown。
- 主题：跟随系统的明暗模式。

### 5.3 开发/生产模式

- 开发：`vite dev` 起在 5173，`server.proxy` 把 `/api` 代到后端 8787。
- 生产：`vite build` 产物拷进 `packages/server/src/agent_chat_viewer/static/`，FastAPI 用 `StaticFiles` 同源托管，一条命令即可启动整个应用。

---

## 6. 分阶段实施

每个阶段结束都要求：可运行、有测试、`make check` 通过。不做"全部适配器一起写"——**先用 Codex 这个最规整、有官方 schema 的格式把整条链路打通**，模型设计在真实数据上验证过之后，再写难的。

### M0 · 地基与格式验证

- `uv` 初始化后端包，Vite 初始化前端包，`justfile` 串起 `dev/test/lint/build`。
- 写 `scripts/probe_stores.py`：扫描本机四个数据源，输出"检测到什么、目录结构、样本记录字段直方图"，用来**逐条验证/修正 `docs/storage-formats.md`**。这是后续所有工作的事实依据。
- FastAPI 骨架 + `/api/health` + `/api/providers`（只做 detect）；前端出一个能显示 provider 检测结果的页面。
- 打通 OpenAPI → TS 类型生成。

**完成标准**：`just dev` 起来，页面上正确显示本机装了哪几个 agent、各自根路径在哪。

### M1 · Codex 适配器 + 端到端最小可用

- `models.py` 全部 Part 类型定稿。
- Codex 适配器：目录遍历、头部快速扫描、`response_item` 为主 / `event_msg` 补充的归一化、子 agent 关联、压缩文件兼容。
- `/api/sessions`、`/api/sessions/{uid}`。
- 前端三栏骨架：会话列表 + 转录渲染（text / reasoning / tool / unknown 四种 part 先跑通）。

**完成标准**：能从列表点开任意一个真实 Codex 会话，内容与 `codex --resume` 里看到的一致。

### M2 · opencode 适配器

- 新旧两种存储（`opencode.db` 与 JSON 文件树）自动判别，共用同一套归一化。
- 补全 part 类型渲染：`patch` 的 diff 视图、`step-finish` 的用量、`file` 附件、`subtask` 跳转子会话。
- 项目维度聚合 `/api/projects`。

**完成标准**：opencode 会话的工具调用、diff、子任务在 UI 上都能正确展开。

### M3 · Cursor IDE 适配器

- 只读快照工具 `sqlite_ro.py`（这是 M3/M4 共同的前置）。
- `globalStorage` 的 `composerData:` / `bubbleId:` 解析，`fullConversationHeadersOnly` 定序。
- 扫 `workspaceStorage/*` 建 `composerId → cwd` 映射；关联不上的会话照样展示。
- `toolFormerData` → `ToolPart`，`thinking` → `ReasoningPart`，`checkpointId` → `SnapshotPart`。
- 兼容老版 `_v` 与 `workbench.panel.aichat.view.aichat.chatdata`。

**完成标准**：Cursor 正在运行时也能安全读取，不影响 IDE，不损坏库。

### M4 · Cursor CLI 适配器

- `~/.cursor/chats/<md5>/<uuid>/` 遍历，`meta.json` + `meta` 表（hex JSON）解出会话元信息。
- JSON blob 归一化；**第一版接受近似排序并在 UI 明示**，随后解 protobuf turn graph 得到精确顺序。
- 工作区 md5 反向索引 + 手动绑定入口。
- `acp-sessions` 一并支持。

**完成标准**：四个 provider 在同一个列表里并排出现，可按项目跨 provider 聚合。

### M5 · 索引与搜索

- `index.db` + FTS5，启动后台增量扫描，SSE 推进度。
- `/api/search` 跨会话检索 + 片段高亮；全局 `Cmd+K`。
- `watchfiles` 热更新。

**完成标准**：万级会话下，列表首屏 < 300ms，全文检索 < 200ms。

### M6 · 导出、统计与打磨

- Markdown / JSON / 自包含 HTML 导出，可选脱敏。
- `/api/stats` + 统计页（按天/模型/工具的用量与成本）。
- 键盘导航、空状态、错误态、"解析异常"会话的原始查看器、暗色模式。

### M7 · 打包分发

- 前端产物内嵌进后端包，`agent-chat-viewer` 命令一键启动并打开浏览器。
- 发到 PyPI，支持 `uvx agent-chat-viewer` 零安装运行。
- README：截图、支持矩阵、隐私说明。

---

## 7. 测试策略

- **Fixtures 优先**：`scripts/make_fixtures.py` 为每个 provider 生成**合成**存储（造 JSONL、造 SQLite），覆盖正常、缺字段、脏数据、超大、旧版本形态。真实数据含隐私，绝不入库。
- **适配器黄金测试**：fixture → 归一化 JSON 快照比对。格式漂移时快照 diff 会第一时间暴露。
- **容错测试**：故意塞入截断行、非法 UTF-8、未知 `type`、空 blob，断言"降级但不崩"，并且产出对应 warning。
- **API 测试**：`httpx.ASGITransport` + `TestClient`，覆盖分页、过滤、错误码。
- **并发安全测试**：一边写 fixture SQLite（模拟 IDE 运行）一边读，断言读取不报错、不写回原文件。
- **前端**：vitest 覆盖 part 渲染组件与 markdown/diff 边界；Playwright 覆盖"列表 → 打开会话 → 搜索 → 导出"主链路。
- **CI**：lint（ruff + mypy + eslint + tsc）、测试、OpenAPI 与 TS 类型一致性校验。

---

## 8. 主要风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| Cursor / opencode 格式无文档且版本churn | 适配器随时解析失败 | 宽容解析三原则（见 3 节）；`UnknownPart` 兜底；黄金快照测试尽早发现漂移；UI 明示"解析异常"而不是静默丢数据 |
| Cursor CLI 的顺序信息在 protobuf 里 | 消息顺序可能不准 | M4 第一版用时间戳近似并在 UI 标注，再迭代解 turn graph；不把不确定当确定 |
| Cursor CLI 工作区路径是 md5，不可逆 | 会话无法归属项目 | 候选路径反向索引 + 用户手动绑定 + 允许"未知工作区"分组 |
| 应用运行时 SQLite 加锁 / WAL | 读到撕裂数据甚至损坏源库 | 统一快照复制只读方案，带 `(path, mtime, size)` 缓存；写路径在代码层面完全不存在 |
| 会话体量大（上万 part / 单文件数十 MB） | 前端卡死、内存爆 | 后端分段返回 + 前端虚拟化；列表页只读头部；超大 part 截断显示并提供"加载全部" |
| 数据含隐私和凭据 | 泄露风险 | 只绑 127.0.0.1 + 本地 token；无外发；导出可脱敏；日志不含正文 |
| 四个适配器工作量不均 | 进度失衡 | 分阶段按"从规整到混乱"排序，每阶段独立可用，随时可停在一个有价值的状态 |

---

## 9. 首版验收清单

- [ ] 一条命令启动，自动检测本机已安装的 agent 并列出会话。
- [ ] Cursor IDE、Cursor CLI、Codex、opencode 四个来源的会话出现在同一列表，可按 provider / 项目 / 时间过滤。
- [ ] 打开任一会话，正确渲染用户消息、助手回复、推理、工具调用（含入参出参）、文件 diff。
- [ ] 全文检索能跨会话跨 provider 命中并高亮。
- [ ] 任一会话可导出为 Markdown。
- [ ] 目标 agent 正在运行时读取不报错、不影响其工作、不修改任何源文件。
- [ ] 遇到无法解析的记录时，UI 降级展示原始 JSON 而非整页失败。
