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

from coded_tools.agent_network_designer.list_domains import ListDomains
from tests.coded_tools.agent_network_designer.pack_fixtures import PackFixtures


class TestListDomains(IsolatedAsyncioTestCase):
    """
    Tests for ListDomains.
    """

    async def test_every_shipped_domain_is_listed_with_its_version_and_ids(self) -> None:
        """
        The designer decides which domain a request belongs to from this list.
        """
        PackFixtures.use_knowdocs_root(self, None)
        result: Any = await ListDomains().async_invoke({}, {})
        self.assertEqual(result, await ListDomains().async_invoke({"unexpected": "value"}, {}))

        domains: dict[str, dict[str, Any]] = {}
        for domain in result.get("domains"):
            domains[domain.get("id")] = domain
        self.assertEqual(len(domains), result.get("count"))
        self.assertLessEqual(set(PackFixtures.SHIPPED_DOMAINS), set(domains))
        oracle: dict[str, Any] = domains.get("oracle_database_patching")
        self.assertEqual("Oracle database patching", oracle.get("title"))
        self.assertEqual("1.0.0", oracle.get("version"))
        self.assertEqual(["ODB-01", "ODB-02", "ODB-03", "ODB-04", "ODB-05", "ODB-06"], oracle.get("standard_ids"))

    async def test_a_deployment_without_packs_is_an_error(self) -> None:
        """
        An empty catalog is an explicit miss, telling the designer to continue on general knowledge.
        """
        with tempfile.TemporaryDirectory() as root:
            PackFixtures.use_knowdocs_root(self, Path(root))
            result: Any = await ListDomains().async_invoke({}, {})
        self.assertTrue(result.startswith("Error: No curated knowledge domains found"))
        self.assertIn("general knowledge", result)
