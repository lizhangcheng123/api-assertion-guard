# -*- coding: utf-8 -*-
"""upgrader.py 升级引擎单元测试"""

import pytest
from aag.parser import TestCase, TestFile
from aag.analyzer import FileAnalysis
from aag.upgrader import UpgradeEngine, SKIP_CHECK_TYPES
from aag.upgrade_templates import (
    build_level1_check_body,
    build_search_check_body,
    build_create_check_body,
    build_safe_check_body,
    build_generic_check_body,
)


@pytest.fixture
def engine():
    return UpgradeEngine(level=2, dry_run=True)


def _make_tf(**kwargs):
    defaults = dict(file_path='/test.yaml', rel_path='test.yaml', title='', method='POST', address='/api/test')
    defaults.update(kwargs)
    return TestFile(**defaults)


def _make_fa(tf=None, api_type='other', has_pagination=False):
    tf = tf or _make_tf()
    return FileAnalysis(test_file=tf, api_type=api_type, has_pagination=has_pagination)


# ── 跳过规则测试 ──────────────────────────────────────────


class TestSkipRules:
    def test_skip_custom_check(self, engine):
        tc = TestCase(summary='test', check_type='custom_check')
        d = engine._decide(tc, _make_fa(), 0)
        assert d.skip_reason is not None
        assert 'custom_check' in d.skip_reason

    def test_skip_entirely_check(self, engine):
        tc = TestCase(summary='test', check_type='entirely_check')
        d = engine._decide(tc, _make_fa(), 0)
        assert d.skip_reason is not None

    def test_skip_no_check(self, engine):
        tc = TestCase(summary='test', check_type='no_check')
        d = engine._decide(tc, _make_fa(), 0)
        assert d.skip_reason is not None

    def test_skip_error_scenario(self, engine):
        tc = TestCase(summary='test', check_type='check_json',
                      expected_result={'code': 10043, 'msg': 'ERROR'})
        d = engine._decide(tc, _make_fa(), 0)
        assert d.skip_reason is not None
        assert '错误场景' in d.skip_reason

    def test_skip_has_data_fields(self, engine):
        tc = TestCase(summary='test', check_type='check_json',
                      expected_result={'code': 0, 'msg': 'SUCCESS', 'data': {'id': 1}})
        d = engine._decide(tc, _make_fa(), 0)
        assert d.skip_reason is not None
        assert '数据层' in d.skip_reason


# ── Level 1 决策测试 ──────────────────────────────────────────


class TestLevel1:
    def test_check_code_to_check_json(self, engine):
        tc = TestCase(summary='test', check_type='check_code', expected_code=200)
        d = engine._decide(tc, _make_fa(), 0)
        assert d.skip_reason is None
        assert d.level == 1
        assert d.target_check_type == 'check_json'
        assert d.new_check_body['check_type'] == 'check_json'
        assert d.new_check_body['expected_result']['code'] == 0

    def test_level1_only_engine(self):
        engine = UpgradeEngine(level=1, dry_run=True)
        tc = TestCase(summary='test', check_type='check_json',
                      expected_result={'code': 0, 'msg': 'SUCCESS'})
        d = engine._decide(tc, _make_fa(), 0)
        # level=1 引擎不升级 check_json
        assert d.skip_reason is not None


# ── Level 2 决策测试 ──────────────────────────────────────────


class TestLevel2:
    def test_weak_json_to_custom_check(self, engine):
        tc = TestCase(summary='test', check_type='check_json',
                      expected_result={'code': 0, 'msg': 'SUCCESS'})
        d = engine._decide(tc, _make_fa(), 0)
        assert d.skip_reason is None
        assert d.level == 2
        assert d.target_check_type == 'custom_check'
        assert 'python_code' in d.new_check_body['expected_result']

    def test_empty_expected_result(self, engine):
        tc = TestCase(summary='test', check_type='check_json',
                      expected_result={})
        d = engine._decide(tc, _make_fa(), 0)
        assert d.skip_reason is None
        assert d.level == 2

    def test_none_expected_result(self, engine):
        tc = TestCase(summary='test', check_type='check_json',
                      expected_result=None)
        d = engine._decide(tc, _make_fa(), 0)
        assert d.skip_reason is None
        assert d.level == 2

    def test_search_api_template(self, engine):
        tc = TestCase(summary='test', check_type='check_json',
                      expected_result={'code': 0, 'msg': 'SUCCESS'})
        fa = _make_fa(api_type='search')
        d = engine._decide(tc, fa, 0)
        code = d.new_check_body['expected_result']['python_code']
        assert 'records' in code

    def test_create_api_template(self, engine):
        tc = TestCase(summary='test', check_type='check_json',
                      expected_result={'code': 0, 'msg': 'SUCCESS'})
        fa = _make_fa(api_type='create')
        d = engine._decide(tc, fa, 0)
        code = d.new_check_body['expected_result']['python_code']
        assert 'resp_data' in code
        assert 'not None' in code

    def test_delete_api_template(self, engine):
        tc = TestCase(summary='test', check_type='check_json',
                      expected_result={'code': 0, 'msg': 'SUCCESS'})
        fa = _make_fa(api_type='delete')
        d = engine._decide(tc, fa, 0)
        code = d.new_check_body['expected_result']['python_code']
        # 删除接口不断言 data 存在
        assert 'resp_data' not in code


# ── 模板函数测试 ──────────────────────────────────────────


class TestTemplates:
    def test_level1_template(self):
        body = build_level1_check_body(200)
        assert body['check_type'] == 'check_json'
        assert body['expected_result']['code'] == 0
        assert body['expected_result']['msg'] == 'SUCCESS'

    def test_search_with_pagination(self):
        body = build_search_check_body(has_pagination=True, page_size=20)
        code = str(body['expected_result']['python_code'])
        assert 'pageSize=20' in code

    def test_search_without_pagination(self):
        body = build_search_check_body(has_pagination=False)
        code = str(body['expected_result']['python_code'])
        assert 'pageSize' not in code

    def test_safe_template_no_data_assert(self):
        body = build_safe_check_body()
        code = str(body['expected_result']['python_code'])
        assert 'resp_data' not in code
        assert 'isinstance(data, dict)' in code

    def test_generic_template_defensive(self):
        body = build_generic_check_body()
        code = str(body['expected_result']['python_code'])
        assert 'if data.get("data") is not None' in code
