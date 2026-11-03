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

from typing import Any
from unittest import TestCase
from unittest import mock

from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack
from coded_tools.agent_network_designer.pack_catalog import PackCatalog
from middleware.agent_network_designer.persistence import agent_network_persistence_middleware
from middleware.agent_network_designer.persistence.agent_network_persistence_middleware import (
    AgentNetworkPersistenceMiddleware,
)
from tests.coded_tools.agent_network_designer.pack_fixtures import PackFixtures


class TestAgentNetworkPersistenceMiddleware(TestCase):
    """
    Tests for the standards check AgentNetworkPersistenceMiddleware runs before persisting a network.
    """

    # pylint: disable=protected-access

    def setUp(self) -> None:
        """Build the middleware, which needs no reservationist for this check, and a faithful Oracle network."""
        self.check: Any = AgentNetworkPersistenceMiddleware(None, {})._get_standards_errors
        self.pack: KnowledgePack = PackFixtures.load_shipped_pack(self, "oracle_database_patching")
        self.network: dict[str, Any] = PackFixtures.build_reference_network(self.pack)

    def test_only_a_paraphrased_standard_or_an_invented_id_blocks_persistence(self) -> None:
        """Neither is a judgment call, and each error is addressed to the agent that can repair it."""
        self.assertEqual([], self.check(self.network) + self.check({"agent": {"instructions": "No standards."}}))
        text: str = self.pack.standards[2].text
        owner: str = PackFixtures.ROLE_OWNERS.get(self.pack.standards[2].role or "work")
        errors: list[str] = self.check(PackFixtures.replace_in_network(self.network, text, f"{text} Probably."))
        self.assertTrue(
            errors[0].startswith(f"Standard ODB-03 in agent '{owner}' does not match the curated document.")
        )
        self.assertTrue(errors[0].endswith("Call `agent_network_instructions_editor` to restore the exact wording."))
        invented: list[str] = self.check(PackFixtures.append_to_agent(self.network, owner, "MUST: Twice. [ODB-99]"))
        self.assertTrue(invented[0].startswith(f"Agent '{owner}' carries the standard id ODB-99, which the oracle"))

    def test_incomplete_coverage_only_logs_and_nothing_blocks_when_off_or_unreadable(self) -> None:
        """Five of six standards is still useful, a deployment can turn the check off, and a bad root never blocks."""
        missing: dict[str, Any] = PackFixtures.replace_in_network(
            self.network, PackFixtures.get_must_line(self.pack.standards[0]), ""
        )
        paraphrased: dict[str, Any] = PackFixtures.replace_in_network(self.network, "MUST: ", "MUST: Maybe ")
        with self.assertLogs(level="WARNING") as logs:
            self.assertEqual([], self.check(missing))
            with mock.patch.object(PackCatalog, "load_catalog", side_effect=PermissionError("denied")):
                self.assertEqual([], self.check(paraphrased))
        self.assertIn("missing=['ODB-01']", logs.output[0])
        self.assertIn("Could not check standards, so not enforcing them: denied", logs.output[1])
        with mock.patch.object(agent_network_persistence_middleware, "ENFORCE_STANDARDS", False):
            self.assertEqual([], self.check(paraphrased))
