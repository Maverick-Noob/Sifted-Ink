<p align="center">
  <pre style="font-size:10px;line-height:1.1;color:#a371f7;">
   ███████╗ ██╗ ███████╗ ████████╗ ███████╗ ██████╗        ██╗ ███╗   ██╗ ██╗  ██╗
   ██╔════╝ ██║ ██╔════╝ ╚══██╔══╝ ██╔════╝ ██╔══██╗       ██║ ████╗  ██║ ██║ ██╔╝
   ███████╗ ██║ █████╗      ██║    █████╗   ██║  ██║       ██║ ██╔██╗ ██║ █████╔╝
   ╚════██║ ██║ ██╔══╝      ██║    ██╔══╝   ██║  ██║       ██║ ██║╚██╗██║ ██╔═██╗
   ███████║ ██║ ██║         ██║    ███████╗ ██████╔╝       ██║ ██║ ╚████║ ██║  ██╗
   ╚══════╝ ╚═╝ ╚═╝         ╚═╝    ╚══════╝ ╚═════╝        ╚═╝ ╚═╝  ╚═══╝ ╚═╝  ╚═╝

          ███████╗ ██╗ ███████╗ ████████╗ ███████╗ ██████╗
          ██╔════╝ ██║ ██╔════╝ ╚══██╔══╝ ██╔════╝ ██╔══██╗
          ███████╗ ██║ █████╗      ██║    █████╗   ██║  ██║
          ╚════██║ ██║ ██╔══╝      ██║    ██╔══╝   ██║  ██║
          ███████║ ██║ ██║         ██║    ███████╗ ██████╔╝
          ╚══════╝ ╚═╝ ╚═╝         ╚═╝    ╚══════╝ ╚═════╝
  </pre>
</p>

<h1 align="center">选墨集</h1>
<h3 align="center">Sifted-Ink</h3>
<p align="center"><em>千墨选一，落纸成书 — Selected ink, eternal story.</em></p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/license-Apache%202.0-blue.svg" alt="Apache 2.0">
  <img src="https://img.shields.io/badge/language-中文-red.svg" alt="中文">
</p>

---

## 📑 目录 | Table of Contents

- [项目简介](#-项目简介--about)
- [核心特性](#-核心特性--features)
- [快速开始](#-快速开始--quick-start)
- [配置说明](#-配置说明--configuration)
- [安全约束](#-安全约束--safety-constraints)
- [Web 界面](#-web-界面预览--web-ui)
- [更新日志](#-更新日志--changelog)
- [贡献指南](#-贡献指南--contributing)
- [使用指南](USER_GUIDE.md)
- [许可证](#-许可证--license)

---

## 📖 项目简介 | About

**选墨集（Sifted-Ink）** 是一个由多 AI Agent 协同驱动的小说生成引擎。

它不像传统 AI 写作工具那样一次性输出文本，而是模拟一个 **"编剧室"**：多名 AI Agent 分别扮演**叙事导演**、**主角**、**NPC** 和**评估师**，对同一个故事前提进行多版本预演。预演完成后，评估师从**戏剧张力**、**角色成长**、**逻辑一致性**、**结局匹配度**四个维度评选出最佳版本，最终生成一部完整的小说。

> **默认只跑 1 个版本。** 批量预演是平台治理的判定维度之一（是否批量生成 / 是否严重缺乏原创性），
> 费用也会随版本数线性增长。Web 界面会在提交前给出消耗预估与提示——先跑 1 版确认方向，再决定要不要开多版。

> *"千墨选一，落纸成书 — Selected ink, eternal story."*

---

## ✨ 核心特性 | Features

| 特性 | 说明                                                                                                         |
|---|------------------------------------------------------------------------------------------------------------|
| 🎭 **多 Agent 架构** | 叙事导演、主角、NPC 池、评估师——各有独立角色与系统提示词 |
| ⚡ **并行预演** | 基于 `asyncio`，**默认 1 个版本**；多版本需显式开启（提交前有消耗预估与合规提示） |
| 📋 **多大纲择优** | 生成不同角度大纲，评估后选用最优 |
| 🎯 **节奏控制** | 三幕剧结构 + 动态压力 + 动态每章字数控制 |
| 🧠 **RAG 故事记忆** | 每章提取结构化关键信息，检索增强生成确保章节连贯 |
| 👥 **主角团模式** | 聚光灯轮换 / 团队 Agent / 全并行，动态超时保护 |
| 🎭 **自动结局** | 不输入结局时 AI 自动设计 |
| 📊 **四维评估** | 戏剧张力 / 角色成长 / 逻辑一致性 / 结局匹配度打分 |
| 🖋️ **叙事手法** | 15 套可执行风格规格（人称 / 句长 / 对话率 / 禁用词 / 样例）+ 自定义 |
| ✨ **智能起名** | 7 种命名风格 + 规则模板 + LLM 择优，章节标题也适用 |
| 🌐 **Web 界面** | FastAPI 暗色主题，SSE 实时进度 + 控制台日志同步 |
| 🔌 **全平台 API** | 13 家主流大模型提供商 |
| 👤 **用户定义 NPC** | 预定义角色（姓名/关系/背景/能力/登场章），AI 可补充 |
| 📥 **多格式导出** | MD / TXT / EPUB / PDF / MOBI / AZW3 + 可选前附文（目录/引言/楔子/人物表） |
| 📝 **日志记录** | 系统日志 + 生成参数文件自动保存 |

---

## 🚀 快速开始 | Quick Start

### 安装

```bash
git clone https://github.com/Maverick-Noob/Sifted-Ink.git
cd Sifted-Ink

# 基础安装（核心 + Web 界面）
pip install -e .

# 按需追加：模型厂商 SDK / 导出格式 / 开发工具
pip install -e ".[providers-anthropic]"    # 或 providers-openai / providers-google
pip install -e ".[all-providers]"
pip install -e ".[export]"                 # EPUB / PDF
pip install -e ".[dev]"                    # pytest / ruff / mypy

# MOBI / AZW3 额外需要（可选）
# 安装 Calibre: https://calibre-ebook.com/
```

> 安装后 `sifted-ink --web` 与 `python -m novel_preactor --web` 都可用。
> 若不想安装，也可 `pip install -r requirements.txt` 后在**仓库的上一级目录**
> 执行 `python -m novel_preactor --web`（本仓库的根目录即 Python 包目录）。

### 设置 API Key

```bash
# 通用方式（所有提供商都会读取）
export SIFTED_INK_API_KEY="your-api-key"

# 或使用各提供商的专属环境变量：
export ANTHROPIC_API_KEY="sk-ant-..."    # Anthropic
export OPENAI_API_KEY="sk-..."           # OpenAI
export DEEPSEEK_API_KEY="sk-..."         # DeepSeek
export MOONSHOT_API_KEY="sk-..."         # Moonshot / Kimi
export ZHIPU_API_KEY="..."               # 智谱 GLM
export DASHSCOPE_API_KEY="sk-..."        # 阿里通义千问
export GOOGLE_API_KEY="..."              # Google Gemini
# ... 等等
```

### 启动 Web 界面（推荐）

```bash
python -m novel_preactor --web
# 然后访问 http://localhost:8000
```

### 命令行方式

```bash
# YAML 配置文件
python -m novel_preactor --config story_config.yaml

# 交互式配置
python -m novel_preactor --interactive

# 完整参数
python -m novel_preactor --config story.yaml --budget 200000 --output ./output
```
---

## ⚙️ 配置说明 | Configuration

```yaml
# ── 故事设定 ──
protagonist_name: "林远"             # 主角姓名
protagonist_traits: |                # 主角性格、动机、能力
  勇敢但冲动，20岁，渴望为家族复仇。
  擅长剑术，具备初级火系魔法。
world_setting: |                     # 世界背景（时代、魔法/科技水平）
  架空奇幻世界"苍澜大陆"，中世纪，四元素魔法体系。
story_start: |                       # 故事开头场景
  深夜，林远在家族废墟发现了父亲留下的密信…
story_end: |                         # 目标结局（留空则 AI 自动设计）
  林远找到炎之心，击败幕后黑手，成为火焰守护者。

# ── 叙事手法（可选）──
# narrative_technique: "fast-climax"  # 留空=不指定；可选值见 narrative_techniques.json
# naming_style: "诗意意境型"          # 书名风格（留空则自动选择，7 种可选）

# ── 用户定义 NPC（可选）──
# user_npcs:
#   - name: "铁山"
#     role: "friend"
#     personality: "沉默忠诚的佣兵"
#     relevance: "high"
#     intro_chapter: 3

# ── 生成参数 ──
target_word_count: 8000              # 目标字数
num_versions: 1                      # 并行预演版本数（1-500，默认 1）
max_npcs: 30                         # NPC 数量上限（程序自动清理不相关 NPC）
max_chapters: 30                     # 每版本章节上限
total_token_budget: 0                # 总 Token 预算（0 = 不限制）

# ── API 设置 ──
model: "claude-sonnet-4-6"           # 模型名称（程序自动匹配提供商）
api_provider: "anthropic"            # 提供商: anthropic / openai / google / deepseek / moonshot
                                     #         zhipu / qwen / baichuan / minimax / grok / mistral / cohere / custom
# api_base_url: ""                   # 自定义 API 地址（custom 或代理时使用）
```

---

## 🛡️ 安全约束 | Safety Constraints

| 约束项 | 默认值 | 说明 |
|---|---|---|
| 章节上限 | 30 章 / 版本 | 超过后强制终止，标记"未完成" |
| NPC 上限 | 30 人 | 导演达到上限后不可新增 NPC |
| NPC 动态清理 | 自动 | 3 章未活跃或低相关性 NPC 自动退场 |
| 单次调用 Token 限制 | 4,000 | 每次 API 调用最多消耗 |
| 总 Token 预算 | 不限制 | 可手动设置上限，0 = 不限制 |
| 版本超时 | 30 分钟 | 单个预演版本的墙钟时间上限 |
| 重复动作检测 | 相似度 > 90% | 连续 3 次相似动作 → 强制切换场景 |
| 用户中断 (Ctrl+C) | 优雅保存 | 捕获信号，保存已完成版本后退出 |
| 内容审核 | 敏感词过滤 | 每章自动检测，命中标记警告（不阻断） |
| 叙事手法 | 可执行规格 | 不含任何作家姓名；每套手法给出人称/句长/对话率/禁用词/自撰样例 |

---

## 🖥️ Web 界面预览 | Web UI

启动后访问 `http://localhost:8000`：

<img width="2559" height="1316" alt="屏幕截图 2026-06-11 190544" src="https://github.com/user-attachments/assets/4f008e81-d3d6-457c-b79a-ec8dc69f30de" />
<img width="2538" height="1300" alt="屏幕截图 2026-06-11 191004" src="https://github.com/user-attachments/assets/a465e02d-df96-4bb5-b09b-1918952825d9" />

| 页面 | 路径 | 功能 |
|---|---|---|
| 配置页 | `/` | 卡片式表单：主角 / 世界 / 故事 / **指定 NPC** / 叙事手法 / 前附文 / 书名风格 / 主角团模式 / NPC策略 / 质量模式 / API 设置 + **运行前消耗预估** |
| 进度页 | `/progress/{id}` | SSE 实时推送：进度条、版本卡片、**控制台日志同步**、取消按钮 |
| 结果页 | `/result/{id}` | **书名展示 + 情节摘要** + 统计面板 + 版本对比表 + Tab 切换 + 下载 |

### 叙事手法选择

Web UI 提供**叙事手法**卡片，内置 **15 套**可执行风格规格，按类别分组。不选则使用默认叙事。

每套手法给出的不是"像谁"，而是**可执行的写作约束**——这正是本工具替代"模仿特定作家"的原因：

| 字段 | 含义 |
|------|------|
| 叙事人称 / 视角距离 | 第三人称限知 · 近 / 中 / 远 |
| 句长 p50 / p90 | 中位句长与长句上限（字） |
| 对话 / 描写 / 心理 占比 | 三者的比例预算 |
| 用词 · 意象取材 · 语体 · 节奏 | 具体的写作取向 |
| 禁用表达 | 命中即视为不合格（如"眼中闪过一丝""嘴角勾起"） |
| 参考样例 | 150 字自撰样例——**参数给方向，样例给手感** |

也可以在界面里添加**你自己的**手法（用自己的话描述人称、句长、节奏、忌讳）。

| 类别 | 手法 |
|------|------|
| 现实主义 | 冷叙述·白描 |
| 网文 | 快节奏·爽点密集 |
| 抒情 | 温柔·抒情散文 |
| 古典 | 古典·章回气韵 |
| 对话 | 对话驱动·机锋 |
| 心理 | 内心独白·心理流 |
| 史诗 | 史诗·宏阔场面 |
| 悬疑 / 权谋 / 群像 / 都市 / 喜剧 / 暗黑 / 成长 | 悬疑·信息差、权谋·信息博弈、群像速写、都市·口语写实、轻喜剧·网感、暗黑·冷硬、成长·少年气、日常暗流·都市悬疑 |

不选则使用默认叙事。

> **为什么不再提供"模仿某位作家"**：
> ① 著作权保护**具体表达**，不保护创作方法——手法是方法，作品是表达；
> ② 旧库 183 位作家只有 12 位进入公有领域，其余 171 位（93.4%）在世或去世不足 50 年，
> 把"模仿在世作家"做成卖点，等于把最大的法律风险挂在最显眼的位置；
> ③ 平台侧已把「AI 粗制滥造」「是否严重缺乏原创性」列为治理维度，模仿特定在世网文作家
> 在变现体裁上的风险最高。
> 详见 [使用条款](TERMS.md)。

### 运行前消耗预估

配置页在提交前会显示本次运行的**预计章节数、模型调用次数、token 总量、墙钟时长与费用**，
并在版本数 > 1、目标字数超出单次运行能力上限时给出提示。费用按公开挂牌价估算，
以服务商账单为准。

### 故事起名

完结后自动调用 AI 进行：**情节摘要**（150-250 字）+ **10 个候选书名** → 择优。输出文件以 `{书名}_{时间戳}` 格式命名。

### 多格式下载

结果页提供一键下载，格式由后端按需生成并缓存：

| 格式 | 说明 | 依赖 |
|------|------|------|
| **Markdown** (.md) | 原生格式，含标题和元数据 | — |
| **纯文本** (.txt) | 去除标记，章节装饰分隔线 | — |
| **EPUB** (.epub) | 电子书标准格式，CSS 排版 | `ebooklib` |
| **PDF** (.pdf) | A5 书页尺寸，中文排版 | `fpdf2` + 系统中文字体 |

### API 配置

Web UI 的 API 设置简化为三字段：**模型供应商** 下拉选择 → 模型名自动填入 → 填写 API Key。Base URL 由后端根据供应商自动解析，无需手动填写。

---

## 📋 更新日志 | Changelog

### v1.0 (2026-06)

- 🎭 多 Agent 架构：叙事导演、主角、NPC 池、评估师
- ⚡ 并行预演：1~500 版本 asyncio 协程并行
- 📋 多大纲择优：3 角度大纲生成 + 评估 + 选择
- 🎯 三幕剧节奏控制 + 动态压力系统
- 🎭 AI 自动结局生成
- 🖋️ 15 套叙事手法规格（可执行约束 + 禁用词 + 自撰样例，支持自定义）
- ✨ 智能起名：7 种命名风格 + 规则模板 + LLM 评分
- 👥 主角团模式：聚光灯轮换 / 团队 Agent / 全并行（3 种）
- 🧹 NPC 策略：异步并行批处理 / 场景过滤 / 叙事代劳
- ⚖️ 质量模式：平衡 / 质量优先（动态超时 + NPC 数量）
- 📖 前附文：目录 / 引言 / 楔子 / 人物表（可选）
- 👤 用户定义 NPC：预定义角色属性，AI 可补充更多
- 🧠 RAG 故事记忆：每章提取结构化信息，检索增强确保章节连贯
- 📥 多格式导出：MD / TXT / EPUB / PDF / MOBI / AZW3
- 🌐 FastAPI 暗色 Web UI + SSE 实时推送
- 🔌 13 家主流大模型 API 支持
- 📝 系统日志自动保存
- 🛡️ 7 项硬约束安全机制

---

## 🤝 贡献指南 | Contributing

欢迎提交 Issue 和 Pull Request！

### 报告 Bug
请在 [Issues](../../issues) 中描述：
- 运行环境（OS / Python 版本）
- 复现步骤
- 期望行为 vs 实际行为
- 相关日志（`logs/` 目录下的文件）

### 添加叙事手法
1. 编辑 `narrative_techniques.json`，按现有格式添加新条目
2. 或通过 Web UI 的「叙事手法 → 添加我自己的手法」提交（保存在 `user_techniques.json`，不入库）
3. 提交 PR 时请确保 JSON 格式有效

> ⚠️ 新增条目**不得包含真实作家姓名或作品名**。手法是方法，著作权不保护方法，只保护具体表达。

### 添加 API 提供商
1. 在 `agents.py` 的 `PROVIDER_REGISTRY` 中添加新条目
2. 更新 `webui/templates/index.html` 的下拉列表
3. 如使用非 OpenAI 兼容 SDK，需在 `LLMClient` 中添加新的 `_call_*` 方法

### 开发环境
```bash
git clone https://github.com/Maverick-Noob/Sifted-Ink.git
cd Sifted-Ink
pip install -e ".[dev]"
export SIFTED_INK_API_KEY="your-key"
python -m novel_preactor --web
pytest                     # 24 个测试，不需要 API Key
```

---

## 📜 许可证 | License

Apache License 2.0 — 详见 [LICENSE](LICENSE) 文件。

---

<p align="center">
  <sub>Made with ❤️ by Maverick-Noob / 布河狸 · 千墨选一，落纸成书</sub>
</p>
