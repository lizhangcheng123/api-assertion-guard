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
aag -p /path/to/yaml/tests --html report.html --suggest --detail  # 完整功能
```

| 参数 | 说明 |
|------|------|
| `-p / --path` | YAML 测试文件目录（必填） |
| `--html` | 输出 HTML 报告路径 |
| `-d / --detail` | 显示用例级详细分析 |
| `-s / --suggest` | 生成改进建议 |
| `--suggest-output` | 建议保存路径 |
| `--suggest-limit` | 建议最多处理的文件数（默认 10） |

## 评分维度

工具通过**静态分析断言代码**来评分，不需要了解具体业务含义：

| 维度 | 权重 | 评分依据 |
|------|------|---------|
| 断言类型强度 | 20% | check_type 类型 + custom_check 中 assert 数量和深度 |
| 字段覆盖率 | 30% | 验证的响应字段数量（`.get("xxx")` 访问次数） |
| 业务逻辑验证 | 30% | 是否验证列表/数量/返回ID/跨接口/数据库校验 |
| 场景覆盖 | 20% | 是否有异常场景、错误码验证 |

**如何提高分数**：将 `check_json` 改为 `custom_check`，加上字段验证和数据结构断言。`--suggest` 功能会自动生成改进后的 YAML 片段。

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

## 项目结构

```
api-assertion-guard/
├── aag_cli.py        # CLI 入口
├── setup.py
├── requirements.txt
└── aag/
    ├── parser.py     # YAML 解析器
    ├── py_parser.py  # .py 断言解析器
    ├── analyzer.py   # 断言分析引擎
    ├── scorer.py     # 评分器
    ├── reporter.py   # 报告生成器
    └── suggester.py  # 改进建议生成器
```

## 依赖

- `ruamel.yaml` — YAML 解析
- `rich` — 终端彩色输出
