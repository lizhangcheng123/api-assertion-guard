# -*- coding: utf-8 -*-
"""analyzer.py 弱断言规则 W001-W008 测试"""

import pytest
from aag.parser import TestCase, TestFile
from aag.analyzer import AssertionAnalyzer, FileAnalysis, CaseAnalysis, ONLY_CODE_MSG_FIELDS
from aag.py_parser import PyAssertionInfo


@pytest.fixture
def analyzer():
    return AssertionAnalyzer()


def _make_tf(**kwargs):
    defaults = dict(file_path='/test.yaml', rel_path='test.yaml', title='', method='POST', address='/api/test')
    defaults.update(kwargs)
    return TestFile(**defaults)


def _make_fa(tf=None, api_type='other', has_pagination=False, py_info=None):
    tf = tf or _make_tf()
    return FileAnalysis(test_file=tf, api_type=api_type, has_pagination=has_pagination, py_info=py_info)


# ── W001: 无断言 ──────────────────────────────────────────


class TestW001:
    def test_no_check_is_critical(self, analyzer):
        tc = TestCase(summary='test', check_type='no_check')
        fa = _make_fa()
        patterns = analyzer._detect_weak_patterns(tc, _make_tf(), fa)
        assert len(patterns) == 1
        assert patterns[0].code == 'W001'
        assert patterns[0].severity == 'critical'

    def test_no_check_with_py_is_warning(self, analyzer):
        tc = TestCase(summary='test', check_type='no_check')
        py_info = PyAssertionInfo(assert_count=3, is_template_only=False)
        fa = _make_fa(py_info=py_info)
        patterns = analyzer._detect_weak_patterns(tc, _make_tf(), fa)
        assert len(patterns) == 1
        assert patterns[0].code == 'W001'
        assert patterns[0].severity == 'warning'


# ── W002: 只检查状态码 ──────────────────────────────────────────


class TestW002:
    def test_check_code_only_is_critical(self, analyzer):
        tc = TestCase(summary='test', check_type='check_code')
        fa = _make_fa()
        patterns = analyzer._detect_weak_patterns(tc, _make_tf(), fa)
        assert len(patterns) == 1
        assert patterns[0].code == 'W002'
        assert patterns[0].severity == 'critical'

    def test_check_code_with_py_is_info(self, analyzer):
        tc = TestCase(summary='test', check_type='check_code')
        py_info = PyAssertionInfo(assert_count=3, is_template_only=False)
        fa = _make_fa(py_info=py_info)
        patterns = analyzer._detect_weak_patterns(tc, _make_tf(), fa)
        assert len(patterns) == 1
        assert patterns[0].code == 'W002'
        assert patterns[0].severity == 'info'


# ── W003: check_json 只验证 code+msg ──────────────────────────────────


class TestW003:
    def test_json_code_msg_only_is_critical(self, analyzer):
        tc = TestCase(summary='test', check_type='check_json', expected_result={'code': 0, 'msg': 'ok'})
        fa = _make_fa()
        patterns = analyzer._detect_weak_patterns(tc, _make_tf(), fa)
        codes = [p.code for p in patterns]
        assert 'W003' in codes
        w003 = next(p for p in patterns if p.code == 'W003')
        assert w003.severity == 'critical'

    def test_json_with_extra_fields_no_w003(self, analyzer):
        tc = TestCase(summary='test', check_type='check_json',
                      expected_result={'code': 0, 'msg': 'ok', 'data': {'id': 1}})
        fa = _make_fa()
        patterns = analyzer._detect_weak_patterns(tc, _make_tf(), fa)
        codes = [p.code for p in patterns]
        assert 'W003' not in codes


# ── W005: 搜索接口不验证返回数据 ──────────────────────────────────


class TestW005:
    def test_search_no_data_check(self, analyzer):
        tc = TestCase(summary='test', check_type='check_json', expected_result={'code': 0, 'msg': 'ok'})
        fa = _make_fa(api_type='search')
        patterns = analyzer._detect_weak_patterns(tc, _make_tf(), fa)
        codes = [p.code for p in patterns]
        assert 'W005' in codes

    def test_search_with_data_fields_no_w005(self, analyzer):
        tc = TestCase(summary='test', check_type='check_json',
                      expected_result={'code': 0, 'msg': 'ok', 'data': {'records': []}})
        fa = _make_fa(api_type='search')
        patterns = analyzer._detect_weak_patterns(tc, _make_tf(), fa)
        codes = [p.code for p in patterns]
        assert 'W005' not in codes


# ── W008: 异常用例期望成功 ──────────────────────────────────


class TestW008:
    def test_error_case_expects_success(self, analyzer):
        tc = TestCase(summary='无效参数测试', check_type='check_json',
                      expected_code=200, expected_result={'code': 0, 'msg': 'ok'})
        fa = _make_fa()
        patterns = analyzer._detect_weak_patterns(tc, _make_tf(), fa)
        codes = [p.code for p in patterns]
        assert 'W008' in codes

    def test_normal_case_no_w008(self, analyzer):
        tc = TestCase(summary='正常查询', check_type='check_json',
                      expected_code=200, expected_result={'code': 0, 'msg': 'ok'})
        fa = _make_fa()
        patterns = analyzer._detect_weak_patterns(tc, _make_tf(), fa)
        codes = [p.code for p in patterns]
        assert 'W008' not in codes


# ── 评分方法测试 ──────────────────────────────────────────


class TestCheckTypeScoring:
    def test_no_check_score(self, analyzer):
        tc = TestCase(check_type='no_check')
        assert analyzer._score_check_type(tc) == 0

    def test_check_code_score(self, analyzer):
        tc = TestCase(check_type='check_code')
        assert analyzer._score_check_type(tc) == 20

    def test_check_json_code_msg_only(self, analyzer):
        tc = TestCase(check_type='check_json', expected_result={'code': 0, 'msg': 'ok'})
        score = analyzer._score_check_type(tc)
        assert score == 30

    def test_check_json_many_fields(self, analyzer):
        tc = TestCase(check_type='check_json', expected_result={
            'code': 0, 'msg': 'ok', 'data': {}, 'total': 10,
            'f1': 1, 'f2': 2, 'f3': 3, 'f4': 4, 'f5': 5,
        })
        score = analyzer._score_check_type(tc)
        assert score == 70

    def test_entirely_check_score(self, analyzer):
        tc = TestCase(check_type='entirely_check')
        assert analyzer._score_check_type(tc) == 80


class TestFieldCoverage:
    def test_no_check(self, analyzer):
        tc = TestCase(check_type='no_check')
        assert analyzer._score_field_coverage(tc) == 0

    def test_entirely_check(self, analyzer):
        tc = TestCase(check_type='entirely_check', expected_result={'code': 0, 'data': {}})
        assert analyzer._score_field_coverage(tc) == 90


class TestOnlyCodeMsgFields:
    def test_code_msg_set(self):
        assert {'code', 'msg'} <= ONLY_CODE_MSG_FIELDS
        assert {'code', 'message'} <= ONLY_CODE_MSG_FIELDS

    def test_extra_field_not_subset(self):
        assert not {'code', 'msg', 'data'} <= ONLY_CODE_MSG_FIELDS
