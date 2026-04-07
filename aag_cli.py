#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""API Assertion Guard - CLI 入口"""

import sys
import os
import argparse

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from aag.parser import YamlTestParser
from aag.analyzer import AssertionAnalyzer
from aag.scorer import AssertionScorer
from aag.reporter import TerminalReporter, HtmlReporter
from aag.suggester import AssertionSuggester


def main():
    parser = argparse.ArgumentParser(
        description='API Assertion Guard - API 断言质量检查工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python aag_cli.py -p /path/to/yaml/tests
  python aag_cli.py -p /path/to/yaml/tests --html report.html
  python aag_cli.py -p /path/to/yaml/tests --suggest
  python aag_cli.py -p /path/to/yaml/tests --suggest --suggest-output suggestions.md
  python aag_cli.py -p /path/to/yaml/tests --detail
        """,
    )
    parser.add_argument(
        '--path', '-p',
        required=True,
        help='YAML 测试文件目录路径',
    )
    parser.add_argument(
        '--html',
        default=None,
        help='输出 HTML 报告路径（如: report.html）',
    )
    parser.add_argument(
        '--detail', '-d',
        action='store_true',
        help='显示每个文件的详细分析',
    )
    parser.add_argument(
        '--suggest', '-s',
        action='store_true',
        help='生成改进建议',
    )
    parser.add_argument(
        '--suggest-output',
        default=None,
        help='改进建议输出文件路径（默认输出到终端）',
    )
    parser.add_argument(
        '--suggest-limit',
        type=int,
        default=10,
        help='改进建议最多展示文件数（默认10）',
    )

    args = parser.parse_args()

    # 验证路径
    if not os.path.isdir(args.path):
        print(f"错误: 目录不存在 - {args.path}")
        sys.exit(1)

    # 1. 解析
    print(f"\n🔍 正在扫描: {args.path}")
    yaml_parser = YamlTestParser()
    test_files = yaml_parser.parse_directory(args.path)
    print(f"   找到 {len(test_files)} 个 YAML 测试文件")

    if not test_files:
        print("未找到任何有效的 YAML 测试文件")
        sys.exit(0)

    # 2. 分析
    print("📊 正在分析断言质量...")
    analyzer = AssertionAnalyzer()
    file_analyses = [analyzer.analyze_file(tf) for tf in test_files]

    # 3. 评分
    scorer = AssertionScorer()
    project_score = scorer.score_project(file_analyses)

    # 4. 终端报告
    terminal = TerminalReporter()
    terminal.report(project_score, file_analyses)

    # 5. 详细模式
    if args.detail:
        _print_detail(file_analyses, project_score)

    # 6. 改进建议
    if args.suggest or args.suggest_output:
        _print_suggestions(file_analyses, project_score, args)

    # 7. HTML 报告
    if args.html:
        html_reporter = HtmlReporter()
        # 如果开启了 suggest，把建议也加入 HTML
        suggestions = None
        if args.suggest or args.suggest_output:
            suggester = AssertionSuggester()
            suggestions = []
            for fa in file_analyses:
                suggestions.extend(suggester.suggest_for_file(fa))
        output = html_reporter.report(project_score, file_analyses, args.html, suggestions)
        print(f"\n📄 HTML 报告已生成: {os.path.abspath(output)}")

    print()


def _print_suggestions(file_analyses, project_score, args):
    """生成并输出改进建议"""
    suggester = AssertionSuggester()

    # 按得分排序，优先处理最差的文件
    sorted_analyses = sorted(
        file_analyses,
        key=lambda fa: next(
            (fs.total for fs in project_score.file_scores if fs.file_path == fa.test_file.file_path), 100
        )
    )

    all_suggestions = []
    files_with_suggestions = 0

    for fa in sorted_analyses:
        if files_with_suggestions >= args.suggest_limit:
            break
        suggs = suggester.suggest_for_file(fa)
        if suggs:
            all_suggestions.extend(suggs)
            files_with_suggestions += 1

    if not all_suggestions:
        print("\n✅ 未发现需要改进的断言")
        return

    # 构建 Markdown 输出
    lines = [
        "# API 断言改进建议",
        "",
        f"共 {len(all_suggestions)} 条建议（来自得分最低的 {files_with_suggestions} 个文件）",
        "",
        "---",
        "",
    ]

    current_file = None
    for sugg in all_suggestions:
        if sugg['file'] != current_file:
            current_file = sugg['file']
            lines.append(f"## {current_file}")
            lines.append("")

        lines.append(f"### 用例: {sugg['summary']}")
        lines.append("")
        lines.append(f"**原始断言**: `{sugg['original']}`")
        lines.append("")
        lines.append("**问题**:")
        for reason in sugg['reasons']:
            lines.append(f"- {reason}")
        lines.append("")
        lines.append("**建议改为**:")
        lines.append("```yaml")
        lines.append(sugg['suggested'])
        lines.append("```")
        lines.append("")
        lines.append("---")
        lines.append("")

    content = '\n'.join(lines)

    # 输出到文件或终端
    if args.suggest_output:
        with open(args.suggest_output, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"\n💡 改进建议已保存: {os.path.abspath(args.suggest_output)}")
    else:
        # 终端输出
        try:
            from rich.console import Console
            from rich.markdown import Markdown
            console = Console()
            console.print()
            console.print(Markdown(content))
        except ImportError:
            print(content)


def _print_detail(file_analyses, project_score):
    """打印详细分析"""
    try:
        from rich.console import Console
        from rich.tree import Tree
        console = Console()

        console.print("\n[bold]📋 详细分析[/bold]\n")

        for fa in sorted(file_analyses, key=lambda x: x.test_file.rel_path):
            fs = next((f for f in project_score.file_scores if f.file_path == fa.test_file.file_path), None)
            if not fs:
                continue

            grade_color = {'A': 'green', 'B': 'cyan', 'C': 'yellow', 'D': 'red', 'F': 'bright_red'}
            color = grade_color.get(fs.grade, 'white')

            py_info = ""
            if fs.has_py_assertions:
                py_info = f"  [cyan]PY:{fs.py_assert_count}[/cyan]"

            tree = Tree(f"[{color}][{fs.grade}][/{color}] [bold]{fs.rel_path}[/bold]  "
                        f"得分:[{color}]{fs.total}[/{color}]  "
                        f"接口:{fs.api_type}  方法:{fs.method}{py_info}")

            for ca in fa.case_analyses:
                case_node = tree.add(f"[dim]{ca.test_case.summary}[/dim]  "
                                     f"类型:{ca.test_case.check_type}")

                for wp in ca.weak_patterns:
                    sev_color = {'critical': 'red', 'warning': 'yellow', 'info': 'dim'}.get(wp.severity, 'white')
                    case_node.add(f"[{sev_color}][{wp.code}][/{sev_color}] {wp.message}")

            console.print(tree)
            console.print()

    except ImportError:
        print("\n详细模式需要 rich 库: pip install rich")


if __name__ == '__main__':
    main()
