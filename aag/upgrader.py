# -*- coding: utf-8 -*-
"""升级引擎 - 批量升级 YAML 断言"""

import io
import os
import re
import json
import shutil
import logging
import datetime
from dataclasses import dataclass, field
from typing import List, Optional, Dict

from ruamel.yaml import YAML

from aag.parser import YamlTestParser, TestFile, TestCase
from aag.analyzer import AssertionAnalyzer, FileAnalysis, ONLY_CODE_MSG_FIELDS
from aag.scorer import AssertionScorer
from aag.upgrade_templates import (
    build_level1_check_body,
    build_search_check_body,
    build_create_check_body,
    build_detail_check_body,
    build_safe_check_body,
    build_generic_check_body,
    build_captured_check_body,
)

logger = logging.getLogger(__name__)

# 不需要升级的 check_type
SKIP_CHECK_TYPES = frozenset({'custom_check', 'entirely_check', 'regular_check', 'no_check'})


@dataclass
class UpgradeDecision:
    """单个用例的升级决策"""
    case_index: int
    summary: str
    original_check_type: str
    target_check_type: str
    level: int
    risk: str  # low / medium
    new_check_body: Optional[dict] = None
    skip_reason: Optional[str] = None


@dataclass
class FileUpgradeResult:
    """单个文件的升级结果"""
    file_path: str
    rel_path: str
    api_type: str
    decisions: List[UpgradeDecision] = field(default_factory=list)
    upgraded_count: int = 0
    skipped_count: int = 0
    score_before: float = 0.0
    backup_path: Optional[str] = None


@dataclass
class UpgradeSummary:
    """整体升级摘要"""
    total_files_scanned: int = 0
    files_upgraded: int = 0
    cases_upgraded: int = 0
    cases_skipped: int = 0
    avg_score_before: float = 0.0
    results: List[FileUpgradeResult] = field(default_factory=list)


class UpgradeEngine:
    """升级引擎"""

    def __init__(self, level: int = 2, dry_run: bool = False, no_backup: bool = False,
                 capture_file: str = None):
        self.level = level
        self.dry_run = dry_run
        self.no_backup = no_backup
        self.yaml = YAML()
        self.yaml.preserve_quotes = True
        self.yaml.width = 4096  # 防止自动折行
        self.parser = YamlTestParser()
        self.analyzer = AssertionAnalyzer()
        self.scorer = AssertionScorer()
        # 加载 capture 数据
        self.capture_map: Dict[str, dict] = {}
        if capture_file:
            self.capture_map = self._load_capture(capture_file)

    def upgrade_directory(self, path: str) -> UpgradeSummary:
        """升级整个目录"""
        summary = UpgradeSummary()

        # 1. 解析所有文件
        test_files = self.parser.parse_directory(path)
        summary.total_files_scanned = len(test_files)

        # 2. 分析评分
        file_analyses = [self.analyzer.analyze_file(tf) for tf in test_files]
        project_score = self.scorer.score_project(file_analyses)
        summary.avg_score_before = project_score.avg_score

        # 3. 为每个文件做升级决策
        fs_map = {fs.file_path: fs for fs in project_score.file_scores}
        for fa in file_analyses:
            result = self._process_file(fa, fs_map)
            summary.results.append(result)
            summary.cases_upgraded += result.upgraded_count
            summary.cases_skipped += result.skipped_count
            if result.upgraded_count > 0:
                summary.files_upgraded += 1

        return summary

    def _process_file(self, fa: FileAnalysis, fs_map: dict) -> FileUpgradeResult:
        """处理单个文件"""
        tf = fa.test_file
        fs = fs_map.get(tf.file_path)
        result = FileUpgradeResult(
            file_path=tf.file_path,
            rel_path=tf.rel_path,
            api_type=fa.api_type,
            score_before=fs.total if fs else 0,
        )

        # 为每个用例做决策
        for i, tc in enumerate(tf.test_cases):
            decision = self._decide(tc, fa, i)
            result.decisions.append(decision)
            if decision.skip_reason:
                result.skipped_count += 1
            else:
                result.upgraded_count += 1

        # 如果有需要升级的用例，执行修改
        if result.upgraded_count > 0:
            if not self.dry_run:
                result.backup_path = self._backup(tf.file_path)
                self._apply(tf.file_path, result.decisions)

        return result

    def _decide(self, tc: TestCase, fa: FileAnalysis, case_index: int) -> UpgradeDecision:
        """为单个用例做升级决策"""
        base = dict(
            case_index=case_index,
            summary=tc.summary,
            original_check_type=tc.check_type,
            target_check_type=tc.check_type,
            level=0,
            risk='low',
        )

        # 跳过规则
        if tc.check_type in SKIP_CHECK_TYPES:
            return UpgradeDecision(**base, skip_reason=f'已是 {tc.check_type}，无需升级')

        # 错误场景用例：expected_result 中 code != 0
        if isinstance(tc.expected_result, dict) and tc.expected_result.get('code', 0) != 0:
            return UpgradeDecision(**base, skip_reason='错误场景用例，断言已合理')

        # 已有数据层断言：expected_result 有超出 code/msg 的字段
        if tc.check_type == 'check_json' and isinstance(tc.expected_result, dict):
            fields = set(tc.expected_result.keys())
            if fields and not fields <= ONLY_CODE_MSG_FIELDS:
                return UpgradeDecision(**base, skip_reason='已有数据层断言')

        # Level 1: check_code → check_json
        if tc.check_type == 'check_code':
            return UpgradeDecision(
                case_index=case_index,
                summary=tc.summary,
                original_check_type='check_code',
                target_check_type='check_json',
                level=1,
                risk='low',
                new_check_body=build_level1_check_body(tc.expected_code),
            )

        # Level 2: 弱 check_json → custom_check
        if self.level >= 2 and tc.check_type == 'check_json':
            er = tc.expected_result
            is_weak = (
                not er
                or not isinstance(er, dict)
                or set(er.keys()) <= ONLY_CODE_MSG_FIELDS
            )
            if is_weak:
                new_body = self._build_level2_body(fa, tc)
                return UpgradeDecision(
                    case_index=case_index,
                    summary=tc.summary,
                    original_check_type='check_json',
                    target_check_type='custom_check',
                    level=2,
                    risk='low',
                    new_check_body=new_body,
                )

        return UpgradeDecision(**base, skip_reason='不满足升级条件')

    def _build_level2_body(self, fa: FileAnalysis, tc: TestCase) -> dict:
        """根据接口类型选择 Level 2 模板。优先使用 capture 数据生成精确断言。"""
        expected_code = tc.expected_code

        # 优先使用 capture 数据
        capture_info = self.capture_map.get(fa.test_file.file_path)
        if capture_info and capture_info.get('data_exists'):
            return build_captured_check_body(capture_info, expected_code)

        # 回退到基于接口类型的模板
        if fa.api_type == 'search':
            page_size = None
            if isinstance(tc.parameter, dict):
                page_size = tc.parameter.get('pageSize')
            return build_search_check_body(
                has_pagination=fa.has_pagination,
                page_size=page_size,
                expected_code=expected_code,
            )
        elif fa.api_type == 'create':
            return build_create_check_body(expected_code)
        elif fa.api_type == 'detail':
            return build_detail_check_body(expected_code)
        elif fa.api_type in ('delete', 'update', 'action'):
            return build_safe_check_body(expected_code)
        else:
            return build_generic_check_body(expected_code)

    @staticmethod
    def _load_capture(capture_file: str) -> Dict[str, dict]:
        """加载 capture JSON，返回 {yaml_path: capture_info} 映射"""
        try:
            with open(capture_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (IOError, json.JSONDecodeError) as e:
            logger.warning("无法加载 capture 文件: %s (%s)", capture_file, e)
            return {}

        result = {}
        for file_entry in data.get('files', []):
            yaml_path = file_entry.get('yaml_path', '')
            if yaml_path:
                result[yaml_path] = file_entry
        return result

    def _backup(self, file_path: str) -> Optional[str]:
        """备份文件"""
        if self.no_backup:
            return None
        bak_path = file_path + '.bak'
        if os.path.exists(bak_path):
            ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            bak_path = f'{file_path}.bak.{ts}'
        shutil.copy2(file_path, bak_path)
        return bak_path

    def _apply(self, file_path: str, decisions: List[UpgradeDecision]):
        """应用升级到 YAML 文件"""
        with open(file_path, 'r', encoding='utf-8') as f:
            doc = self.yaml.load(f)

        for decision in decisions:
            if decision.skip_reason or decision.new_check_body is None:
                continue
            idx = decision.case_index
            if idx < len(doc['test_case']):
                doc['test_case'][idx]['check_body'] = decision.new_check_body

        # 验证：序列化后重新解析
        buf = io.StringIO()
        self.yaml.dump(doc, buf)
        verify_yaml = YAML()
        verify_yaml.load(buf.getvalue())

        # 原子写入：先写临时文件，验证后 rename
        import tempfile
        dir_name = os.path.dirname(os.path.abspath(file_path))
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', dir=dir_name,
                                         delete=False, encoding='utf-8') as tmp:
            self.yaml.dump(doc, tmp)
            tmp_path = tmp.name
        os.replace(tmp_path, file_path)

    @staticmethod
    def rollback_directory(path: str) -> int:
        """回滚：将 .bak 文件恢复"""
        count = 0
        for root, _, files in os.walk(path):
            for f in sorted(files):
                if f.endswith('.yaml.bak') or '.yaml.bak.' in f:
                    bak_path = os.path.join(root, f)
                    # 从 .bak 文件名推导原文件名（精确去掉 .bak 及后续时间戳）
                    original = re.sub(r'\.bak(\.\d{8}_\d{6})?$', '', bak_path)
                    if os.path.exists(original):
                        shutil.copy2(bak_path, original)
                        os.remove(bak_path)
                        count += 1
        return count
