# -*- coding: utf-8 -*-
"""YAML 测试文件解析器"""

import os
from dataclasses import dataclass, field
from typing import List, Optional
from ruamel.yaml import YAML


@dataclass
class TestCase:
    """单个测试用例"""
    summary: str = ""
    describe: str = ""
    tags: List[str] = field(default_factory=list)
    parameter: dict = field(default_factory=dict)
    check_type: str = ""
    expected_code: int = 200
    expected_result: object = None
    has_check_db: bool = False


@dataclass
class TestFile:
    """一个 YAML 测试文件"""
    file_path: str = ""
    rel_path: str = ""  # 相对路径，用于展示
    title: str = ""
    method: str = ""
    address: str = ""
    has_premise: bool = False
    has_cookies: bool = False
    test_cases: List[TestCase] = field(default_factory=list)


class YamlTestParser:
    """解析 YAML 测试文件"""

    def __init__(self):
        self.yaml = YAML()
        self.yaml.preserve_quotes = True

    def parse_directory(self, path: str) -> List[TestFile]:
        """递归扫描目录下所有 YAML 文件"""
        test_files = []
        for root, _, files in os.walk(path):
            for f in sorted(files):
                if f.endswith(('.yaml', '.yml')) and not f.startswith(('TEMPLATE', '(unavailable)')):
                    full_path = os.path.join(root, f)
                    try:
                        tf = self.parse_file(full_path, base_path=path)
                        if tf and tf.test_cases:
                            test_files.append(tf)
                    except Exception as e:
                        print(f"  跳过解析失败的文件: {full_path} ({e})")
        return test_files

    def parse_file(self, file_path: str, base_path: str = "") -> Optional[TestFile]:
        """解析单个 YAML 文件"""
        with open(file_path, 'r', encoding='utf-8') as f:
            data = self.yaml.load(f)

        if not data or 'test_info' not in data or 'test_case' not in data:
            return None

        info = data['test_info']
        cases_raw = data['test_case']
        if not isinstance(cases_raw, list):
            return None

        tf = TestFile(
            file_path=file_path,
            rel_path=os.path.relpath(file_path, base_path) if base_path else file_path,
            title=info.get('title', ''),
            method=str(info.get('method', '')).upper(),
            address=info.get('address', ''),
            has_premise=bool(info.get('premise')),
            has_cookies=bool(info.get('cookies')),
        )

        for case in cases_raw:
            if not isinstance(case, dict):
                continue
            check_body = case.get('check_body', {})
            tc = TestCase(
                summary=case.get('summary', ''),
                describe=case.get('describe', ''),
                tags=list(case.get('tags', [])),
                parameter=case.get('parameter', {}),
                check_type=check_body.get('check_type', 'no_check'),
                expected_code=check_body.get('expected_code', 200),
                expected_result=check_body.get('expected_result'),
                has_check_db='check_db' in case,
            )
            tf.test_cases.append(tc)

        return tf
