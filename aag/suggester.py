# -*- coding: utf-8 -*-
"""改进建议生成器 - 根据接口类型自动生成更强的断言"""

from aag.analyzer import FileAnalysis, CaseAnalysis, WeakPattern
from aag.parser import TestCase, TestFile
from typing import List


class AssertionSuggester:
    """为弱断言生成改进建议（YAML 片段）"""

    def suggest_for_file(self, fa: FileAnalysis) -> List[dict]:
        """为一个文件生成所有改进建议"""
        suggestions = []
        for ca in fa.case_analyses:
            if not ca.weak_patterns:
                continue
            # 只为 critical 和 warning 生成建议
            serious = [wp for wp in ca.weak_patterns if wp.severity in ('critical', 'warning')]
            if not serious:
                continue

            sugg = self._generate_suggestion(ca, fa)
            if sugg:
                suggestions.append(sugg)
        return suggestions

    def _generate_suggestion(self, ca: CaseAnalysis, fa: FileAnalysis) -> dict:
        """为单个用例生成改进建议"""
        tc = ca.test_case
        api_type = fa.api_type
        has_pagination = fa.has_pagination

        # 根据接口类型选择模板
        if api_type == 'search':
            new_check = self._suggest_search(tc, has_pagination, fa.test_file)
        elif api_type == 'create':
            new_check = self._suggest_create(tc, fa.test_file)
        elif api_type == 'update':
            new_check = self._suggest_update(tc, fa.test_file)
        elif api_type == 'delete':
            new_check = self._suggest_delete(tc, fa.test_file)
        else:
            new_check = self._suggest_generic(tc, fa.test_file)

        if not new_check:
            return None

        return {
            'file': fa.test_file.rel_path,
            'summary': tc.summary,
            'original': self._format_original(tc),
            'suggested': new_check,
            'reasons': [wp.message for wp in ca.weak_patterns if wp.severity in ('critical', 'warning')],
        }

    # ── 各接口类型的建议模板 ──────────────────────────────────

    def _suggest_search(self, tc: TestCase, has_pagination: bool, tf: TestFile) -> str:
        """搜索/列表接口的改进建议"""
        lines = [
            'assert isinstance(data, dict), f"响应非dict: {type(data)}"',
            'assert data.get("code") == 0, f"业务码错误: {data.get(\'code\')}, msg: {data.get(\'msg\')}"',
            '',
            '# 验证数据结构',
            'resp_data = data.get("data", {})',
            'assert isinstance(resp_data, dict), f"data层非dict: {type(resp_data)}"',
        ]

        # 分页接口额外断言
        if has_pagination:
            page_size = None
            if isinstance(tc.parameter, dict):
                page_size = tc.parameter.get('pageSize')

            lines += [
                '',
                '# 验证分页信息',
                'records = resp_data.get("records", [])',
                'assert isinstance(records, list), "records 应为列表"',
            ]
            if page_size:
                lines.append(f'assert len(records) <= {page_size}, f"返回数量 {{len(records)}} 超过 pageSize={page_size}"')
            lines += [
                '',
                '# 验证记录结构（至少第一条）',
                'if len(records) > 0:',
                '    first = records[0]',
                '    assert isinstance(first, dict), "记录应为dict"',
                '    # TODO: 根据业务补充必要字段检查',
                '    # assert "id" in first, "记录缺少 id 字段"',
            ]

            # 如果有搜索条件，添加结果匹配验证
            if isinstance(tc.parameter, dict):
                condition = tc.parameter.get('condition')
                if condition and isinstance(condition, str) and condition.strip():
                    lines += [
                        '',
                        f'# 验证搜索结果与条件 "{condition}" 匹配',
                        '# for item in records:',
                        '#     assert condition.lower() in str(item).lower(), f"记录不匹配搜索条件"',
                    ]
        else:
            lines += [
                '',
                '# 验证返回数据',
                'if isinstance(resp_data, list):',
                '    assert len(resp_data) >= 0, "数据列表应有效"',
                '    if len(resp_data) > 0:',
                '        first = resp_data[0]',
                '        assert isinstance(first, dict), "数据项应为dict"',
            ]

        return self._wrap_custom_check(lines, tc.expected_code)

    def _suggest_create(self, tc: TestCase, tf: TestFile) -> str:
        """创建接口的改进建议"""
        lines = [
            'assert isinstance(data, dict), f"响应非dict: {type(data)}"',
            'assert data.get("code") == 0, f"业务码错误: {data.get(\'code\')}, msg: {data.get(\'msg\')}"',
            '',
            '# 验证创建结果',
            'resp_data = data.get("data")',
            'if resp_data is not None:',
            '    if isinstance(resp_data, dict):',
            '        # 验证返回的 ID',
            '        assert resp_data.get("id") is not None, "创建后应返回 id"',
            '    elif isinstance(resp_data, (int, str)):',
            '        # 有些接口直接返回 ID',
            '        assert resp_data, "创建后应返回有效 ID"',
        ]

        return self._wrap_custom_check(lines, tc.expected_code)

    def _suggest_update(self, tc: TestCase, tf: TestFile) -> str:
        """更新接口的改进建议"""
        lines = [
            'assert isinstance(data, dict), f"响应非dict: {type(data)}"',
            'assert data.get("code") == 0, f"业务码错误: {data.get(\'code\')}, msg: {data.get(\'msg\')}"',
            '',
            '# 验证更新成功',
            '# 建议：调用 GET 接口验证更新后的数据',
            '# resp_data = data.get("data", {})',
            '# assert resp_data, "更新后应返回数据"',
        ]

        return self._wrap_custom_check(lines, tc.expected_code)

    def _suggest_delete(self, tc: TestCase, tf: TestFile) -> str:
        """删除接口的改进建议"""
        lines = [
            'assert isinstance(data, dict), f"响应非dict: {type(data)}"',
            'assert data.get("code") == 0, f"业务码错误: {data.get(\'code\')}, msg: {data.get(\'msg\')}"',
            '',
            '# 建议：调用 GET 接口验证数据已被删除',
            '# 或验证删除后返回的确认信息',
        ]

        return self._wrap_custom_check(lines, tc.expected_code)

    def _suggest_generic(self, tc: TestCase, tf: TestFile) -> str:
        """通用接口的改进建议"""
        lines = [
            'assert isinstance(data, dict), f"响应非dict: {type(data)}"',
            'assert data.get("code") == 0, f"业务码错误: {data.get(\'code\')}, msg: {data.get(\'msg\')}"',
            '',
            '# 验证响应数据结构',
            'resp_data = data.get("data")',
            'assert resp_data is not None, "data 字段不应为空"',
        ]

        return self._wrap_custom_check(lines, tc.expected_code)

    # ── 辅助方法 ──────────────────────────────────────────

    def _wrap_custom_check(self, code_lines: list, expected_code: int) -> str:
        """包装为 YAML 格式的 custom_check"""
        indent = '      '
        python_code = '\n'.join(f'{indent}{line}' for line in code_lines)

        return (
            f"  check_body:\n"
            f"    check_type: custom_check\n"
            f"    expected_code: {expected_code}\n"
            f"    expected_result:\n"
            f"      python_code: |\n"
            f"{python_code}"
        )

    def _format_original(self, tc: TestCase) -> str:
        """格式化原始断言"""
        if tc.check_type == 'check_json':
            er = tc.expected_result
            if isinstance(er, dict):
                fields = ', '.join(f'{k}: {v}' for k, v in er.items())
                return f"check_json → {{{fields}}}"
        elif tc.check_type == 'check_code':
            return f"check_code → {tc.expected_code}"
        elif tc.check_type == 'no_check':
            return "no_check"
        return f"{tc.check_type}"
