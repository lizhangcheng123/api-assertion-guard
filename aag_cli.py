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
from aag.upgrader import UpgradeEngine


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
    parser.add_argument(
        '--fail-under',
        type=float,
        default=None,
        help='平均分低于此阈值时返回非零退出码（用于 CI 门禁，如: --fail-under 40）',
    )
    parser.add_argument(
        '--max-critical',
        type=int,
        default=None,
        help='严重问题数超过此值时返回非零退出码（用于 CI 门禁，如: --max-critical 10）',
    )
    parser.add_argument(
        '--upgrade',
        action='store_true',
        help='执行断言升级',
    )
    parser.add_argument(
        '--level',
        type=int,
        choices=[1, 2],
        default=2,
        help='升级级别: 1=check_code→check_json, 2=含弱check_json→custom_check（默认2）',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='预览模式，不实际修改文件',
    )
    parser.add_argument(
        '--no-backup',
        action='store_true',
        help='升级时不创建备份文件',
    )
    parser.add_argument(
        '--rollback',
        action='store_true',
        help='回滚：将 .bak 文件恢复为原始文件',
    )
    parser.add_argument(
        '--capture',
        default=None,
        help='使用 capture 插件抓取的 JSON 文件生成精确断言（如: --capture responses.json）',
    )

    args = parser.parse_args()

    # 验证路径
    if not os.path.isdir(args.path):
        print(f"错误: 目录不存在 - {args.path}")
        sys.exit(1)

    # ── 回滚模式 ──
    if args.rollback:
        count = UpgradeEngine.rollback_directory(args.path)
        print(f"\n✅ 已回滚 {count} 个文件")
        sys.exit(0)

    # ── 升级模式 ──
    if args.upgrade:
        _run_upgrade(args)
        sys.exit(0)

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

    # 6. 改进建议（统一生成一次）
    suggestions = None
    if args.suggest or args.suggest_output or args.html:
        suggester = AssertionSuggester()
        score_map = {fs.file_path: fs.total for fs in project_score.file_scores}
        sorted_analyses = sorted(
            file_analyses,
            key=lambda fa: score_map.get(fa.test_file.file_path, 100)
        )
        suggestions = []
        files_with_suggestions = 0
        for fa in sorted_analyses:
            if files_with_suggestions >= args.suggest_limit:
                break
            suggs = suggester.suggest_for_file(fa)
            if suggs:
                suggestions.extend(suggs)
                files_with_suggestions += 1

    if args.suggest or args.suggest_output:
        _print_suggestions(suggestions, args)

    # 7. HTML 报告
    if args.html:
        html_reporter = HtmlReporter()
        output = html_reporter.report(project_score, file_analyses, args.html, suggestions)
        print(f"\n📄 HTML 报告已生成: {os.path.abspath(output)}")

    # 8. 行动引导
    _print_next_steps(project_score, args)

    # 9. CI 门禁
    if args.fail_under is not None and project_score.avg_score < args.fail_under:
        print(f"\n❌ CI 门禁未通过: 平均分 {project_score.avg_score} < 阈值 {args.fail_under}")
        sys.exit(1)
    if args.max_critical is not None and project_score.total_critical > args.max_critical:
        print(f"\n❌ CI 门禁未通过: 严重问题 {project_score.total_critical} > 阈值 {args.max_critical}")
        sys.exit(1)

    print()


def _print_suggestions(all_suggestions, args):
    """输出改进建议"""
    if not all_suggestions:
        print("\n✅ 未发现需要改进的断言")
        return

    # 构建 Markdown 输出
    files_set = set(s['file'] for s in all_suggestions)
    lines = [
        "# API 断言改进建议",
        "",
        f"共 {len(all_suggestions)} 条建议（来自得分最低的 {len(files_set)} 个文件）",
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
        try:
            from rich.console import Console
            from rich.markdown import Markdown
            console = Console()
            console.print()
            console.print(Markdown(content))
        except ImportError:
            print(content)


def _print_next_steps(project_score, args):
    """在报告末尾打印行动引导"""
    hints = []
    if not args.suggest and not args.suggest_output:
        hints.append("运行 --suggest 生成具体改进建议")
    if not args.detail:
        hints.append("运行 --detail 查看每个文件的用例级详情")
    if not args.html:
        hints.append("运行 --html report.html 生成可分享的 HTML 报告")

    if project_score.worst_files:
        worst = project_score.worst_files[0]
        hints.append(f"最优先修复: {worst.rel_path} (得分 {worst.total}, {worst.critical_count} 个严重问题)")

    if hints:
        print("\n💡 下一步:")
        for h in hints:
            print(f"   {h}")


def _print_detail(file_analyses, project_score):
    """打印详细分析"""
    try:
        from rich.console import Console
        from rich.tree import Tree
        console = Console()

        console.print("\n[bold]📋 详细分析[/bold]\n")

        fs_map = {f.file_path: f for f in project_score.file_scores}
        for fa in sorted(file_analyses, key=lambda x: x.test_file.rel_path):
            fs = fs_map.get(fa.test_file.file_path)
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


def _run_upgrade(args):
    """执行断言升级"""
    engine = UpgradeEngine(
        level=args.level,
        dry_run=args.dry_run,
        no_backup=args.no_backup,
        capture_file=args.capture,
    )

    mode = "预览" if args.dry_run else "执行"
    capture_hint = "（使用 capture 数据）" if args.capture else ""
    print(f"\n🔧 正在{mode} Level {args.level} 断言升级{capture_hint}...")
    print(f"   扫描目录: {args.path}")

    summary = engine.upgrade_directory(args.path)

    # 输出结果
    print(f"\n{'=' * 60}")
    print(f"  断言升级{'预览' if args.dry_run else '完成'}")
    print(f"{'=' * 60}")
    print(f"  扫描文件: {summary.total_files_scanned}")
    print(f"  升级文件: {summary.files_upgraded}")
    print(f"  升级用例: {summary.cases_upgraded}")
    print(f"  跳过用例: {summary.cases_skipped}")
    print(f"  升级前平均分: {summary.avg_score_before}")
    print()

    # 显示升级详情
    for result in summary.results:
        if result.upgraded_count == 0:
            continue
        upgraded = [d for d in result.decisions if not d.skip_reason]
        levels = set(d.level for d in upgraded)
        level_str = '/'.join(f'L{l}' for l in sorted(levels))
        print(f"  ✅ {result.rel_path}  [{result.api_type}]  +{result.upgraded_count} 用例 ({level_str})")
        for d in upgraded:
            print(f"     {d.summary}: {d.original_check_type} → {d.target_check_type}")

    # 显示跳过的文件（仅当 verbose 时可以扩展）
    skipped_files = [r for r in summary.results if r.upgraded_count == 0 and r.skipped_count > 0]
    if skipped_files:
        print(f"\n  跳过 {len(skipped_files)} 个文件（已有足够断言或不满足升级条件）")

    if args.dry_run:
        print(f"\n💡 以上为预览，实际执行请去掉 --dry-run 参数")
    else:
        print(f"\n💡 如需回滚，运行: python3 aag_cli.py -p {args.path} --rollback")


if __name__ == '__main__':
    main()
