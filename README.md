# API Assertion Guard (aag)

![Python](https://img.shields.io/badge/Python-3.8+-blue) ![License](https://img.shields.io/badge/License-MIT-green) ![Version](https://img.shields.io/badge/version-0.1.0-orange)

解决 API 自动化测试中"全绿但有 bug"的问题——大量测试用例只验证 `code:0 + msg:SUCCESS`，不检查实际业务数据。

## 功能特性

- 扫描 YAML 测试文件及对应 `.py` 文件，分析断言强度
- **4 维度加权评分**：断言类型强度(20%)、字段覆盖率(30%)、业务逻辑验证(30%)、场景覆盖(20%)
- 检测 **8 种弱断言模式**（W001–W008）
- 等级评定：A≥80 优秀 / B≥60 良好 / C≥40 一般 / D≥20 较差 / F<20 极差
- 终端彩色报告 + HTML 可视化报告
- 自动生成改进建议（可直接粘贴到 YAML 的 `custom_check` 片段）
- **断言自动升级**：支持 Level 1 / Level 2 两档升级，并支持回滚
- **Capture 精确升级**：通过 pytest 插件抓取真实响应结构，基于真实字段生成断言
- **CI 门禁**：支持平均分阈值和严重问题数阈值

## 安装

```bash
git clone https://github.com/lizhangcheng123/api-assertion-guard.git
cd api-assertion-guard
pip install .
```

或不安装直接运行：

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 使用

```bash
aag -p /path/to/yaml/tests                                        # 基础扫描
aag -p /path/to/yaml/tests --html report.html                     # HTML 报告
aag -p /path/to/yaml/tests --detail                               # 详细分析
aag -p /path/to/yaml/tests --suggest --suggest-output suggest.md  # 改进建议
aag -p /path/to/yaml/tests --html report.html --suggest --detail  # 完整分析

aag -p /path/to/yaml/tests --upgrade --level 1                    # Level 1 升级
aag -p /path/to/yaml/tests --upgrade --level 2                    # Level 2 升级
aag -p /path/to/yaml/tests --upgrade --level 2 --dry-run          # 仅预览，不改文件
aag -p /path/to/yaml/tests --rollback                             # 回滚 .bak 文件
aag -p /path/to/yaml/tests --upgrade --capture responses.json     # 基于 capture 精确升级
```

| 参数 | 说明 |
|------|------|
| `-p / --path` | YAML 测试文件目录（必填） |
| `--html` | 输出 HTML 报告路径 |
| `-d / --detail` | 显示用例级详细分析 |
| `-s / --suggest` | 生成改进建议 |
| `--suggest-output` | 建议保存路径 |
| `--suggest-limit` | 建议最多处理的文件数（默认 10） |
| `--fail-under` | 平均分低于阈值时返回非零退出码 |
| `--max-critical` | 严重问题数超过阈值时返回非零退出码 |
| `--upgrade` | 执行断言升级 |
| `--level` | 升级级别：1=check_code→check_json，2=弱 check_json→custom_check |
| `--dry-run` | 预览升级结果，不实际修改文件 |
| `--no-backup` | 升级时不生成 `.bak` |
| `--rollback` | 将 `.bak` 回滚为原始文件 |
| `--capture` | 使用 capture 插件抓到的响应结构生成精确断言 |

## 评分维度

工具通过**静态分析断言代码**来评分，不需要了解具体业务含义：

| 维度 | 权重 | 评分依据 |
|------|------|---------|
| 断言类型强度 | 20% | check_type 类型 + custom_check 中 assert 数量和深度 |
| 字段覆盖率 | 30% | 验证的响应字段数量（`.get("xxx")` 访问次数） |
| 业务逻辑验证 | 30% | 是否验证列表/数量/返回ID/跨接口/数据库校验 |
| 场景覆盖 | 20% | 是否有异常场景、错误码验证 |

**如何提高分数**：将 `check_json` 改为 `custom_check`，加上字段验证和数据结构断言。`--suggest` 功能会自动生成改进后的 YAML 片段。对真实项目，推荐优先使用 `capture` 流程生成更准确的断言。

## 弱断言规则

| 规则 | 严重度 | 说明 |
|------|--------|------|
| W001 | critical | 无任何断言（no_check） |
| W002 | critical | 仅校验 HTTP 状态码 |
| W003 | critical | check_json 仅验证 code+msg |
| W004 | warning | custom_check 仅断言 code==0 |
| W005 | critical | 搜索接口未验证返回数据 |
| W006 | warning | 分页接口未验证分页字段 |
| W007 | warning | 创建接口未验证返回 ID |
| W008 | warning | 异常场景期望成功响应 |

## 断言升级

### Level 1

将弱 `check_code` 升级为 `check_json`，补齐 `code + msg` 断言，适合保守改造。

### Level 2

将弱 `check_json` 升级为 `custom_check`，增加数据结构和业务字段断言，适合提升断言质量。

### 预览 / 回滚

```bash
aag -p /path/to/yaml/tests --upgrade --level 2 --dry-run
aag -p /path/to/yaml/tests --rollback
```

默认升级时会生成 `.bak` 备份；如果你在公共仓库中使用，建议先自行备份到本地目录，再配合 `--no-backup` 避免污染项目目录。

## Capture 精确断言

AAG 提供独立 pytest 插件，可在真实运行测试时抓取响应结构，再据此生成更贴近真实接口的断言。

### 1) 抓取真实响应结构

在被测项目目录执行：

```bash
PYTHONPATH=/path/to/api-assertion-guard \
pytest -p aag.capture_plugin \
  --aag-capture /path/to/responses.json \
  path/to/testcase
```

### 2) 用 capture 数据升级断言

```bash
aag -p /path/to/yaml/tests --upgrade --level 2 --capture /path/to/responses.json
```

### 3) 再跑一次真实测试验证

```bash
pytest path/to/testcase -v
```

### capture 能解决什么问题？

不带 capture 的 Level 2 升级使用通用模板推断结构；带 capture 时，AAG 会根据真实响应判断：

- `data` 是 `list` 还是 `dict`
- 是否存在 `records`
- 首条记录的真实字段名（如 `id`、`agentId`、`email`）
- 某些接口的 `data` 是否只是 `bool`

这能避免把错误的通用结构断言写进 YAML，例如把真实 `list` 误判成 `dict.records`。

## 推荐工作流

```bash
# 1. 先扫描评分
aag -p /path/to/yaml/tests --html report_before.html --detail

# 2. 使用 capture 抓真实响应结构
PYTHONPATH=/path/to/api-assertion-guard \
pytest -p aag.capture_plugin \
  --aag-capture responses.json \
  path/to/testcase -v

# 3. 预览升级结果
aag -p /path/to/yaml/tests --upgrade --level 2 --capture responses.json --dry-run

# 4. 正式升级
aag -p /path/to/yaml/tests --upgrade --level 2 --capture responses.json

# 5. 重新跑测试验证
pytest path/to/testcase -v

# 6. 再次评分，查看提升
aag -p /path/to/yaml/tests --html report_after.html
```

## 项目结构

```
api-assertion-guard/
├── aag_cli.py            # CLI 入口
├── setup.py
├── requirements.txt
└── aag/
    ├── parser.py         # YAML 解析器
    ├── py_parser.py      # .py 断言解析器
    ├── analyzer.py       # 断言分析引擎
    ├── scorer.py         # 评分器
    ├── reporter.py       # 报告生成器
    ├── suggester.py      # 改进建议生成器
    ├── upgrader.py       # 断言升级引擎
    ├── upgrade_templates.py # 升级模板
    └── capture_plugin.py # pytest 响应结构抓取插件
```

## 依赖

- `ruamel.yaml` — YAML 解析
- `rich` — 终端彩色输出
