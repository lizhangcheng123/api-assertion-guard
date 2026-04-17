# -*- coding: utf-8 -*-
"""升级模板 - 各接口类型的 check_body 升级模板"""

from ruamel.yaml.scalarstring import LiteralScalarString


def build_level1_check_body(expected_code: int = 200) -> dict:
    """Level 1: check_code → check_json"""
    return {
        'check_type': 'check_json',
        'expected_code': expected_code,
        'expected_result': {
            'code': 0,
            'msg': 'SUCCESS',
        }
    }


def build_search_check_body(has_pagination: bool = False,
                            page_size: int = None,
                            expected_code: int = 200) -> dict:
    """搜索/列表接口: 验证 data 结构 + records 类型"""
    lines = [
        'assert isinstance(data, dict), f"响应非dict: {type(data)}"',
        'assert data.get("code") == 0, f"业务码错误: {data.get(\'code\')}, msg: {data.get(\'msg\')}"',
        'resp_data = data.get("data")',
        'assert resp_data is not None, "data 字段不应为空"',
        'if isinstance(resp_data, dict):',
        '    records = resp_data.get("records")',
        '    if records is not None:',
        '        assert isinstance(records, list), f"records 应为列表, 实际: {type(records)}"',
    ]
    if has_pagination and page_size:
        lines.append(
            f'        assert len(records) <= {page_size}, '
            f'f"返回数量 {{len(records)}} 超过 pageSize={page_size}"'
        )
    return {
        'check_type': 'custom_check',
        'expected_code': expected_code,
        'expected_result': {
            'python_code': LiteralScalarString('\n'.join(lines) + '\n'),
        }
    }


def build_create_check_body(expected_code: int = 200) -> dict:
    """创建接口: 验证 data 存在"""
    python_code = (
        'assert isinstance(data, dict), f"响应非dict: {type(data)}"\n'
        'assert data.get("code") == 0, f"业务码错误: {data.get(\'code\')}, msg: {data.get(\'msg\')}"\n'
        'resp_data = data.get("data")\n'
        'assert resp_data is not None, "data 字段不应为空"\n'
    )
    return {
        'check_type': 'custom_check',
        'expected_code': expected_code,
        'expected_result': {
            'python_code': LiteralScalarString(python_code),
        }
    }


def build_detail_check_body(expected_code: int = 200) -> dict:
    """详情接口: 验证 data 存在，且不是 records 列表分页形态"""
    python_code = (
        'assert isinstance(data, dict), f"响应非dict: {type(data)}"\n'
        'assert data.get("code") == 0, f"业务码错误: {data.get(\'code\')}, msg: {data.get(\'msg\')}"\n'
        'resp_data = data.get("data")\n'
        'assert resp_data is not None, "data 字段不应为空"\n'
        'assert isinstance(resp_data, (dict, list)), f"data 类型异常: {type(resp_data)}"\n'
        'if isinstance(resp_data, dict):\n'
        '    assert "records" not in resp_data, "详情接口不应返回 records 分页结构"\n'
    )
    return {
        'check_type': 'custom_check',
        'expected_code': expected_code,
        'expected_result': {
            'python_code': LiteralScalarString(python_code),
        }
    }


def build_safe_check_body(expected_code: int = 200) -> dict:
    """删除/更新/action 接口: 不断言 data 存在（部分接口不返回 data）"""
    python_code = (
        'assert isinstance(data, dict), f"响应非dict: {type(data)}"\n'
        'assert data.get("code") == 0, f"业务码错误: {data.get(\'code\')}, msg: {data.get(\'msg\')}"\n'
    )
    return {
        'check_type': 'custom_check',
        'expected_code': expected_code,
        'expected_result': {
            'python_code': LiteralScalarString(python_code),
        }
    }


def build_generic_check_body(expected_code: int = 200) -> dict:
    """通用接口: 防御式检查 data"""
    python_code = (
        'assert isinstance(data, dict), f"响应非dict: {type(data)}"\n'
        'assert data.get("code") == 0, f"业务码错误: {data.get(\'code\')}, msg: {data.get(\'msg\')}"\n'
        'if data.get("data") is not None:\n'
        '    assert isinstance(data["data"], (dict, list)), f"data 类型异常: {type(data[\'data\'])}"\n'
    )
    return {
        'check_type': 'custom_check',
        'expected_code': expected_code,
        'expected_result': {
            'python_code': LiteralScalarString(python_code),
        }
    }


def build_captured_check_body(capture_info: dict, expected_code: int = 200) -> dict:
    """基于 capture 抓取的真实响应结构生成精确断言

    capture_info 结构（来自 capture_plugin 的合并结果）：
        data_exists: bool
        data_type: str ('dict' / 'list' / None)
        data_keys: list[str]
        has_records: bool
        record_sample_keys: list[str]
    """
    lines = [
        'assert isinstance(data, dict), f"响应非dict: {type(data)}"',
        'assert data.get("code") == 0, f"业务码错误: {data.get(\'code\')}, msg: {data.get(\'msg\')}"',
    ]

    if not capture_info.get('data_exists'):
        # 真实响应中没有 data 字段，不做 data 断言
        pass
    elif capture_info.get('data_type') == 'dict':
        lines.append('resp_data = data.get("data")')
        lines.append('assert resp_data is not None, "data 字段不应为空"')
        lines.append('assert isinstance(resp_data, dict), f"data 应为dict, 实际: {type(resp_data)}"')

        data_keys = capture_info.get('data_keys', [])
        if data_keys:
            # 验证关键字段存在（取前 5 个，避免断言过长）
            check_keys = data_keys[:5]
            for key in check_keys:
                lines.append(f'assert "{key}" in resp_data, "data 中缺少 {key} 字段"')

        if capture_info.get('has_records'):
            lines.append('records = resp_data.get("records")')
            lines.append('assert isinstance(records, list), f"records 应为列表, 实际: {type(records)}"')

            sample_keys = capture_info.get('record_sample_keys', [])
            if sample_keys:
                # 验证记录的关键字段（取前 5 个）
                check_keys = sample_keys[:5]
                lines.append('if len(records) > 0:')
                lines.append('    first = records[0]')
                for key in check_keys:
                    lines.append(f'    assert "{key}" in first, "记录缺少 {key} 字段"')

    elif capture_info.get('data_type') == 'list':
        lines.append('resp_data = data.get("data")')
        lines.append('assert resp_data is not None, "data 字段不应为空"')
        lines.append('assert isinstance(resp_data, list), f"data 应为list, 实际: {type(resp_data)}"')

        sample_keys = capture_info.get('record_sample_keys', [])
        if sample_keys:
            check_keys = sample_keys[:5]
            lines.append('if len(resp_data) > 0:')
            lines.append('    first = resp_data[0]')
            for key in check_keys:
                lines.append(f'    assert "{key}" in first, "记录缺少 {key} 字段"')

    return {
        'check_type': 'custom_check',
        'expected_code': expected_code,
        'expected_result': {
            'python_code': LiteralScalarString('\n'.join(lines) + '\n'),
        }
    }
