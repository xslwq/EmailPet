from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import check_docs


class CheckDocsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.original_root = check_docs.ROOT
        check_docs.ROOT = self.root

    def tearDown(self) -> None:
        check_docs.ROOT = self.original_root
        self.temp_dir.cleanup()

    def write(self, relative: str, content: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_relative_link_to_existing_file_passes(self) -> None:
        source = self.write("docs/README.md", "[产品](product.md)\n")
        self.write("docs/product.md", "# 产品\n")
        errors: list[str] = []

        checked = check_docs.check_markdown_links([source], errors)

        self.assertEqual(checked, 1)
        self.assertEqual(errors, [])

    def test_broken_relative_link_reports_file_and_line(self) -> None:
        source = self.write("docs/README.md", "# 索引\n\n[缺失](missing.md)\n")
        errors: list[str] = []

        check_docs.check_markdown_links([source], errors)

        self.assertEqual(errors, ["docs/README.md:3: broken relative link: missing.md"])

    def test_external_links_and_links_in_fences_are_ignored(self) -> None:
        source = self.write(
            "README.md",
            "[官方](https://example.com)\n```markdown\n[示例](missing.md)\n```\n",
        )
        errors: list[str] = []

        check_docs.check_markdown_links([source], errors)

        self.assertEqual(errors, [])

    def test_dangling_legacy_reference_is_rejected(self) -> None:
        source = self.write(
            "module.py",
            '"""Module.\n\nSee docs/'
            'modules/module.md for full module doc.\n"""\n',
        )
        errors: list[str] = []

        check_docs.check_legacy_references([source], errors)

        self.assertEqual(
            errors,
            [
                "module.py:3: dangling legacy documentation reference: "
                "docs/modules/module.md"
            ],
        )

    def test_final_progress_requires_closed_state_and_resolved_fields(self) -> None:
        fields = {
            "状态": "`in_progress`",
            "已完成": "待填写。",
            "验证结果": "待执行。",
            "文档影响": "待确认。",
            "现场清理": "待执行。",
        }
        errors: list[str] = []

        with patch.object(check_docs, "changed_runtime_paths", return_value=[]):
            check_docs.check_final_progress(fields, errors)

        self.assertIn(
            "progress.md: final check requires status completed or blocked",
            errors,
        )
        self.assertEqual(len(errors), 5)

    def test_runtime_change_accepts_explicit_no_document_impact_reason(self) -> None:
        fields = {
            "状态": "`completed`",
            "已完成": "内部重命名完成。",
            "验证结果": "相关测试通过。",
            "文档影响": "无需更新：公共行为和接口未改变。",
            "现场清理": "无后台进程或临时文件残留。",
        }
        errors: list[str] = []

        with patch.object(
            check_docs,
            "changed_runtime_paths",
            return_value=["backend/emailpet/example.py"],
        ):
            check_docs.check_final_progress(fields, errors)

        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
