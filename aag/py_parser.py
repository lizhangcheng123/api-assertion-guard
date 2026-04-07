# -*- coding: utf-8 -*-
"""Python 测试文件解析器 - 分析 .py 中的额外断言"""

import os
import re
import logging
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class PyAssertionInfo:
    """从 .py 文件中提取的断言信息"""
    assert_count: int = 0               # 实质 assert 语句数（不含基础检查）
    basic_assert_count: int = 0          # 基础断言数（assert code==200 等）
    has_cross_api_verify: bool = False   # 是否有跨接口验证（创建后查询）
    has_field_validation: bool = False   # 是否有字段级校验
    has_loop_validation: bool = False    # 是否有循环遍历校验
    has_conditional_logic: bool = False  # 是否有条件分支断言
    has_type_check: bool = False         # 是否有类型检查
    has_range_check: bool = False        # 是否有范围/边界检查
    has_allure_steps: int = 0            # allure.step 块数量
    verified_fields: List[str] = field(default_factory=list)  # 验证的字段名
    is_template_only: bool = True        # 是否只是模板代码（无额外断言）


class PyTestParser:
    """解析 Python 测试文件中的断言"""

    # 模板代码中的标准断言（不计为额外断言）
    TEMPLATE_PATTERNS = [
        r'check_result\(test_case,\s*code,\s*data\)',
    ]

    def find_py_file(self, yaml_path: str) -> Optional[str]:
        """根据 YAML 路径找到对应的 .py 文件"""
        # YAML: projects/xxx/page/module/test_xxx.yaml
        # PY:   projects/xxx/testcase/module/test_xxx.py
        py_path = yaml_path.replace('/page/', '/testcase/').replace('.yaml', '.py').replace('.yml', '.py')
        if os.path.exists(py_path):
            return py_path
        return None

    def parse(self, py_path: str) -> PyAssertionInfo:
        """解析 .py 文件，提取断言信息"""
        try:
            with open(py_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except (IOError, UnicodeDecodeError) as e:
            logger.warning("无法读取 %s: %s", py_path, e)
            return PyAssertionInfo()

        info = PyAssertionInfo()

        # 去掉 import 区域和类定义行，只分析测试方法体
        # 找到 check_result 调用之后的代码（额外断言部分）
        check_result_pos = content.find('check_result(')
        if check_result_pos == -1:
            # 没有 check_result，整个文件可能都是自定义逻辑
            test_body = content
        else:
            # 取 check_result 之后的代码
            test_body = content[check_result_pos:]

        # 统计 assert 语句（排除模板中的 check_result 调用）
        # 只统计 check_result 之后的 assert
        # 支持多行 assert（括号内换行或 \ 续行）
        post_check_asserts = []
        lines = test_body.split('\n')
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if re.match(r'^assert\s+', line):
                # 收集可能的续行
                full_line = line
                open_parens = full_line.count('(') - full_line.count(')')
                while (full_line.endswith('\\') or open_parens > 0) and i + 1 < len(lines):
                    i += 1
                    next_line = lines[i].strip()
                    full_line = full_line.rstrip('\\') + ' ' + next_line
                    open_parens = full_line.count('(') - full_line.count(')')
                # 提取 assert 后面的内容
                m = re.match(r'^assert\s+(.+)', full_line)
                if m:
                    post_check_asserts.append(m.group(1))
            i += 1

        # 过滤掉基础断言（assert code == 200, assert data is not None 等）
        BASIC_ASSERT_PATTERNS = [
            r'^code\s*==\s*200',
            r'^data\s+is\s+not\s+None',
            r'^data\s*!=\s*None',
            r'^data\s*,',  # assert data, "xxx"
            r'^code\s*,',  # assert code, "xxx"
        ]

        real_asserts = []
        basic_asserts = []
        for a in post_check_asserts:
            a_stripped = a.strip()
            is_basic = any(re.match(pat, a_stripped) for pat in BASIC_ASSERT_PATTERNS)
            if is_basic:
                basic_asserts.append(a_stripped)
            else:
                real_asserts.append(a_stripped)

        info.assert_count = len(real_asserts)
        info.basic_assert_count = len(basic_asserts)

        if info.assert_count == 0:
            info.is_template_only = True
            return info

        info.is_template_only = False

        # 检测跨接口验证（deepcopy + send_request，都必须在测试方法体内）
        if 'deepcopy' in test_body and 'send_request' in test_body:
            info.has_cross_api_verify = True

        # 检测 allure.step 块
        info.has_allure_steps = len(re.findall(r'with\s+allure\.step\(', test_body))

        # 检测字段级验证（.get() 链式访问）
        field_accesses = re.findall(r"\.get\(['\"](\w+)['\"]\)", test_body)
        if field_accesses:
            info.has_field_validation = True
            # 去重，排除通用字段
            generic_fields = {'data', 'code', 'msg', 'message', 'parameter', 'summary'}
            info.verified_fields = list(set(f for f in field_accesses if f not in generic_fields))

        # 检测循环遍历校验
        if re.search(r'for\s+\w+.*in\s+.*records|for\s+index,\s*item\s+in\s+enumerate', test_body):
            info.has_loop_validation = True

        # 检测条件分支断言（基于 summary 或参数做不同验证）
        if re.search(r'if\s+summary\s*==|if\s+["\'].*["\']\s+in\s+summary|if\s+test_case', test_body):
            info.has_conditional_logic = True

        # 检测类型检查
        if 'isinstance(' in test_body:
            info.has_type_check = True

        # 检测范围检查
        if re.search(r'<=\s*\w+\s*<=|>=|<\s*\w+|>\s*\w+', test_body):
            info.has_range_check = True

        return info

    def score_py_assertions(self, info: PyAssertionInfo) -> dict:
        """对 .py 中的断言进行评分（作为加分项）

        .py 文件中的断言是真实有效的测试逻辑，应该获得充分的分值。
        加分采用"保底 + 累加"模式：有实质断言的文件至少获得一个基础分，
        然后根据断言的深度和广度累加。
        """
        if info.is_template_only:
            return {
                'py_bonus': 0,
                'field_coverage_bonus': 0,
                'business_logic_bonus': 0,
            }

        py_bonus = 0
        field_bonus = 0
        business_bonus = 0

        # ── 断言类型强度加分 ──
        # 有实质 .py 断言 = 至少相当于一个中等强度的 custom_check
        if info.assert_count >= 8:
            py_bonus = 30
        elif info.assert_count >= 5:
            py_bonus = 25
        elif info.assert_count >= 3:
            py_bonus = 20
        elif info.assert_count >= 1:
            py_bonus = 15

        # ── 业务逻辑加分 ──
        # 跨接口验证（创建后查询确认）—— 这是最强的断言模式之一
        if info.has_cross_api_verify:
            business_bonus += 40

        # 循环遍历校验（对每条记录做断言）
        if info.has_loop_validation:
            business_bonus += 25
            field_bonus += 15

        # 条件分支断言（根据场景做不同验证）
        if info.has_conditional_logic:
            business_bonus += 15

        # 范围检查（如时间范围、数值范围）
        if info.has_range_check:
            business_bonus += 15

        # ── 字段覆盖加分 ──
        unique_fields = len(info.verified_fields)
        if unique_fields >= 5:
            field_bonus += 40
        elif unique_fields >= 3:
            field_bonus += 25
        elif unique_fields >= 1:
            field_bonus += 15

        # 类型检查
        if info.has_type_check:
            field_bonus += 10

        return {
            'py_bonus': min(py_bonus, 35),
            'field_coverage_bonus': min(field_bonus, 60),
            'business_logic_bonus': min(business_bonus, 40),
        }
