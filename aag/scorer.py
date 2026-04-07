# -*- coding: utf-8 -*-
"""评分器 - 综合评分与统计"""

from dataclasses import dataclass, field
from typing import List, Dict
from aag.analyzer import FileAnalysis, CaseAnalysis


# 权重配置
WEIGHTS = {
    'check_type': 0.20,      # 断言类型强度
    'field_coverage': 0.30,  # 字段覆盖率
    'business_logic': 0.30,  # 业务逻辑验证
    'scenario': 0.20,        # 场景覆盖
}


@dataclass
class CaseScore:
    """单个用例评分"""
    summary: str = ""
    total: float = 0.0
    check_type: int = 0
    field_coverage: int = 0
    business_logic: int = 0
    scenario: int = 0
    weak_count: int = 0
    critical_count: int = 0


@dataclass
class FileScore:
    """文件级评分"""
    rel_path: str = ""
    file_path: str = ""
    api_type: str = ""
    method: str = ""
    address: str = ""
    total: float = 0.0
    case_count: int = 0
    case_scores: List[CaseScore] = field(default_factory=list)
    weak_count: int = 0
    critical_count: int = 0
    grade: str = ""  # A/B/C/D/F
    has_py_assertions: bool = False  # .py 文件是否有额外断言
    py_assert_count: int = 0  # .py 中 assert 数量


@dataclass
class ProjectScore:
    """项目级评分"""
    total_files: int = 0
    total_cases: int = 0
    avg_score: float = 0.0
    grade_dist: Dict[str, int] = field(default_factory=dict)
    type_dist: Dict[str, int] = field(default_factory=dict)
    check_type_dist: Dict[str, int] = field(default_factory=dict)
    file_scores: List[FileScore] = field(default_factory=list)
    worst_files: List[FileScore] = field(default_factory=list)
    best_files: List[FileScore] = field(default_factory=list)
    total_weak: int = 0
    total_critical: int = 0
    files_with_py: int = 0  # 有 .py 额外断言的文件数


class AssertionScorer:
    """评分器"""

    def score_file(self, fa: FileAnalysis) -> FileScore:
        """对文件打分"""
        fs = FileScore(
            rel_path=fa.test_file.rel_path,
            file_path=fa.test_file.file_path,
            api_type=fa.api_type,
            method=fa.test_file.method,
            address=fa.test_file.address,
            case_count=len(fa.case_analyses),
        )

        # 记录 .py 文件断言信息
        if fa.py_info and not fa.py_info.is_template_only:
            fs.has_py_assertions = True
            fs.py_assert_count = fa.py_info.assert_count

        for ca in fa.case_analyses:
            cs = self._score_case(ca, fa)
            fs.case_scores.append(cs)
            fs.weak_count += cs.weak_count
            fs.critical_count += cs.critical_count

        # 文件总分 = 所有用例平均分
        if fs.case_scores:
            fs.total = round(sum(cs.total for cs in fs.case_scores) / len(fs.case_scores), 1)

        fs.grade = self._grade(fs.total)
        return fs

    def score_project(self, file_analyses: List[FileAnalysis]) -> ProjectScore:
        """对项目整体打分"""
        ps = ProjectScore()
        ps.grade_dist = {'A': 0, 'B': 0, 'C': 0, 'D': 0, 'F': 0}
        ps.type_dist = {}
        ps.check_type_dist = {}

        for fa in file_analyses:
            fs = self.score_file(fa)
            ps.file_scores.append(fs)

            # 统计
            ps.total_files += 1
            ps.total_cases += fs.case_count
            ps.grade_dist[fs.grade] = ps.grade_dist.get(fs.grade, 0) + 1
            ps.type_dist[fa.api_type] = ps.type_dist.get(fa.api_type, 0) + 1
            ps.total_weak += fs.weak_count
            ps.total_critical += fs.critical_count

            if fs.has_py_assertions:
                ps.files_with_py += 1

            # 统计 check_type 分布
            for ca in fa.case_analyses:
                ct = ca.test_case.check_type
                ps.check_type_dist[ct] = ps.check_type_dist.get(ct, 0) + 1

        # 平均分
        if ps.file_scores:
            ps.avg_score = round(sum(fs.total for fs in ps.file_scores) / len(ps.file_scores), 1)

        # 排序
        sorted_scores = sorted(ps.file_scores, key=lambda x: x.total)
        ps.worst_files = sorted_scores[:10]
        ps.best_files = sorted_scores[-5:][::-1]

        return ps

    def _score_case(self, ca: CaseAnalysis, fa: FileAnalysis) -> CaseScore:
        """计算单个用例的加权总分"""
        # 场景覆盖分 - 文件级维度，需要单独计算
        scenario_score = self._calc_scenario_score(ca, fa)

        total = (
            ca.check_type_score * WEIGHTS['check_type']
            + ca.field_coverage_score * WEIGHTS['field_coverage']
            + ca.business_logic_score * WEIGHTS['business_logic']
            + scenario_score * WEIGHTS['scenario']
        )

        cs = CaseScore(
            summary=ca.test_case.summary,
            total=round(total, 1),
            check_type=ca.check_type_score,
            field_coverage=ca.field_coverage_score,
            business_logic=ca.business_logic_score,
            scenario=scenario_score,
            weak_count=len(ca.weak_patterns),
            critical_count=sum(1 for wp in ca.weak_patterns if wp.severity == 'critical'),
        )
        return cs

    def _calc_scenario_score(self, ca: CaseAnalysis, fa: FileAnalysis) -> int:
        """计算场景覆盖分，基础分与断言类型挂钩"""
        tc = ca.test_case

        # 基础分根据断言类型动态给予
        base_scores = {
            'no_check': 0,
            'check_code': 20,
            'check_json': 40,
            'regular_check': 40,
            'entirely_check': 50,
            'custom_check': 50,
        }
        score = base_scores.get(tc.check_type, 30)

        # 异常场景：期望非 200 或非 code=0
        if tc.expected_code != 200:
            score += 25
        elif isinstance(tc.expected_result, dict) and tc.expected_result.get('code', 0) != 0:
            score += 25

        # 有数据库校验
        if tc.has_check_db:
            score += 25

        return min(score, 100)

    def _grade(self, score: float) -> str:
        if score >= 80:
            return 'A'
        if score >= 60:
            return 'B'
        if score >= 40:
            return 'C'
        if score >= 20:
            return 'D'
        return 'F'
