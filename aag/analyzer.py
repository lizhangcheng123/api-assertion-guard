# -*- coding: utf-8 -*-
"""断言分析引擎 - 检测弱断言模式"""

import re
from dataclasses import dataclass, field
from typing import List, Optional
from aag.parser import TestCase, TestFile
from aag.py_parser import PyTestParser, PyAssertionInfo


# ── 弱断言模式定义 ──────────────────────────────────────────────

@dataclass
class WeakPattern:
    """一条弱断言检测结果"""
    code: str       # 规则编码
    severity: str   # critical / warning / info
    message: str    # 中文描述
    suggestion: str  # 改进建议


# ── 评分常量 ──────────────────────────────────────────────

# 仅含 code/msg 的字段集合
ONLY_CODE_MSG_FIELDS = frozenset({'code', 'msg', 'message'})

# check_json 动态评分阈值
CHECK_JSON_SCORES = {
    'code_msg_only': 30,
    'few_fields': 45,       # ≤4 字段
    'moderate_fields': 60,  # ≤8 字段
    'many_fields': 70,      # >8 字段
}

# 字段覆盖率
FIELD_COVERAGE_SCORES = {
    'entirely_check': 90,
    'regular_check': 30,
    'check_code': 5,
    'json_code_msg': 20,
    'json_few': 40,
    'json_moderate': 60,
    'json_many': 80,
}

# 业务逻辑分值
BIZ_SCORES = {
    'check_db': 40,
    'check_code': 10,
    'has_code_field': 15,
    'extra_fields': 15,
    'data_layer': 20,
    'search_records': 25,
    'search_len': 15,
    'create_id': 25,
    'pagination': 20,
    'error_code': 15,
}


# 接口类型关键词（全词匹配，避免子串误判如 get 匹配 budget）
SEARCH_KEYWORDS = ['search', 'list', 'query', 'find', 'page', 'getall', 'getlist']
CREATE_KEYWORDS = ['add', 'create', 'insert', 'save', 'register', 'import']
UPDATE_KEYWORDS = ['update', 'edit', 'modify', 'put', 'patch', 'switch']
DELETE_KEYWORDS = ['delete', 'remove', 'destroy', 'cancel']
DETAIL_KEYWORDS = ['get', 'detail', 'info', 'view', 'show', 'fetch', 'profile']
ACTION_KEYWORDS = ['send', 'submit', 'execute', 'run', 'trigger', 'apply',
                   'enable', 'disable', 'activate', 'deactivate', 'verify',
                   'confirm', 'approve', 'reject', 'publish', 'unpublish',
                   'export', 'download', 'upload', 'sync', 'refresh', 'retry']
PAGINATION_KEYWORDS = ['pageNo', 'pageSize', 'page_no', 'page_size', 'offset', 'limit']

# 路径中的 ID 占位符模式（/123, /{id}, /:id）
_ID_IN_PATH_RE = re.compile(r'/(\d+|{\w+}|:\w+)/?$')


@dataclass
class CaseAnalysis:
    """单个用例的分析结果"""
    test_case: Optional[TestCase] = None
    weak_patterns: List[WeakPattern] = field(default_factory=list)
    check_type_score: int = 0       # 断言类型强度 (0-100)
    field_coverage_score: int = 0   # 字段覆盖率 (0-100)
    business_logic_score: int = 0   # 业务逻辑验证 (0-100)
    scenario_score: int = 0         # 场景覆盖 (0-100)


@dataclass
class FileAnalysis:
    """文件级分析结果"""
    test_file: Optional[TestFile] = None
    case_analyses: List[CaseAnalysis] = field(default_factory=list)
    api_type: str = ""  # search/create/update/delete/other
    has_pagination: bool = False
    py_info: Optional[PyAssertionInfo] = None  # .py 文件断言信息
    py_file_path: str = ""  # 对应的 .py 文件路径


class AssertionAnalyzer:
    """断言分析器"""

    def __init__(self):
        self.py_parser = PyTestParser()

    def analyze_file(self, test_file: TestFile) -> FileAnalysis:
        """分析整个测试文件（YAML + 对应的 .py）"""
        fa = FileAnalysis(test_file=test_file)
        fa.api_type = self._detect_api_type(test_file)
        fa.has_pagination = self._detect_pagination(test_file)

        # 解析对应的 .py 文件
        py_path = self.py_parser.find_py_file(test_file.file_path)
        if py_path:
            fa.py_file_path = py_path
            fa.py_info = self.py_parser.parse(py_path)

        for tc in test_file.test_cases:
            ca = self._analyze_case(tc, test_file, fa)
            fa.case_analyses.append(ca)

        return fa

    def _analyze_case(self, tc: TestCase, tf: TestFile, fa: FileAnalysis) -> CaseAnalysis:
        """分析单个用例（YAML 断言 + .py 额外断言）"""
        ca = CaseAnalysis(test_case=tc)

        # 1. 断言类型强度评分
        ca.check_type_score = self._score_check_type(tc)

        # 2. 字段覆盖率评分
        ca.field_coverage_score = self._score_field_coverage(tc)

        # 3. 业务逻辑验证评分
        ca.business_logic_score = self._score_business_logic(tc, fa)

        # 4. 应用 .py 文件加分
        # 原则：.py 是锦上添花，加分上限 = max(YAML基础分*2, 25)
        if fa.py_info and not fa.py_info.is_template_only:
            py_scores = self.py_parser.score_py_assertions(fa.py_info)
            # 断言类型
            ca.check_type_score = min(ca.check_type_score + py_scores['py_bonus'], 100)
            # 字段覆盖
            field_cap = max(ca.field_coverage_score * 2, 25)
            ca.field_coverage_score = min(
                ca.field_coverage_score + min(py_scores['field_coverage_bonus'], field_cap),
                100
            )
            # 业务逻辑
            biz_cap = max(ca.business_logic_score * 2, 25)
            ca.business_logic_score = min(
                ca.business_logic_score + min(py_scores['business_logic_bonus'], biz_cap),
                100
            )

        # 5. 检测弱断言模式（考虑 .py 补充后的情况）
        ca.weak_patterns = self._detect_weak_patterns(tc, tf, fa)

        return ca

    # ── 断言类型强度 ──────────────────────────────────────────

    def _score_check_type(self, tc: TestCase) -> int:
        scores = {
            'no_check': 0,
            'check_code': 20,
            'check_json': self._score_check_json_type(tc),
            'regular_check': 55,
            'entirely_check': 80,
            'custom_check': self._score_custom_check(tc),
        }
        return scores.get(tc.check_type, 0)

    def _score_check_json_type(self, tc: TestCase) -> int:
        """check_json 的断言类型分根据字段数动态计算"""
        er = tc.expected_result
        if not isinstance(er, dict):
            return CHECK_JSON_SCORES['code_msg_only']
        fields = set(er.keys())
        if fields <= ONLY_CODE_MSG_FIELDS:
            return CHECK_JSON_SCORES['code_msg_only']
        elif len(fields) <= 4:
            return CHECK_JSON_SCORES['few_fields']
        elif len(fields) <= 8:
            return CHECK_JSON_SCORES['moderate_fields']
        else:
            return CHECK_JSON_SCORES['many_fields']

    def _score_custom_check(self, tc: TestCase) -> int:
        """分析 custom_check 的实际断言深度"""
        if not isinstance(tc.expected_result, dict):
            return 30

        python_code = tc.expected_result.get('python_code', '')
        assertions = tc.expected_result.get('assertions', [])

        score = 30  # 基础分

        if python_code:
            code = str(python_code)
            assert_count = len(re.findall(r'\bassert\b', code))

            if assert_count == 0:
                return 20
            elif assert_count == 1:
                # 只有一个 assert，检查是否只是 code==0
                if re.search(r'assert.*code.*==\s*0', code) and assert_count == 1:
                    return 25  # 伪装的弱断言
                score = 40
            elif assert_count <= 3:
                score = 60
            else:
                score = 75

            # 加分项
            if re.search(r'data\.get\(["\']data["\']\)', code) or 'data["data"]' in code:
                score = min(score + 10, 100)  # 验证了业务数据层
            if re.search(r'isinstance\(.*list\)', code):
                score = min(score + 5, 100)  # 验证了数据类型
            if re.search(r'\[0\]|\["\w+"\]', code):
                score = min(score + 5, 100)  # 验证了嵌套结构
            if 'len(' in code:
                score = min(score + 5, 100)  # 验证了数量

        if assertions:
            score = 40 + min(len(assertions) * 10, 40)

        return min(score, 100)

    # ── 字段覆盖率 ──────────────────────────────────────────

    def _score_field_coverage(self, tc: TestCase) -> int:
        if tc.check_type == 'no_check':
            return 0
        if tc.check_type == 'check_code':
            return 5

        er = tc.expected_result
        if not er:
            return 0

        if tc.check_type == 'entirely_check':
            return 90  # 完全比对，覆盖率最高

        if tc.check_type == 'custom_check':
            return self._count_custom_fields(er)

        if tc.check_type == 'check_json':
            return self._count_json_fields(er)

        if tc.check_type == 'regular_check':
            return 30  # 正则能覆盖一部分

        return 0

    def _count_json_fields(self, expected_result) -> int:
        """统计 check_json 中验证了多少字段"""
        if not isinstance(expected_result, dict):
            return 0

        fields = set(expected_result.keys())
        if fields <= ONLY_CODE_MSG_FIELDS:
            return FIELD_COVERAGE_SCORES['json_code_msg']
        elif len(fields) <= 4:
            return FIELD_COVERAGE_SCORES['json_few']
        elif len(fields) <= 8:
            return FIELD_COVERAGE_SCORES['json_moderate']
        else:
            return FIELD_COVERAGE_SCORES['json_many']

    def _count_custom_fields(self, expected_result) -> int:
        """统计 custom_check 中涉及的字段"""
        if not isinstance(expected_result, dict):
            return 0

        python_code = expected_result.get('python_code', '')
        assertions = expected_result.get('assertions', [])

        score = 10
        if python_code:
            code = str(python_code)
            # 计算访问了多少不同的字段
            field_accesses = set(re.findall(r'(?:data|tpl|resp)(?:\["|\.get\(")(\w+)', code))
            field_accesses.update(re.findall(r'["\'](\w+)["\']\s*in\s+\w+', code))

            unique_fields = len(field_accesses)
            if unique_fields == 0:
                score = 10
            elif unique_fields <= 2:
                score = 25
            elif unique_fields <= 5:
                score = 50
            elif unique_fields <= 10:
                score = 70
            else:
                score = 85

        if assertions:
            score = max(score, 20 + min(len(assertions) * 10, 60))

        return min(score, 100)

    # ── 业务逻辑验证 ──────────────────────────────────────────

    def _score_business_logic(self, tc: TestCase, fa: FileAnalysis) -> int:
        score = 0

        # 如果有数据库校验，大幅加分
        if tc.has_check_db:
            score += BIZ_SCORES['check_db']

        if tc.check_type == 'no_check':
            return score

        if tc.check_type == 'check_code':
            return score + BIZ_SCORES['check_code']

        er = tc.expected_result
        if not er:
            return score

        # check_json 验证了 code==0 本身就是业务逻辑验证
        if tc.check_type == 'check_json' and isinstance(er, dict):
            fields = set(er.keys())
            if 'code' in fields:
                score += BIZ_SCORES['has_code_field']

            if not fields <= ONLY_CODE_MSG_FIELDS:
                score += BIZ_SCORES['extra_fields']
            if 'data' in er and isinstance(er.get('data'), dict):
                score += BIZ_SCORES['data_layer']

        if tc.check_type == 'custom_check' and isinstance(er, dict):
            python_code = str(er.get('python_code', ''))

            # 搜索接口：验证搜索结果是否与条件匹配
            if fa.api_type == 'search':
                if any(kw in python_code.lower() for kw in ['records', 'list', 'items', 'results']):
                    score += BIZ_SCORES['search_records']
                if 'len(' in python_code:
                    score += BIZ_SCORES['search_len']

            # 创建接口：验证返回的 ID
            if fa.api_type == 'create':
                if any(kw in python_code.lower() for kw in ['id', 'created', 'insert']):
                    score += BIZ_SCORES['create_id']

            # 分页接口：验证分页参数
            if fa.has_pagination:
                if any(kw in python_code.lower() for kw in ['page', 'total', 'size']):
                    score += BIZ_SCORES['pagination']

            # 验证了错误码（非0场景）
            if re.search(r'code.*!=\s*0|code.*==\s*\d{3,}', python_code):
                score += BIZ_SCORES['error_code']

        return min(score, 100)

    # ── 弱断言模式检测 ──────────────────────────────────────────

    def _detect_weak_patterns(self, tc: TestCase, tf: TestFile, fa: FileAnalysis) -> List[WeakPattern]:
        patterns = []

        # .py 文件是否有额外断言
        py_has_extra = fa.py_info and not fa.py_info.is_template_only

        # W001: 无断言
        if tc.check_type == 'no_check':
            if py_has_extra:
                patterns.append(WeakPattern(
                    code='W001', severity='warning',
                    message='YAML 无断言（no_check），但 .py 有额外断言',
                    suggestion='建议将关键断言也写入 YAML 以便统一管理'
                ))
            else:
                patterns.append(WeakPattern(
                    code='W001', severity='critical',
                    message='无任何断言（no_check）',
                    suggestion='至少添加状态码和业务码验证'
                ))
            return patterns

        # W002: 只检查状态码
        if tc.check_type == 'check_code':
            if py_has_extra:
                patterns.append(WeakPattern(
                    code='W002', severity='info',
                    message='YAML 仅校验状态码，但 .py 有补充断言',
                    suggestion='考虑将核心断言迁移到 YAML 中统一管理'
                ))
            else:
                patterns.append(WeakPattern(
                    code='W002', severity='critical',
                    message='仅校验 HTTP 状态码，未验证响应体',
                    suggestion='使用 check_json 或 custom_check 验证响应体'
                ))
            return patterns

        er = tc.expected_result

        # W003: check_json 只验证 code+msg
        if tc.check_type == 'check_json' and isinstance(er, dict):
            fields = set(er.keys())
            if fields <= ONLY_CODE_MSG_FIELDS:
                if py_has_extra:
                    # .py 有补充断言，降级为 info
                    msg_parts = ['YAML 仅验证 code+msg，但 .py 有补充断言']
                    if fa.py_info.has_cross_api_verify:
                        msg_parts.append('(含跨接口验证)')
                    if fa.py_info.has_loop_validation:
                        msg_parts.append('(含循环遍历校验)')
                    patterns.append(WeakPattern(
                        code='W003', severity='info',
                        message=''.join(msg_parts),
                        suggestion='YAML+PY 组合断言有效，可考虑统一管理'
                    ))
                else:
                    patterns.append(WeakPattern(
                        code='W003', severity='critical',
                        message='check_json 仅验证 code+msg，未检查业务数据',
                        suggestion='添加 data 层字段验证，或改用 custom_check 做深度断言'
                    ))

        # W004: custom_check 但实际断言很弱
        if tc.check_type == 'custom_check' and isinstance(er, dict):
            python_code = str(er.get('python_code', ''))
            assert_count = len(re.findall(r'\bassert\b', python_code))
            if assert_count <= 1 and 'assert' in python_code:
                if re.search(r'assert.*code.*==\s*0', python_code):
                    if not py_has_extra:
                        patterns.append(WeakPattern(
                            code='W004', severity='warning',
                            message='custom_check 仅断言 code==0，与 check_json 无实质区别',
                            suggestion='增加响应体数据结构和业务字段断言'
                        ))

        # W005: 搜索/列表接口不验证返回数据
        if fa.api_type == 'search' and tc.check_type in ('check_json', 'check_code'):
            if isinstance(er, dict) and set(er.keys()) <= ONLY_CODE_MSG_FIELDS:
                if py_has_extra and (fa.py_info.has_field_validation or fa.py_info.has_loop_validation):
                    pass  # .py 已有字段级验证，不再报 critical
                else:
                    patterns.append(WeakPattern(
                        code='W005', severity='critical',
                        message='搜索/列表接口未验证返回数据内容',
                        suggestion='验证 records/list 字段存在性、结构和内容匹配'
                    ))

        # W006: 分页接口不验证分页参数
        if fa.has_pagination and tc.check_type in ('check_json', 'check_code'):
            has_page_check = False
            if isinstance(er, dict):
                er_str = str(er)
                has_page_check = any(kw in er_str.lower() for kw in ['page', 'total', 'size', 'count'])
            if not has_page_check and not (py_has_extra and fa.py_info.has_field_validation):
                patterns.append(WeakPattern(
                    code='W006', severity='warning',
                    message='分页接口未验证分页相关字段（total/pageSize/records数量）',
                    suggestion='验证返回数据数量是否与 pageSize 一致'
                ))

        # W007: 创建接口不验证返回 ID
        if fa.api_type == 'create' and tc.check_type in ('check_json',):
            if isinstance(er, dict) and 'id' not in str(er).lower():
                if py_has_extra and fa.py_info.has_cross_api_verify:
                    pass  # .py 有跨接口验证（创建后查询），不报
                else:
                    patterns.append(WeakPattern(
                        code='W007', severity='warning',
                        message='创建接口未验证返回的 ID 或创建结果',
                        suggestion='验证返回的 id 字段存在且有效'
                    ))

        # W008: 异常用例但期望 code=200+code=0
        if tc.expected_code == 200 and isinstance(er, dict) and er.get('code') == 0:
            summary_lower = tc.summary.lower()
            if any(kw in summary_lower for kw in ['无效', '异常', '边界', 'invalid', 'error', '不存在']):
                patterns.append(WeakPattern(
                    code='W008', severity='warning',
                    message='异常场景用例仍期望成功响应（code=0）',
                    suggestion='异常场景应验证特定的错误码和错误消息'
                ))

        return patterns

    # ── 辅助方法 ──────────────────────────────────────────

    def _detect_api_type(self, tf: TestFile) -> str:
        """根据接口地址和方法推断接口类型

        优先级：关键词匹配 > 路径模式 > HTTP 方法兜底
        """
        addr = tf.address
        title = tf.title
        combined = addr + ' ' + title

        # 先做驼峰/帕斯卡拆词，再做分隔符切分，避免 createOrder/getUserList 无法命中关键词
        combined = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', combined)
        combined = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', combined)

        # 用分词集合做全词匹配，避免子串误判（如 get 匹配 budget）
        tokens = {
            tok.lower()
            for tok in re.split(r'[\s/\-_.?=&:]+', combined)
            if tok
        }

        # 第一优先级：关键词匹配（最准确）
        if tokens & set(SEARCH_KEYWORDS):
            return 'search'
        if tokens & set(CREATE_KEYWORDS):
            return 'create'
        if tokens & set(UPDATE_KEYWORDS):
            return 'update'
        if tokens & set(DELETE_KEYWORDS):
            return 'delete'
        if tokens & set(DETAIL_KEYWORDS):
            return 'detail'
        if tokens & set(ACTION_KEYWORDS):
            return 'action'

        # 第二优先级：路径模式
        # URL 以 /123 或 /{id} 或 /:id 结尾 → 大概率是详情或单资源操作
        has_id_in_path = bool(_ID_IN_PATH_RE.search(addr.lower()))

        # 第三优先级：HTTP 方法兜底
        if tf.method == 'GET':
            return 'detail' if has_id_in_path else 'search'
        if tf.method == 'POST':
            if has_id_in_path:
                return 'action'
            # POST 无 ID → 看参数中是否有分页字段来区分 search 和 create
            if self._detect_pagination(tf):
                return 'search'
            return 'create'
        if tf.method in ('PUT', 'PATCH'):
            return 'update'
        if tf.method == 'DELETE':
            return 'delete'

        return 'other'

    def _detect_pagination(self, tf: TestFile) -> bool:
        """检测是否为分页接口"""
        for tc in tf.test_cases:
            if isinstance(tc.parameter, dict):
                param_keys = set(str(k).lower() for k in tc.parameter.keys())
                if param_keys & set(PAGINATION_KEYWORDS):
                    return True
        return False
