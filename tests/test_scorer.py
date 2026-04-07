# -*- coding: utf-8 -*-
"""scorer.py 核心评分逻辑测试"""

import pytest
from aag.parser import TestCase, TestFile
from aag.analyzer import CaseAnalysis, FileAnalysis, WeakPattern
from aag.py_parser import PyAssertionInfo
from aag.scorer import AssertionScorer, WEIGHTS


@pytest.fixture
def scorer():
    return AssertionScorer()


# ── 等级边界测试 ──────────────────────────────────────────


class TestGrade:
    def test_grade_a(self, scorer):
        assert scorer._grade(80) == 'A'
        assert scorer._grade(100) == 'A'

    def test_grade_b(self, scorer):
        assert scorer._grade(60) == 'B'
        assert scorer._grade(79.9) == 'B'

    def test_grade_c(self, scorer):
        assert scorer._grade(40) == 'C'
        assert scorer._grade(59.9) == 'C'

    def test_grade_d(self, scorer):
        assert scorer._grade(20) == 'D'
        assert scorer._grade(39.9) == 'D'

    def test_grade_f(self, scorer):
        assert scorer._grade(0) == 'F'
        assert scorer._grade(19.9) == 'F'


# ── 加权评分测试 ──────────────────────────────────────────


class TestCaseScoring:
    def _make_case_analysis(self, check_type_score=0, field_coverage=0,
                            business_logic=0, weak_patterns=None):
        tc = TestCase(summary='test', check_type='check_json', expected_code=200)
        ca = CaseAnalysis(test_case=tc)
        ca.check_type_score = check_type_score
        ca.field_coverage_score = field_coverage
        ca.business_logic_score = business_logic
        ca.weak_patterns = weak_patterns or []
        return ca

    def _make_file_analysis(self):
        tf = TestFile(file_path='/test.yaml', rel_path='test.yaml')
        return FileAnalysis(test_file=tf)

    def test_all_zero_scores(self, scorer):
        ca = self._make_case_analysis(0, 0, 0)
        fa = self._make_file_analysis()
        cs = scorer._score_case(ca, fa)
        # scenario_score for check_json base=40, so total = 40*0.2 = 8
        assert cs.total == 8.0

    def test_all_max_scores(self, scorer):
        ca = self._make_case_analysis(100, 100, 100)
        fa = self._make_file_analysis()
        cs = scorer._score_case(ca, fa)
        # check_type=100*0.2 + field=100*0.3 + biz=100*0.3 + scenario=40*0.2
        # = 20 + 30 + 30 + 8 = 88
        assert cs.total == 88.0

    def test_weak_pattern_counting(self, scorer):
        patterns = [
            WeakPattern(code='W001', severity='critical', message='', suggestion=''),
            WeakPattern(code='W002', severity='warning', message='', suggestion=''),
            WeakPattern(code='W003', severity='critical', message='', suggestion=''),
        ]
        ca = self._make_case_analysis(50, 50, 50, patterns)
        fa = self._make_file_analysis()
        cs = scorer._score_case(ca, fa)
        assert cs.weak_count == 3
        assert cs.critical_count == 2

    def test_weights_sum_to_one(self):
        total = sum(WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9


# ── 场景覆盖评分测试 ──────────────────────────────────────────


class TestScenarioScore:
    def _make(self, check_type, expected_code=200, expected_result=None, has_check_db=False):
        tc = TestCase(
            summary='test', check_type=check_type,
            expected_code=expected_code, expected_result=expected_result,
            has_check_db=has_check_db,
        )
        ca = CaseAnalysis(test_case=tc)
        tf = TestFile(file_path='/test.yaml', rel_path='test.yaml')
        fa = FileAnalysis(test_file=tf)
        return ca, fa

    def test_no_check_base(self, scorer):
        ca, fa = self._make('no_check')
        assert scorer._calc_scenario_score(ca, fa) == 0

    def test_check_code_base(self, scorer):
        ca, fa = self._make('check_code')
        assert scorer._calc_scenario_score(ca, fa) == 20

    def test_check_json_base(self, scorer):
        ca, fa = self._make('check_json')
        assert scorer._calc_scenario_score(ca, fa) == 40

    def test_error_scenario_bonus(self, scorer):
        ca, fa = self._make('check_json', expected_code=400)
        assert scorer._calc_scenario_score(ca, fa) == 65  # 40 + 25

    def test_error_code_bonus(self, scorer):
        ca, fa = self._make('check_json', expected_result={'code': 1001})
        assert scorer._calc_scenario_score(ca, fa) == 65  # 40 + 25

    def test_check_db_bonus(self, scorer):
        ca, fa = self._make('check_json', has_check_db=True)
        assert scorer._calc_scenario_score(ca, fa) == 65  # 40 + 25

    def test_max_cap(self, scorer):
        ca, fa = self._make('custom_check', expected_code=400, has_check_db=True)
        assert scorer._calc_scenario_score(ca, fa) == 100  # 50+25+25=100


# ── 文件级评分测试 ──────────────────────────────────────────


class TestFileScoring:
    def test_file_avg_score(self, scorer):
        tf = TestFile(file_path='/test.yaml', rel_path='test.yaml')
        tc1 = TestCase(summary='case1', check_type='entirely_check', expected_code=200)
        tc2 = TestCase(summary='case2', check_type='no_check', expected_code=200)
        tf.test_cases = [tc1, tc2]

        fa = FileAnalysis(test_file=tf)
        ca1 = CaseAnalysis(test_case=tc1, check_type_score=80, field_coverage_score=90,
                           business_logic_score=0, scenario_score=0)
        ca2 = CaseAnalysis(test_case=tc2, check_type_score=0, field_coverage_score=0,
                           business_logic_score=0, scenario_score=0)
        fa.case_analyses = [ca1, ca2]

        fs = scorer.score_file(fa)
        assert fs.case_count == 2
        assert fs.total > 0
        assert fs.grade in ('A', 'B', 'C', 'D', 'F')

    def test_py_assertions_tracked(self, scorer):
        tf = TestFile(file_path='/test.yaml', rel_path='test.yaml')
        tc = TestCase(summary='case1', check_type='check_json', expected_code=200)
        tf.test_cases = [tc]

        py_info = PyAssertionInfo(assert_count=5, is_template_only=False)
        fa = FileAnalysis(test_file=tf, py_info=py_info)
        ca = CaseAnalysis(test_case=tc, check_type_score=30, field_coverage_score=20)
        fa.case_analyses = [ca]

        fs = scorer.score_file(fa)
        assert fs.has_py_assertions is True
        assert fs.py_assert_count == 5
