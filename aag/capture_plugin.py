# -*- coding: utf-8 -*-
"""
AAG Capture Plugin — 独立 pytest 插件，零侵入抓取接口响应结构。

使用方式（在 apitesting-main 目录下）：
    pytest -p aag.capture_plugin --aag-capture /path/to/responses.json [其他pytest参数]

确保 api-assertion-guard 在 PYTHONPATH 中：
    PYTHONPATH=/Users/lizhangcheng/Documents/api-assertion-guard pytest -p aag.capture_plugin --aag-capture responses.json

原理：
    通过 monkeypatch 拦截 check_result() 函数，在原函数执行前
    记录 (code, data) 的结构信息，然后正常放行。
    不影响测试执行和结果。

输出：
    JSON 文件，每条记录包含 YAML 文件路径、用例 summary、
    HTTP 状态码、响应体的 key 结构和类型信息。
"""

import json
import os
import sys
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# 全局存储
_captures = []
_output_path = None
_original_check_result = None
_current_yaml_path = None  # 当前正在执行的 YAML 文件路径


def pytest_addoption(parser):
    """注册 --aag-capture 命令行参数"""
    parser.addoption(
        '--aag-capture',
        default=None,
        help='AAG: 抓取接口响应结构并保存到指定 JSON 文件路径',
    )


def pytest_configure(config):
    """插件初始化：如果指定了 --aag-capture，激活拦截"""
    global _output_path
    _output_path = config.getoption('--aag-capture', default=None)

    if not _output_path:
        return

    # Monkeypatch check_result
    try:
        from comm.unit import checkResult
        global _original_check_result
        _original_check_result = checkResult.check_result
        checkResult.check_result = _hooked_check_result
        print(f"\n🔍 AAG Capture 已激活，响应结构将保存到: {_output_path}")
    except ImportError:
        print("\n⚠️  AAG Capture: 无法导入 comm.unit.checkResult，插件未激活")


def pytest_runtest_setup(item):
    """每个测试用例开始前，推算对应的 YAML 文件路径"""
    global _current_yaml_path

    if not _output_path:
        return

    # item.fspath 是 .py 文件的绝对路径
    py_path = str(item.fspath).replace('\\', '/')
    # 规则：/testcase/xxx.py → /page/xxx.yaml
    yaml_path = py_path.replace('/testcase/', '/page/').replace('.py', '.yaml')
    _current_yaml_path = yaml_path


def pytest_unconfigure(config):
    """测试结束：恢复原函数 + 写入 JSON"""
    global _original_check_result

    if not _output_path:
        return

    # 恢复原函数
    if _original_check_result:
        try:
            from comm.unit import checkResult
            checkResult.check_result = _original_check_result
        except ImportError:
            pass

    # 去重合并：同一个 YAML 文件的多个用例合并为一条
    merged = _merge_captures(_captures)

    # 写入
    output = {
        'captured_at': datetime.now().isoformat(),
        'total_records': len(_captures),
        'total_files': len(merged),
        'files': merged,
    }
    out_dir = os.path.dirname(os.path.abspath(_output_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(_output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n✅ AAG Capture: 已保存 {len(_captures)} 条记录（{len(merged)} 个文件）到 {_output_path}")


def _hooked_check_result(case_data, code, data):
    """拦截 check_result，记录响应结构后放行原函数"""
    try:
        record = _extract_structure(case_data, code, data)
        _captures.append(record)
    except Exception as e:
        logger.debug("AAG Capture: 抓取失败 %s", e)

    # 调用原函数，不影响测试
    return _original_check_result(case_data, code, data)


def _extract_structure(case_data, code, data):
    """从响应中提取结构信息（只记录 key 和类型，不记录具体值）"""
    record = {
        'yaml_path': _current_yaml_path or '',
        'summary': case_data.get('summary', ''),
        'check_type': case_data.get('check_body', {}).get('check_type', ''),
        'http_code': code,
        'response_type': type(data).__name__,
        'data_exists': False,
        'data_type': None,
        'data_keys': [],
        'has_records': False,
        'records_count': 0,
        'record_sample_keys': [],
    }

    if not isinstance(data, dict):
        return record

    record['response_keys'] = list(data.keys())
    record['code_value'] = data.get('code')
    record['msg_value'] = data.get('msg', '')

    # data 层结构
    data_field = data.get('data')
    if data_field is None:
        return record

    record['data_exists'] = True
    record['data_type'] = type(data_field).__name__

    if isinstance(data_field, dict):
        record['data_keys'] = list(data_field.keys())
        # records 子结构
        records = data_field.get('records')
        if isinstance(records, list):
            record['has_records'] = True
            record['records_count'] = len(records)
            if records and isinstance(records[0], dict):
                record['record_sample_keys'] = list(records[0].keys())
    elif isinstance(data_field, list):
        record['data_type'] = 'list'
        record['data_list_length'] = len(data_field)
        if data_field and isinstance(data_field[0], dict):
            record['record_sample_keys'] = list(data_field[0].keys())

    return record


def _merge_captures(captures):
    """将同一 YAML 文件的多条记录合并"""
    file_map = {}
    for record in captures:
        yaml_path = record.get('yaml_path', '')
        if yaml_path not in file_map:
            file_map[yaml_path] = {
                'yaml_path': yaml_path,
                'cases': [],
                # 文件级汇总信息：取第一个成功响应的结构
                'data_exists': False,
                'data_type': None,
                'data_keys': [],
                'has_records': False,
                'record_sample_keys': [],
            }

        entry = file_map[yaml_path]
        entry['cases'].append({
            'summary': record.get('summary', ''),
            'check_type': record.get('check_type', ''),
            'http_code': record.get('http_code'),
            'code_value': record.get('code_value'),
            'data_exists': record.get('data_exists', False),
        })

        # 用第一个有 data 的响应填充文件级结构
        if record.get('data_exists') and not entry['data_exists']:
            entry['data_exists'] = True
            entry['data_type'] = record.get('data_type')
            entry['data_keys'] = record.get('data_keys', [])
            entry['has_records'] = record.get('has_records', False)
            entry['record_sample_keys'] = record.get('record_sample_keys', [])

    return list(file_map.values())
