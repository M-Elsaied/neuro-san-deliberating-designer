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

from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack
from coded_tools.agent_network_designer.standard import Standard
from coded_tools.agent_network_designer.standards_verifier import StandardsVerifier
from coded_tools.agent_network_designer.verification_report import VerificationReport
from coded_tools.agent_network_designer.verification_result import VerificationResult
from tests.coded_tools.agent_network_designer.pack_fixtures import PackFixtures


class TestVerificationReport(TestCase):
    """
    Tests for VerificationReport.
    """

    def setUp(self) -> None:
        """
        Load the Oracle pack and the network a correct build of it produces.
        """
        self.pack: KnowledgePack = PackFixtures.load_shipped_pack(self, "oracle_database_patching")
        self.network: dict[str, Any] = PackFixtures.build_reference_network(self.pack)

    def test_a_clean_build_renders_the_table_with_its_provenance(self) -> None:
        """
        The report states which pack it checked against and who owns each standard.
        """
        report: str = VerificationReport.render(StandardsVerifier.verify(self.pack, self.network))
        self.assertTrue(
            report.startswith("## Standards coverage (verified)\n\n_Pack: Oracle database patching, v1.0.0")
        )
        self.assertIn("| **ODB-03** | precondition | `readiness_gate` | verbatim |", report)
        self.assertTrue(report.endswith("Every standard is embedded exactly once, verbatim, with a valid id."))

    def test_every_failure_is_named(self) -> None:
        """
        A partial, honest report is more useful than an exception.
        """
        dropped: Standard = self.pack.get_standard("ODB-01")
        altered: Standard = self.pack.get_standard("ODB-03")
        network: dict[str, Any] = PackFixtures.replace_in_network(
            self.network, PackFixtures.get_must_line(dropped), ""
        )
        network = PackFixtures.replace_in_network(network, altered.text, "Take a backup.")
        network = PackFixtures.append_to_agent(network, "coordinator", "MUST: Do something extra. [ODB-99]")
        result: VerificationResult = StandardsVerifier.verify(self.pack, network)

        problems: list[str] = VerificationReport.get_problems(result)
        self.assertEqual(3, len(problems))
        self.assertEqual("COVERAGE: ODB-01 is not embedded in any agent.", problems[0])
        self.assertTrue(problems[1].startswith("PROVENANCE: agent 'coordinator' carries id ODB-99"))
        self.assertTrue(problems[2].startswith("FIDELITY: ODB-03 in agent 'readiness_gate'"))

        report: str = VerificationReport.render(result)
        self.assertIn("| **ODB-01** | precondition | **not embedded** | - |", report)
        self.assertIn("| **ODB-03** | precondition | `readiness_gate` | **altered** |", report)
        self.assertIn("**This network did not verify clean:**", report)

    def test_pack_warnings_are_listed_without_failing(self) -> None:
        """
        Warnings do not stop a clean verification, but the report still shows them.
        """
        result: VerificationResult = VerificationResult(domain_id="demo", pack_warnings=["demo: a warning."])
        report: str = VerificationReport.render(result)
        self.assertIn("Every standard is embedded exactly once", report)
        self.assertTrue(
            report.endswith("**Pack warnings** (under-specified, but the standards are intact):\n\n- demo: a warning.")
        )
