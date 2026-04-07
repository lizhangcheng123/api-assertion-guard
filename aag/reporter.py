# -*- coding: utf-8 -*-
"""报告生成器 - 终端彩色输出 + HTML 报告"""

import os
import html
import datetime
from aag.scorer import ProjectScore, FileScore


# ── 等级配色 ──────────────────────────────────────────

GRADE_COLORS = {
    'A': 'green',
    'B': 'cyan',
    'C': 'yellow',
    'D': 'red',
    'F': 'bright_red',
}

GRADE_ICONS = {
    'A': '[green]✅[/green]',
    'B': '[cyan]🔵[/cyan]',
    'C': '[yellow]⚠️[/yellow]',
    'D': '[red]❌[/red]',
    'F': '[bright_red]💀[/bright_red]',
}


class TerminalReporter:
    """终端报告"""

    def __init__(self):
        try:
            from rich.console import Console
            from rich.table import Table
            from rich.panel import Panel
            self.console = Console()
            self._rich_available = True
        except ImportError:
            self._rich_available = False

    def report(self, ps: ProjectScore, file_analyses=None):
        if self._rich_available:
            self._rich_report(ps, file_analyses)
        else:
            self._plain_report(ps, file_analyses)

    def _rich_report(self, ps: ProjectScore, file_analyses=None):
        from rich.table import Table
        from rich.panel import Panel
        from rich import box

        c = self.console

        # 标题
        c.print()
        c.print(Panel.fit(
            "[bold]API 断言质量报告[/bold]\n"
            f"[dim]扫描时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/dim]",
            border_style="blue",
        ))

        # 总体概览
        c.print()
        overview = Table(title="项目概览", box=box.ROUNDED, show_header=False)
        overview.add_column("指标", style="bold")
        overview.add_column("数值", justify="right")
        overview.add_row("文件总数", str(ps.total_files))
        overview.add_row("用例总数", str(ps.total_cases))
        overview.add_row("平均得分", f"[bold {'green' if ps.avg_score >= 60 else 'red'}]{ps.avg_score}/100[/]")
        overview.add_row("含 .py 断言", f"[cyan]{ps.files_with_py}[/cyan] / {ps.total_files}")
        overview.add_row("严重问题", f"[red]{ps.total_critical}[/red]")
        overview.add_row("警告数量", f"[yellow]{ps.total_weak - ps.total_critical}[/yellow]")
        c.print(overview)

        # 等级分布
        c.print()
        dist_table = Table(title="等级分布", box=box.ROUNDED)
        dist_table.add_column("等级", justify="center")
        dist_table.add_column("标准", justify="center")
        dist_table.add_column("数量", justify="right")
        dist_table.add_column("占比", justify="right")

        for grade in ['A', 'B', 'C', 'D', 'F']:
            count = ps.grade_dist.get(grade, 0)
            pct = f"{count / ps.total_files * 100:.1f}%" if ps.total_files > 0 else "0%"
            color = GRADE_COLORS[grade]
            labels = {'A': '>=80 优秀', 'B': '>=60 良好', 'C': '>=40 一般', 'D': '>=20 较差', 'F': '<20 极差'}
            dist_table.add_row(f"[{color}]{grade}[/{color}]", labels[grade], str(count), pct)
        c.print(dist_table)

        # 断言类型分布
        c.print()
        ct_table = Table(title="断言类型分布（用例级）", box=box.ROUNDED)
        ct_table.add_column("类型", style="bold")
        ct_table.add_column("数量", justify="right")
        ct_table.add_column("占比", justify="right")
        for ct, count in sorted(ps.check_type_dist.items(), key=lambda x: -x[1]):
            pct = f"{count / ps.total_cases * 100:.1f}%" if ps.total_cases > 0 else "0%"
            ct_table.add_row(ct, str(count), pct)
        c.print(ct_table)

        # 最差文件 TOP 10
        c.print()
        worst_table = Table(title="[red]得分最低 TOP 10[/red]", box=box.ROUNDED)
        worst_table.add_column("#", justify="right", width=3)
        worst_table.add_column("文件", max_width=50)
        worst_table.add_column("类型", justify="center", width=8)
        worst_table.add_column("用例", justify="right", width=4)
        worst_table.add_column("PY", justify="center", width=4)
        worst_table.add_column("得分", justify="right", width=6)
        worst_table.add_column("等级", justify="center", width=4)
        worst_table.add_column("严重", justify="right", width=4)

        for i, fs in enumerate(ps.worst_files, 1):
            color = GRADE_COLORS[fs.grade]
            py_mark = f"[cyan]{fs.py_assert_count}[/cyan]" if fs.has_py_assertions else "[dim]-[/dim]"
            worst_table.add_row(
                str(i),
                fs.rel_path,
                fs.api_type,
                str(fs.case_count),
                py_mark,
                f"[{color}]{fs.total}[/{color}]",
                f"[{color}]{fs.grade}[/{color}]",
                f"[red]{fs.critical_count}[/red]" if fs.critical_count > 0 else "0",
            )
        c.print(worst_table)

        # 最佳文件 TOP 5
        c.print()
        best_table = Table(title="[green]得分最高 TOP 5[/green]", box=box.ROUNDED)
        best_table.add_column("#", justify="right", width=3)
        best_table.add_column("文件", max_width=50)
        best_table.add_column("类型", justify="center", width=8)
        best_table.add_column("用例", justify="right", width=4)
        best_table.add_column("PY", justify="center", width=4)
        best_table.add_column("得分", justify="right", width=6)
        best_table.add_column("等级", justify="center", width=4)

        for i, fs in enumerate(ps.best_files, 1):
            color = GRADE_COLORS[fs.grade]
            py_mark = f"[cyan]{fs.py_assert_count}[/cyan]" if fs.has_py_assertions else "[dim]-[/dim]"
            best_table.add_row(
                str(i),
                fs.rel_path,
                fs.api_type,
                str(fs.case_count),
                py_mark,
                f"[{color}]{fs.total}[/{color}]",
                f"[{color}]{fs.grade}[/{color}]",
            )
        c.print(best_table)

        # 弱断言模式详情 (只显示 critical)
        c.print()
        c.print("[bold red]严重弱断言问题汇总[/bold red]")
        c.print()

        # 构建 file_path → FileAnalysis 映射
        fa_map = {}
        if file_analyses:
            fa_map = {fa.test_file.file_path: fa for fa in file_analyses}

        shown = 0
        for fs in sorted(ps.file_scores, key=lambda x: x.total):
            if fs.critical_count == 0:
                continue
            if shown >= 15:
                remaining = sum(1 for f in ps.file_scores if f.critical_count > 0) - shown
                if remaining > 0:
                    c.print(f"  [dim]... 还有 {remaining} 个文件存在严重问题[/dim]")
                break

            color = GRADE_COLORS[fs.grade]
            c.print(f"  [{color}]{fs.grade}[/{color}] [bold]{fs.rel_path}[/bold]  得分: [{color}]{fs.total}[/{color}]")

            # 从 FileAnalysis 获取弱断言详情
            fa = fa_map.get(fs.file_path)
            if fa:
                seen = set()
                for ca in fa.case_analyses:
                    for wp in ca.weak_patterns:
                        if wp.severity == 'critical' and wp.message not in seen:
                            seen.add(wp.message)
                            c.print(f"    [red]  [{wp.code}][/red] {wp.message}")
            c.print()

            shown += 1

        c.print()

    def _plain_report(self, ps: ProjectScore, file_analyses=None):
        """无 rich 库时的纯文本报告"""
        print()
        print("=" * 60)
        print("  API 断言质量报告")
        print("=" * 60)
        print()
        print(f"  文件总数: {ps.total_files}")
        print(f"  用例总数: {ps.total_cases}")
        print(f"  平均得分: {ps.avg_score}/100")
        print(f"  严重问题: {ps.total_critical}")
        print()

        print("  等级分布:")
        for grade in ['A', 'B', 'C', 'D', 'F']:
            count = ps.grade_dist.get(grade, 0)
            bar = '#' * count
            print(f"    {grade}: {count:3d} {bar}")

        print()
        print("  得分最低 TOP 10:")
        for i, fs in enumerate(ps.worst_files, 1):
            print(f"    {i:2d}. [{fs.grade}] {fs.total:5.1f}  {fs.rel_path}")

        print()
        print("  得分最高 TOP 5:")
        for i, fs in enumerate(ps.best_files, 1):
            print(f"    {i:2d}. [{fs.grade}] {fs.total:5.1f}  {fs.rel_path}")

        print()


class HtmlReporter:
    """HTML 报告生成器"""

    def report(self, ps: ProjectScore, file_analyses, output_path: str, suggestions=None):
        """生成 HTML 报告"""
        html = self._build_html(ps, file_analyses, suggestions)
        os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)
        return output_path

    def _build_html(self, ps: ProjectScore, file_analyses, suggestions=None) -> str:
        grade_colors = {'A': '#22c55e', 'B': '#06b6d4', 'C': '#eab308', 'D': '#ef4444', 'F': '#dc2626'}
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # 等级分布数据
        grade_bars = ""
        for grade in ['A', 'B', 'C', 'D', 'F']:
            count = ps.grade_dist.get(grade, 0)
            pct = count / ps.total_files * 100 if ps.total_files > 0 else 0
            color = grade_colors[grade]
            grade_bars += f'<div class="bar-row"><span class="bar-label">{grade}</span><div class="bar" style="width:{pct}%;background:{color}"></div><span class="bar-value">{count} ({pct:.1f}%)</span></div>\n'

        # 文件列表
        file_rows = ""
        for fs in sorted(ps.file_scores, key=lambda x: x.total):
            color = grade_colors[fs.grade]
            file_rows += f"""<tr>
                <td><span class="grade" style="background:{color}">{fs.grade}</span></td>
                <td class="filepath">{html.escape(fs.rel_path)}</td>
                <td>{html.escape(fs.method)}</td>
                <td>{html.escape(fs.api_type)}</td>
                <td>{fs.case_count}</td>
                <td style="color:{color};font-weight:bold">{fs.total}</td>
                <td style="color:#ef4444">{fs.critical_count}</td>
            </tr>\n"""

        # 弱断言详情
        weak_details = ""
        fs_map = {f.file_path: f for f in ps.file_scores}
        for fa in file_analyses:
            fs = fs_map.get(fa.test_file.file_path)
            if not fs or fs.critical_count == 0:
                continue
            patterns_html = ""
            for ca in fa.case_analyses:
                for wp in ca.weak_patterns:
                    sev_color = '#ef4444' if wp.severity == 'critical' else '#eab308'
                    patterns_html += f'<div class="pattern"><span class="sev" style="color:{sev_color}">[{html.escape(wp.code)}]</span> {html.escape(wp.message)}<br><span class="suggest">💡 {html.escape(wp.suggestion)}</span></div>\n'
            if patterns_html:
                weak_details += f'<div class="file-detail"><h4>{html.escape(fs.rel_path)} <span style="color:{grade_colors[fs.grade]}">({fs.total}分)</span></h4>{patterns_html}</div>\n'

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>API 断言质量报告</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: -apple-system, 'Segoe UI', sans-serif; background:#0f172a; color:#e2e8f0; padding:2rem; }}
h1 {{ color:#f8fafc; margin-bottom:0.5rem; }}
.subtitle {{ color:#94a3b8; margin-bottom:2rem; }}
.cards {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(180px,1fr)); gap:1rem; margin-bottom:2rem; }}
.card {{ background:#1e293b; border-radius:12px; padding:1.5rem; text-align:center; }}
.card .value {{ font-size:2rem; font-weight:bold; }}
.card .label {{ color:#94a3b8; font-size:0.875rem; margin-top:0.25rem; }}
.section {{ background:#1e293b; border-radius:12px; padding:1.5rem; margin-bottom:1.5rem; }}
.section h3 {{ color:#f8fafc; margin-bottom:1rem; }}
.bar-row {{ display:flex; align-items:center; margin:0.5rem 0; }}
.bar-label {{ width:30px; font-weight:bold; }}
.bar {{ height:24px; border-radius:4px; min-width:2px; transition:width 0.5s; }}
.bar-value {{ margin-left:0.75rem; color:#94a3b8; font-size:0.875rem; }}
table {{ width:100%; border-collapse:collapse; }}
th {{ text-align:left; padding:0.75rem; border-bottom:2px solid #334155; color:#94a3b8; font-size:0.875rem; }}
td {{ padding:0.75rem; border-bottom:1px solid #1e293b; }}
.filepath {{ font-family:monospace; font-size:0.8rem; max-width:400px; word-break:break-all; }}
.grade {{ display:inline-block; width:28px; height:28px; line-height:28px; text-align:center; border-radius:6px; color:#fff; font-weight:bold; font-size:0.875rem; }}
.file-detail {{ margin:1rem 0; padding:1rem; background:#0f172a; border-radius:8px; }}
.file-detail h4 {{ margin-bottom:0.75rem; }}
.pattern {{ margin:0.5rem 0; padding:0.5rem; background:#1e293b; border-radius:6px; font-size:0.875rem; }}
.sev {{ font-weight:bold; margin-right:0.25rem; }}
.suggest {{ color:#94a3b8; font-size:0.8rem; }}
</style>
</head>
<body>
<h1>API 断言质量报告</h1>
<p class="subtitle">生成时间: {now}</p>

<div class="cards">
    <div class="card"><div class="value">{ps.total_files}</div><div class="label">文件总数</div></div>
    <div class="card"><div class="value">{ps.total_cases}</div><div class="label">用例总数</div></div>
    <div class="card"><div class="value" style="color:{'#22c55e' if ps.avg_score >= 60 else '#ef4444'}">{ps.avg_score}</div><div class="label">平均得分</div></div>
    <div class="card"><div class="value" style="color:#ef4444">{ps.total_critical}</div><div class="label">严重问题</div></div>
</div>

<div class="section">
    <h3>等级分布</h3>
    {grade_bars}
</div>

<div class="section">
    <h3>全部文件 (按得分升序)</h3>
    <table>
    <tr><th>等级</th><th>文件</th><th>方法</th><th>类型</th><th>用例</th><th>得分</th><th>严重</th></tr>
    {file_rows}
    </table>
</div>

<div class="section">
    <h3>弱断言问题详情</h3>
    {weak_details if weak_details else '<p style="color:#94a3b8">暂无严重问题</p>'}
</div>

{self._build_suggestions_html(suggestions) if suggestions else ''}

</body>
</html>"""

    def _build_suggestions_html(self, suggestions) -> str:
        """构建改进建议 HTML 区块"""
        if not suggestions:
            return ''

        items = ''
        for sugg in suggestions[:20]:  # 最多展示20条
            reasons = ''.join(f'<li>{html.escape(r)}</li>' for r in sugg['reasons'])
            # HTML 转义代码块
            code = html.escape(sugg['suggested'])
            items += f'''<div class="file-detail">
                <h4>{html.escape(sugg['file'])} — {html.escape(sugg['summary'])}</h4>
                <p style="color:#94a3b8">原始: <code>{html.escape(sugg['original'])}</code></p>
                <p style="color:#f87171">问题:</p>
                <ul style="color:#fca5a5;font-size:0.85rem;margin:0.5rem 0">{reasons}</ul>
                <p style="color:#4ade80">建议改为:</p>
                <pre style="background:#0f172a;padding:1rem;border-radius:6px;font-size:0.8rem;overflow-x:auto;color:#e2e8f0">{code}</pre>
            </div>\n'''

        remaining = len(suggestions) - 20
        if remaining > 0:
            items += f'<p style="color:#94a3b8;text-align:center">... 还有 {remaining} 条建议未展示</p>'

        return f'''<div class="section">
    <h3>改进建议（可直接复制到 YAML）</h3>
    {items}
</div>'''
