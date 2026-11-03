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

import os
import shutil
import tempfile
from pathlib import Path
from unittest import TestCase

from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack
from coded_tools.agent_network_designer.pack_catalog import PackCatalog
from coded_tools.agent_network_designer.pack_reader import PackReader
from tests.coded_tools.agent_network_designer.pack_fixtures import PackFixtures


class TestPackCatalog(TestCase):
    """
    Tests for PackCatalog. tests/conftest.py clears the cache around each test.
    """

    def setUp(self) -> None:
        """Point the catalog at a fresh knowdocs root holding one pack."""
        self.root: Path = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root)
        PackFixtures.write_pack(self.root, "alpha", "- ABC-01: The first rule.\n")
        PackFixtures.use_knowdocs_root(self, self.root)

    def test_a_warm_catalog_is_shared_until_a_pack_changes(self) -> None:
        """One pack does not fill a cold cache, a warm one is shared, and an edit or a new pack is picked up."""
        self.assertEqual("alpha", PackCatalog.load_pack("alpha").domain_id)
        self.assertIsNone(PackCatalog.peek())
        first: KnowledgePack = PackCatalog.load_catalog()[0]
        self.assertIs(first, PackCatalog.load_pack("alpha"))
        standards: Path = self.root / "alpha" / PackReader.STANDARDS_FILENAME
        standards.write_text("- ABC-01: The reworded rule.\n", encoding="utf-8")
        os.utime(standards, ns=(standards.stat().st_mtime_ns + 10**9, standards.stat().st_mtime_ns + 10**9))
        self.assertEqual("The reworded rule.", PackCatalog.load_pack("alpha").standards[0].text)
        PackFixtures.write_pack(self.root, "beta", "- ABC-01: Another rule.\n")
        self.assertEqual(2, len(PackCatalog.load_catalog()))

    def test_an_explicit_or_changed_root_never_gets_a_wrong_hit(self) -> None:
        """The cache holds one root: another is read directly, and a changed or missing root is a miss."""
        other: Path = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, other)
        PackFixtures.write_pack(other, "gamma", "- ABC-01: A rule elsewhere.\n")
        PackCatalog.load_catalog()
        self.assertIsNot(PackCatalog.load_pack("gamma", other), PackCatalog.load_pack("gamma", other))
        self.assertEqual((None, ["alpha"]), (PackCatalog.peek(other), sorted(PackCatalog.peek())))
        PackFixtures.use_knowdocs_root(self, self.root / "nowhere")
        self.assertEqual([], PackCatalog.load_catalog())
