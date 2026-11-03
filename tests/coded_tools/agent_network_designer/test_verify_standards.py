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
from unittest import IsolatedAsyncioTestCase

from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack
from coded_tools.agent_network_designer.verify_standards import VerifyStandards
from tests.coded_tools.agent_network_designer.pack_fixtures import PackFixtures


class TestVerifyStandards(IsolatedAsyncioTestCase):
    """
    Tests for VerifyStandards.
    """

    DOMAIN: str = "oracle_database_patching"

    def setUp(self) -> None:
        """
        Build the network a correct build of the Oracle pack produces.
        """
        self.network: dict[str, Any] = PackFixtures.build_reference_network(
            PackFixtures.load_shipped_pack(self, self.DOMAIN)
        )

    async def test_a_correct_build_verifies_and_records_provenance(self) -> None:
        """
        The tool runs in the same turn as persistence, so it records the provenance the network is stamped with.
        """
        sly_data: dict[str, Any] = {"agent_network_definition": self.network}
        result: Any = await VerifyStandards().async_invoke({"app_name": self.DOMAIN}, sly_data)

        self.assertTrue(result.get("ok"))
        self.assertEqual([], result.get("problems"))
        self.assertTrue(result.get("report").startswith("## Standards coverage (verified)"))
        self.assertEqual(
            "Oracle database patching, v1.0.0, owned by unassigned", sly_data.get(KnowledgePack.PROVENANCE_KEY)
        )

    async def test_a_network_passed_in_args_is_ignored(self) -> None:
        """
        The model being audited cannot hand the verifier a doctored copy of the network.
        """
        broken: dict[str, Any] = PackFixtures.replace_in_network(self.network, "[ODB-06]", "")
        args: dict[str, Any] = {"app_name": self.DOMAIN, "agent_network_definition": self.network}
        result: Any = await VerifyStandards().async_invoke(args, {"agent_network_definition": broken})
        self.assertFalse(result.get("ok"))

    async def test_each_missing_input_is_an_error(self) -> None:
        """
        No domain, no network yet, or an unknown domain is an error rather than an empty pass.
        """
        built: dict[str, Any] = {"agent_network_definition": self.network}
        cases: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {
            "Error: No domain provided": ({}, built),
            "Error: No agent network definition": ({"app_name": self.DOMAIN}, {}),
            """Error: No knowledge pack for domain "not_a_domain" under""": ({"app_name": "not_a_domain"}, built),
        }
        for expected, (args, sly_data) in cases.items():
            with self.subTest(expected=expected):
                result: Any = await VerifyStandards().async_invoke(args, sly_data)
                self.assertTrue(result.startswith(expected), result)

    async def test_strict_turns_only_a_failed_verification_into_an_error(self) -> None:
        """
        Advisory by default; strict is for a caller that wants a failed build to stop, and still carries the report.
        """
        broken: dict[str, Any] = PackFixtures.append_to_agent(self.network, "coordinator", "MUST: Invented. [ODB-99]")
        advisory: Any = await VerifyStandards().async_invoke(
            {"app_name": self.DOMAIN}, {"agent_network_definition": broken}
        )
        strict: Any = await VerifyStandards().async_invoke(
            {"app_name": self.DOMAIN, "strict": True}, {"agent_network_definition": broken}
        )
        clean: Any = await VerifyStandards().async_invoke(
            {"app_name": self.DOMAIN, "strict": True}, {"agent_network_definition": self.network}
        )
        self.assertFalse(advisory.get("ok"))
        self.assertTrue(strict.startswith("Error: Standards verification failed."))
        self.assertIn("ODB-99", strict)
        self.assertTrue(clean.get("ok"))

    async def test_missing_sly_data_is_reported_rather_than_raised(self) -> None:
        """
        Without sly_data there is no network to verify.
        """
        result: Any = await VerifyStandards().async_invoke({"app_name": self.DOMAIN}, None)
        self.assertTrue(result.startswith("Error: No agent network definition"))
