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

它不像传统 AI 写作工具那样一次性输出文本，而是模拟一个 **"编剧室"**：多名 AI Agent 分别扮演**叙事导演**、**主角**、**NPC** 和**评估师**，对同一个故事前提进行 **1～500 条情节线的并行预演**。每条情节线在关键分支点上做出不同选择，探索故事的各种可能性。预演完成后，评估师从**戏剧张力**、**角色成长**、**逻辑一致性**、**结局匹配度**四个维度评选出最佳版本，最终生成一部完整的小说。

> *"千墨选一，落纸成书 — Selected ink, eternal story."*

---

## ✨ 核心特性 | Features

| 特性 | 说明                                                                                                         |
|---|------------------------------------------------------------------------------------------------------------|
| 🎭 **多 Agent 架构** | 叙事导演、主角、NPC 池、评估师——各有独立角色与系统提示词 |
| ⚡ **并行预演** | 基于 `asyncio` 最高支持 500 协程并行 |
| 📋 **多大纲择优** | 生成不同角度大纲，评估后选用最优 |
| 🎯 **节奏控制** | 三幕剧结构 + 动态压力 + 动态每章字数控制 |
| 👥 **主角团模式** | 聚光灯轮换 / 团队 Agent / 全并行，动态超时保护 |
| 🎭 **自动结局** | 不输入结局时 AI 自动设计 |
| 📊 **四维评估** | 戏剧张力 / 角色成长 / 逻辑一致性 / 结局匹配度打分 |
| 🖋️ **写作风格** | 183 位作家 + 搜索 + 自定义 + 公版安全标注 |
| ✨ **智能起名** | 7 种命名风格 + 规则模板 + LLM 择优，章节标题也适用 |
| 🌐 **Web 界面** | FastAPI 暗色主题，SSE 实时进度 + 控制台日志同步 |
| 🔌 **全平台 API** | 13 家主流大模型提供商 |
| 👤 **用户定义 NPC** | 预定义角色（姓名/关系/背景/能力/登场章），AI 可补充 |
| 📥 **多格式导出** | MD / TXT / EPUB / PDF / MOBI / AZW3 + 可选前附文（目录/引言/楔子/人物表） |
| 📝 **日志记录** | 系统日志 + 生成参数文件自动保存 |

---

## 🚀 快速开始 | Quick Start

### 安装依赖

```bash
# 一键安装所有 Python 依赖
pip install -r requirements.txt

# MOBI / AZW3 额外需要（可选）
# 安装 Calibre: https://calibre-ebook.com/
```

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

# ── 写作风格（可选）──
# writing_style: "张爱玲"            # 留空则不模仿特定作家（183 位可选）
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
num_versions: 3                      # 并行预演版本数（1-500，推荐 3～10）
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
| 版本超时 | 15 分钟 | 单个预演版本的墙钟时间上限 |
| 重复动作检测 | 相似度 > 90% | 连续 3 次相似动作 → 强制切换场景 |
| 用户中断 (Ctrl+C) | 优雅保存 | 捕获信号，保存已完成版本后退出 |
| 内容审核 | 敏感词过滤 | 每章自动检测，命中标记警告（不阻断） |
| 公版优先 | 自动标注 | 写作风格中优先展示公版作家 ✅，在世作家标注 🟡 |

---

## 🖥️ Web 界面预览 | Web UI

启动后访问 `http://localhost:8000`：
<img width="2559" height="1316" alt="屏幕截图 2026-06-11 190544" src="https://github.com/user-attachments/assets/4f008e81-d3d6-457c-b79a-ec8dc69f30de" />
<img width="2538" height="1300" alt="屏幕截图 2026-06-11 191004" src="https://github.com/user-attachments/assets/a465e02d-df96-4bb5-b09b-1918952825d9" />

| 页面 | 路径 | 功能 |
|---|---|---|
| 配置页 | `/` | 卡片式表单：主角 / 世界 / 故事 / **指定 NPC** / 写作风格 / 前附文 / 书名风格 / 主角团模式 / NPC策略 / 质量模式 / API 设置 |
| 进度页 | `/progress/{id}` | SSE 实时推送：进度条、版本卡片、**控制台日志同步**、取消按钮 |
| 结果页 | `/result/{id}` | **书名展示 + 情节摘要** + 统计面板 + 版本对比表 + Tab 切换 + 下载 |

### 写作风格选择

Web UI 提供**写作风格**卡片，**183 位**作家按地区 + 类别分组。选择后，叙事 Agent 将模仿该作家的语言特色、叙事节奏和审美取向。

| 类别 | 数量 | 代表作家 |
|------|------|---------|
| 🇨🇳 传统文学 | 25 | 鲁迅、张爱玲、老舍、沈从文、钱钟书、莫言、余华… |
| 🇨🇳 网文大神 | 66 | 猫腻、辰东、Priest、烽火戏诸侯、远瞳、江南、爱潜水的乌贼… |
| 🇯🇵 日本 | 13 | 村上春树、川端康成、三岛由纪夫、夏目漱石… |
| 🇬🇧 英国 | 15 | 狄更斯、奥斯汀、伍尔夫、托尔金… |
| 🇺🇸 美国 | 13 | 海明威、福克纳、菲茨杰拉德… |
| 🇫🇷 法国 | 14 | 雨果、加缪、普鲁斯特、杜拉斯… |
| 🇷🇺 俄罗斯 | 9 | 陀思妥耶夫斯基、托尔斯泰… |
| 🌍 其他 | 28 | 马尔克斯、博尔赫斯、泰戈尔、卡夫卡… |

不选则使用默认风格。

> ⚠️ **法律提示**：本工具优先推荐已进入公有领域的作家（去世超过 50 年，标注 ✅）。
> 选择在世/近期作家风格时，界面会显示风险提示。本工具不保证生成内容与特定作家风格一致，
> 用户对使用生成内容承担全部责任。详见 [使用条款](TERMS.md)。

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
| **Kindle** (.mobi) | Kindle 设备兼容 | Calibre（可选，不可用时降级为 EPUB） |

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
- 🖋️ 183 位作家写作风格（支持搜索 + 自定义）
- ✨ 智能起名：7 种命名风格 + 规则模板 + LLM 评分
- 👥 主角团模式：聚光灯轮换 / 团队 Agent / 全并行（3 种）
- 🧹 NPC 策略：异步并行批处理 / 场景过滤 / 叙事代劳
- ⚖️ 质量模式：平衡 / 质量优先（动态超时 + NPC 数量）
- 📖 前附文：目录 / 引言 / 楔子 / 人物表（可选）
- 👤 用户定义 NPC：预定义角色属性，AI 可补充更多
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

### 添加写作风格
1. 编辑 `writing_style.json`，按现有格式添加新条目
2. 或通过 Web UI 的「写作风格 → 添加自定义风格」提交
3. 提交 PR 时请确保 JSON 格式有效

### 添加 API 提供商
1. 在 `agents.py` 的 `PROVIDER_REGISTRY` 中添加新条目
2. 更新 `webui/templates/index.html` 的下拉列表
3. 如使用非 OpenAI 兼容 SDK，需在 `LLMClient` 中添加新的 `_call_*` 方法

### 开发环境
```bash
git clone <repo-url>
cd novel_preactor
pip install -r requirements.txt
export SIFTED_INK_API_KEY="your-key"
python -m novel_preactor --web
```

---

## 📜 许可证 | License

Apache License 2.0 — 详见 [LICENSE](LICENSE) 文件。

---

<p align="center">
  <sub>Made with ❤️ by Maverick-Noob / 布河狸 · 千墨选一，落纸成书</sub>
</p>
