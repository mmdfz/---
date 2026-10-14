# Research Assistant 科研论证辅助插件

AGH 内置并默认启用的后端插件，实现 [V1 设计](../../../../design/research-assistant-v1.zh-CN.md)中的核心链路：

1. 先在你配置的本地论文文件夹里检索（BM25，英文）；
2. 本地材料不足时，由大模型调用 Athenaeum MCP（`athenaeum_search` → `athenaeum_find_pdf`）找候选，再用本插件的受控下载把开放获取 PDF 存进论文文件夹的 `downloads/` 并统一索引；
3. 大模型逐条提出“问题—原文摘录—原始回答”，插件校验摘录确实逐字出现在原文中并收入证据池；
4. 一轮摘录收齐后，`research_judge` 把所有已核验摘录放进同一次 Jev 请求，由 Jev 对这一组证据给出一个关系；置信度 ≥ 阈值（默认 0.9）且关系为 supports / contradicts 时可以 `answered`，关系为 conditional 时记为 `conflict`；
5. 最终回答只引用证据池中的记录，带文件、页码、段落/章节和原文摘录。

大模型就是你在 AGH Web 中为会话配置的模型，执行循环仍是 AGH 内置的 Core loop。工具与流程只在“文献研究”模式下出现：该模式就是 `research`（Windows 上为 `research-windows`）预设，它把工作流写进系统提示词（`packages/code/prompts/research-workflow.md`）并放开 `research_*` 工具；Harness 模式的 `standard` 预设通过 `tools.hidden: [research_*]` 隐藏这些工具。在 Web 侧栏底部切换模式，见 [Web 工作台指南](../../../../docs/guide/web.zh-CN.md#文献研究模式)。

## 一次性准备（Windows PowerShell，在仓库根目录）

### 1. 解析引擎

插件复用 Document Reader 的 PDFium / Tesseract（英文 OCR）/ Word 解析引擎。`pnpm --filter @agnes/cli build:local` 会把它打包进构建产物中的插件副本；开发用的 `web-local` 入口会在源码目录生成 `src/runtime/`（已在 `.gitignore` 中）。

### 2. 填写配置文件

复制仓库根目录的 `research-assistant.config.example.json` 到你的用户目录，改名为 `agnes-research.config.json`：

```powershell
Copy-Item research-assistant.config.example.json "$HOME\agnes-research.config.json"
notepad "$HOME\agnes-research.config.json"
```

| 字段 | 说明 |
| --- | --- |
| `libraryDir` | 可选。默认是框架根目录（运行 AGH 的 `agnes-harness` 源码目录）下的 `paper/`，不存在时自动创建；在框架目录外运行时默认 `~/agnes-paper`。填写时须为已存在的绝对路径（如 `D:/papers`）。插件只读写这个文件夹：索引和证据保存在其中的 `.research/`，下载的论文放在 `downloads/`。 |
| `jev.api` | 接口协议，默认 `chat`（OpenAI 兼容，请求 `{baseUrl}/chat/completions`）；`decisions` 为 TypeSafe Decisions API（请求 `{baseUrl}/decisions`，以一道 `choice` 题判定关系，置信度取所选项概率与 `confidence` 中较低者）。 |
| `jev.baseUrl` | Jev 地址，填到 `/v1` 为止，如 defapi 的 Decisions API 为 `https://api.defapi.org/api/v1`。 |
| `jev.apiKey` | Jev 的 API Key（以 `Authorization: Bearer` 发送；无需鉴权可留空）。 |
| `jev.model` | Jev 模型名。 |
| `jev.threshold` | 通过阈值，0–1，默认 0.9。 |

配置在每次工具调用时重新读取，改完无需重装插件。若想放在别处，启动 AGH 前设置环境变量 `AGNES_RESEARCH_CONFIG` 指向该文件。配置含密钥，不要提交到仓库。

### 3. 插件已内置

`@agnes/research-assistant` 与 Document Reader 一样随应用发布，首次启动时离线安装、信任并启用；本版本之前创建的 profile 会在下次启动时补装一次，你之后禁用或移除的选择会被保留。已安装插件使用固定快照：修改插件代码并重新构建后，在 Web“设置 → 插件管理”中对该包选择“从新来源更新”，来源填写 `file:./bundled-plugins/research-assistant`。

### 4. 接入 Athenaeum MCP（本地不足时的回退）

```powershell
cd athenaeum-mcp-main
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
cd ..
$exe = (Resolve-Path athenaeum-mcp-main\.venv\Scripts\athenaeum-mcp.exe).Path
node packages/cli/dist/local/agnes.mjs mcp add athenaeum --name athenaeum --stdio $exe
```

若部署策略不允许该可执行文件，`mcp add` 会给出原因；也可以在会话中对 AGH 说“帮我接入这个 MCP”，并提供上面的可执行文件路径。

之后在 Web “设置 → MCP” 审核并启用 `athenaeum`，确认工具目录中出现 `athenaeum_search`、`athenaeum_find_pdf`。可选：在 `athenaeum-mcp-main\.env` 中填写 `ATHENAEUM_EMAIL` 以进入各数据源的 polite pool。MCP 未接入或不可用时，本地论文分析仍可独立运行。

## 使用

把论文（PDF / DOCX / DOC / TXT / MD）放进框架根目录的 `paper/`（或你配置的 `libraryDir`），在侧栏底部切换到“文献研究”，新建会话后直接提问：

> 睡眠不足是否会损害成年人的工作记忆？请给出证据和页码。

右侧面板会随工具调用实时展示问题解析、本地检索、外部检索、全文获取、原文阅读、证据池与 Jev 评估各阶段。

大模型会依次调用：`research_start` → `research_library_import`（大文件夹会分多次完成） → `research_search` →（不足时 Athenaeum + `research_download`）→ `research_add_evidence`（只核验并保存）→ `research_judge`（整轮摘录一次交给 Jev）→ `research_finish`，最后给出带引用的结论。

## 工具一览

| 工具 | 作用 |
| --- | --- |
| `research_start` | 创建/恢复研究 run，拆分待核验的 claim |
| `research_library_import` | 扫描论文文件夹，按文件签名识别类型，内容哈希去重，逐页解析与 OCR；可分多次续传 |
| `research_library_list` | 查看文档清单、状态、警告、错误与不支持的文件 |
| `research_search` | BM25 检索，返回片段的文件/页码/段落/章节/覆盖率与 `localSufficient` |
| `research_read` | 按 chunkId 读取片段及相邻段落 |
| `research_add_evidence` | 写入证据池：校验摘录逐字存在；不调用 Jev |
| `research_judge` | 把本问题全部已核验摘录放进一次 Jev 请求，返回这一组的关系、置信度与 passed；新增摘录后需再调用一次 |
| `research_download` | 受控下载开放获取 PDF 到 `downloads/` 并索引 |
| `research_log` | 记录 MCP 检索、候选选择、全文检查、无法获取等步骤 |
| `research_history` | 本对话历史问题的论文与已核验证据，供新问题复用 |
| `research_status` / `research_finish` | 查看 run；以 answered / insufficient / conflict / acquisition_unavailable 等结局结束并返回证据表 |

## 行为边界

- **路径**：模型只能传 chunkId 或论文集内文件名；扫描不跟随符号链接/目录连接，不进入隐藏目录，解析后的真实路径必须仍在 `libraryDir` 内。
- **类型识别**：以文件签名为准；扩展名与内容不符、XLSX/PPTX/图片等显示为 `unsupported` 并给出原因。单个文件解析失败或某页超时只影响该文件/该页。
- **OCR**：没有文字层的页面用离线英文 OCR；来自 OCR 页面的证据标为 `ocr_uncertain`，无文字页面记为警告，文档状态为 `partial`。
- **摘录校验**：忽略空格、换行、断字和标点后，摘录必须逐字出现在该片段（或同一文档其他片段）中，否则记为 `location_failed`，不交给 Jev，也不能作为确定性引用。
- **检索上限**：本地已有的论文，同一问题里 `research_read` 最多读 3 次，第 4 次拒绝（`RESEARCH_PAPER_REVIEW_LIMIT`），应以 `insufficient` 结束并说明无法从该论文回答。外部检索下载的论文每个问题最多 5 篇、从这些论文写入的证据最多 10 条，超出拒绝（`RESEARCH_EXTERNAL_LIMIT`），应以 `failed` 结束。
- **同一对话多个问题**：每个新问题各自 `research_start`，右侧面板从头展示新问题的流程，历史问题连同其论文与证据收在面板下方“历史问题”中。run 记录所属对话；新问题开始时返回本对话的 `earlierQuestions`，`research_history` 给出历史证据（`ref`、chunkId、原文摘录）。复用时以 `reusedFrom=ref` 调用 `research_add_evidence`，摘录重新核验，再由本问题的 `research_judge` 连同其他摘录一起评估；只能复用同一对话的证据，不同对话互不可见。
- **回答必须基于论文**：文献研究模式下，模型须先检索并阅读本地或外部获取的论文再作答，自身知识只能作为标注出处的补充背景，不能决定结论。`research_finish` 在 `answered` 时要求最新一次 `research_judge` 覆盖全部已核验摘录且通过、关系不是 conditional；在 `conflict` 时要求同一次评估通过且关系为 conditional。否则拒绝结束（`RESEARCH_EVIDENCE_REQUIRED`），run 保持未结束，可继续检索或以 `insufficient` 结束。
- **Jev 失败即不通过**：网络错误、429/5xx、输出不是规定 JSON 时最多尝试 3 次；仍失败记为 `judge_unavailable`，`passed=false`。401/403 等不重试。评估对象是整轮摘录，不是单条。
- **下载**：只接受公网 https；每一跳重定向都会重新校验，拒绝内网/回环/链路本地地址；最多 5 次重定向、单文件 100 MiB；内容必须是 PDF。401/402/403 或返回 HTML 页面视为付费墙/登录/反爬，直接报告，不绕过。不覆盖已有文件，记录 DOI、URL、提供方与下载时间。单次工具调用仍受 AGH 的工具超时约束，所以长导入会分多次完成。

## 测试

```powershell
pnpm exec vitest run packages/package-manager/test/research-assistant.test.ts --maxWorkers=1
```

单元测试覆盖分段与检索、配置校验、Jev 解析/重试/失败关闭、下载拒绝路径与落盘、本地导入到证据判定的完整链路（使用文本文件和模拟 Jev，不需要解析引擎或网络）。
