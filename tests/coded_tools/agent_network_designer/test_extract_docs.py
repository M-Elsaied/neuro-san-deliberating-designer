# Copyright © 2025-2026 Cognizant Technology Solutions Corp, www.cognizant.com.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# END COPYRIGHT

import tempfile
from pathlib import Path
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest import mock

from coded_tools.agent_network_designer.extract_docs import ExtractDocs
from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack
from coded_tools.agent_network_designer.pack_reader import PackReader
from tests.coded_tools.agent_network_designer.pack_fixtures import PackFixtures


class TestExtractDocs(IsolatedAsyncioTestCase):
    """
    Tests for ExtractDocs.
    """

    DOMAIN: str = "oracle_database_patching"
    PROVENANCE: str = "Oracle database patching, v1.0.0, owned by unassigned"

    def setUp(self) -> None:
        """
        Read the shipped packs.
        """
        PackFixtures.use_knowdocs_root(self, None)

    async def test_documents_are_returned_verbatim_and_provenance_is_recorded(self) -> None:
        """
        Standards reach the designer word for word, and the pack is recorded for the generated network.
        """
        sly_data: dict[str, Any] = {}
        result: Any = await ExtractDocs().async_invoke({"app_name": self.DOMAIN}, sly_data)

        standards_path: Path = PackReader.DEFAULT_KNOWDOCS_ROOT / self.DOMAIN / PackReader.STANDARDS_FILENAME
        files: dict[str, str] = result.get("files")
        self.assertEqual(["open_variables.md", "operating_standards.md"], sorted(files))
        self.assertEqual(standards_path.read_text(encoding="utf-8"), files.get(PackReader.STANDARDS_FILENAME))
        expected_pack: dict[str, str] = {
            "id": self.DOMAIN,
            "title": "Oracle database patching",
            "version": "1.0.0",
            "provenance": self.PROVENANCE,
        }
        self.assertEqual(expected_pack, result.get("pack"))
        self.assertEqual(6, len(result.get("standard_ids")))
        self.assertEqual({KnowledgePack.PROVENANCE_KEY: self.PROVENANCE}, sly_data)

    async def test_an_unknown_or_missing_domain_names_the_alternatives(self) -> None:
        """
        A miss is explicit and lists what exists, so the designer can say it has no curated knowledge.
        """
        for args in ({"app_name": "pizza_delivery"}, {"app_name": "../../.."}, {}):
            with self.subTest(args=args):
                result: Any = await ExtractDocs().async_invoke(args, {})
                self.assertTrue(result.startswith("Error: No"))
                self.assertIn(self.DOMAIN, result)

    async def test_missing_sly_data_does_not_stop_the_documents(self) -> None:
        """
        Recording provenance is not a new way for the tool to fail.
        """
        result: Any = await ExtractDocs().async_invoke({"app_name": self.DOMAIN}, None)
        self.assertIn(PackReader.STANDARDS_FILENAME, result.get("files"))

    async def test_a_pack_without_documents_or_with_a_broken_manifest_is_an_error(self) -> None:
        """
        A pack folder holding only pack.hocon has nothing to read, and an unparseable one cannot be trusted.
        """
        with tempfile.TemporaryDirectory() as temporary:
            root: Path = Path(temporary)
            (root / "empty").mkdir()
            (root / "empty" / PackReader.MANIFEST_FILENAME).write_text("""{ version = "1" }""", encoding="utf-8")
            PackFixtures.write_pack(root, "broken", "- ABC-01: A rule.\n", "{ version = ")
            PackFixtures.use_knowdocs_root(self, root)
            empty: Any = await ExtractDocs().async_invoke({"app_name": "empty"}, {})
            broken: Any = await ExtractDocs().async_invoke({"app_name": "broken"}, {})
        self.assertTrue(empty.startswith("""ERROR: No knowledge documents found for domain "empty" under"""))
        self.assertTrue(broken.startswith("""Error: The knowledge pack for domain "broken" could not be read"""))

    async def test_an_unreadable_pack_directory_is_not_reported_as_missing(self) -> None:
        """
        A permission error is logged and named as such, rather than looking like an unknown domain.
        """
        with mock.patch.object(PackReader, "load_pack", side_effect=PermissionError("Permission denied")):
            with self.assertLogs("coded_tools.agent_network_designer.extract_docs", level="WARNING"):
                result: Any = await ExtractDocs().async_invoke({"app_name": self.DOMAIN}, {})
        self.assertTrue(result.startswith("""Error: The knowledge pack for domain "oracle_database_patching" could"""))
        self.assertIn("Permission denied", result)
