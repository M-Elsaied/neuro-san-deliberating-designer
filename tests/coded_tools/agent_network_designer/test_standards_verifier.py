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

import contextlib
import io
import json
import os
import tempfile
from pathlib import Path
from typing import Any
from unittest import TestCase

from coded_tools.agent_network_designer.embedded_standard import EmbeddedStandard
from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack
from coded_tools.agent_network_designer.pack_parser import PackParser
from coded_tools.agent_network_designer.pack_reader import PackReader
from coded_tools.agent_network_designer.standard import Standard
from coded_tools.agent_network_designer.standards_verifier import StandardsVerifier
from coded_tools.agent_network_designer.verification_result import VerificationResult
from tests.coded_tools.agent_network_designer.pack_fixtures import PackFixtures


class TestStandardsVerifier(TestCase):
    """
    Tests for StandardsVerifier, mostly as edits to a correctly built network for the Oracle reference pack.
    """

    def setUp(self) -> None:
        """
        Load the Oracle pack and the network a correct build of it produces.
        """
        self.pack: KnowledgePack = PackFixtures.load_shipped_pack(self, "oracle_database_patching")
        self.network: dict[str, Any] = PackFixtures.build_reference_network(self.pack)

    def test_embedded_standards_are_found_with_their_agent(self) -> None:
        """
        Agents without instructions, such as coded tools, are skipped rather than crashed on.
        """
        network: dict[str, Any] = {
            "backup_gate": {"instructions": "MUST: Take a backup. [ODB-03]"},
            "validator": {"instructions": "Preamble.\nMUST: Check connectivity. [ODB-06]\nEpilogue."},
            "coded_tool": {"class": "some.Tool"},
            "empty": {"instructions": None},
            "malformed": "not a definition",
        }
        expected: list[EmbeddedStandard] = [
            EmbeddedStandard("ODB-03", "Take a backup.", "backup_gate"),
            EmbeddedStandard("ODB-06", "Check connectivity.", "validator"),
        ]
        self.assertEqual(expected, StandardsVerifier.extract_embedded_standards(network))
        self.assertEqual([], StandardsVerifier.extract_embedded_standards(None))

    def test_the_id_is_the_bracket_group_ending_the_line(self) -> None:
        """
        Brackets inside a standard's text and trailing whitespace do not hide or change its id.
        """
        network: dict[str, Any] = {"agent": {"instructions": "MUST: Read the README [and notes]. [ODB-05]   \nNext."}}
        expected: EmbeddedStandard = EmbeddedStandard("ODB-05", "Read the README [and notes].", "agent")
        self.assertEqual([expected], StandardsVerifier.extract_embedded_standards(network))

    def test_a_must_line_may_wrap_but_a_blank_line_ends_it(self) -> None:
        """
        The model writing instructions wraps long lines, but a paragraph break is not a wrap.
        """
        wrapped: dict[str, Any] = {"agent": {"instructions": "MUST: Take a backup,\nand confirm it. [ODB-03]"}}
        broken: dict[str, Any] = {"agent": {"instructions": "MUST: A rule with no id\n\nLater prose. [ODB-01]"}}
        expected: EmbeddedStandard = EmbeddedStandard("ODB-03", "Take a backup,\nand confirm it.", "agent")
        self.assertEqual([expected], StandardsVerifier.extract_embedded_standards(wrapped))
        self.assertEqual([], StandardsVerifier.extract_embedded_standards(broken))

    def test_only_the_upper_case_marker_counts(self) -> None:
        """
        A lower-case "must:" is prose.
        """
        lower: dict[str, Any] = {"agent": {"instructions": "must: A rule. [ABC-01]"}}
        upper: dict[str, Any] = {"agent": {"instructions": "You MUST: A rule. [ABC-01]"}}
        self.assertEqual([], StandardsVerifier.extract_embedded_standards(lower))
        self.assertEqual(1, len(StandardsVerifier.extract_embedded_standards(upper)))

    def test_a_correct_build_of_every_shipped_pack_verifies_clean(self) -> None:
        """
        The baseline every other test edits.
        """
        for domain_id in PackFixtures.SHIPPED_DOMAINS:
            with self.subTest(domain_id=domain_id):
                pack: KnowledgePack = PackReader.load_pack(domain_id)
                result: VerificationResult = StandardsVerifier.verify(pack, PackFixtures.build_reference_network(pack))
                self.assertTrue(result.ok)
                self.assertEqual(len(pack.standards), len(result.owners))

    def test_a_dropped_standard_is_missing(self) -> None:
        """
        The failure a self-reported coverage table is least likely to admit.
        """
        dropped: Standard = self.pack.get_standard("ODB-03")
        network: dict[str, Any] = PackFixtures.replace_in_network(
            self.network, PackFixtures.get_must_line(dropped), ""
        )
        result: VerificationResult = StandardsVerifier.verify(self.pack, network)
        self.assertFalse(result.ok)
        self.assertEqual(["ODB-03"], result.missing)

    def test_ownership_is_ambiguous_only_across_agents(self) -> None:
        """
        Two owning agents means neither is accountable; the same line twice in one agent is only untidy.
        """
        line: str = PackFixtures.get_must_line(self.pack.get_standard("ODB-01"))
        across: dict[str, Any] = PackFixtures.append_to_agent(self.network, "coordinator", line)
        within: dict[str, Any] = PackFixtures.replace_in_network(self.network, line, f"{line}\n{line}")

        self.assertEqual(["ODB-01"], StandardsVerifier.verify(self.pack, across).ambiguous)
        self.assertTrue(StandardsVerifier.verify(self.pack, within).ok)

    def test_an_invented_id_is_unknown(self) -> None:
        """
        A confident-looking rule under an id the pack does not define.
        """
        invented: str = "MUST: Always take two backups. [ODB-99]"
        network: dict[str, Any] = PackFixtures.append_to_agent(self.network, "coordinator", invented)
        result: VerificationResult = StandardsVerifier.verify(self.pack, network)
        self.assertFalse(result.ok)
        self.assertEqual([EmbeddedStandard("ODB-99", "Always take two backups.", "coordinator")], result.unknown)

    def test_changed_text_is_an_infidelity(self) -> None:
        """
        A paraphrase or a dropped clause keeps the id but changes the rule.
        """
        standard: Standard = self.pack.get_standard("ODB-03")
        edits: dict[str, str] = {
            "paraphrased": "Take a backup before patching.",
            "truncated": "Take a full RMAN backup before applying any patch.",
        }
        for name, text in edits.items():
            with self.subTest(edit=name):
                network: dict[str, Any] = PackFixtures.replace_in_network(self.network, standard.text, text)
                result: VerificationResult = StandardsVerifier.verify(self.pack, network)
                self.assertFalse(result.ok)
                self.assertEqual(1, len(result.infidelities))
                self.assertEqual("ODB-03", result.infidelities[0].get("standard_id"))
                self.assertTrue(result.infidelities[0].get("detail").startswith("first differs at character"))

    def test_rewrapping_and_typography_are_tolerated(self) -> None:
        """
        A model that re-wraps, indents or swaps in typographic punctuation has not changed the rule.
        """
        wrapped: str = self.pack.get_standard("ODB-03").text
        hyphenated: str = self.pack.get_standard("ODB-05").text
        network: dict[str, Any] = PackFixtures.replace_in_network(
            self.network, wrapped, wrapped.replace(", ", ",\n    ")
        )
        network = PackFixtures.replace_in_network(network, hyphenated, "\u00a0" + hyphenated.replace("-", "\u2013"))
        self.assertNotEqual(self.network, network)
        self.assertTrue(StandardsVerifier.verify(self.pack, network).ok)

    def test_a_gate_that_is_also_the_work_is_a_structural_problem(self) -> None:
        """
        An agent owning both a precondition and the work it guards has collapsed the gate.
        """
        pack: KnowledgePack = PackReader.load_pack("kubernetes_cluster_upgrade")
        network: dict[str, Any] = PackFixtures.build_reference_network(pack)
        gate: dict[str, Any] = network.pop("readiness_gate")
        network = PackFixtures.append_to_agent(network, "operator", gate.get("instructions"))
        result: VerificationResult = StandardsVerifier.verify(pack, network)
        self.assertFalse(result.ok)
        self.assertEqual(1, len(result.structural))
        self.assertTrue(result.structural[0].startswith("agent 'operator' owns both a precondition and a work"))

    def test_a_pack_without_roles_has_no_structure_to_check(self) -> None:
        """
        The structure check is opt-in through the manifest's roles.
        """
        pack: KnowledgePack = PackFixtures.build_pack([Standard("ABC-01", "One."), Standard("ABC-02", "Two.")])
        network: dict[str, Any] = {"agent": {"instructions": "MUST: One. [ABC-01]\nMUST: Two. [ABC-02]"}}
        self.assertTrue(StandardsVerifier.verify(pack, network).ok)

    def test_a_pack_error_fails_an_otherwise_clean_network(self) -> None:
        """
        A network built perfectly from a pack that lost a standard on load does not carry the pack.
        """
        pack: KnowledgePack = PackFixtures.build_pack(
            [Standard("ABC-01", "A rule.")],
            unloaded=[{"standard_id": "WRONG-02", "reason": PackParser.UNLOADED_OFF_PATTERN}],
        )
        result: VerificationResult = StandardsVerifier.verify(
            pack, {"agent": {"instructions": "MUST: A rule. [ABC-01]"}}
        )
        self.assertEqual([], result.missing + result.infidelities + result.unknown)
        self.assertFalse(result.ok)
        self.assertEqual(1, len(result.pack_errors))

    def test_normalize_folds_rendering_but_not_a_changed_word(self) -> None:
        """
        The line between tolerated and reported.
        """
        self.assertEqual("take a full backup", StandardsVerifier.normalize("take a\n  full\u00a0 backup "))
        self.assertEqual("don't - stop", StandardsVerifier.normalize("don\u2019t \u2014 stop"))
        self.assertNotEqual(
            StandardsVerifier.normalize("take a full backup"), StandardsVerifier.normalize("take a backup")
        )
        self.assertEqual("", StandardsVerifier.normalize(None))

    def test_a_generated_file_is_read_relative_to_the_repository_root(self) -> None:
        """
        Generated networks include files relative to the repository root, as the server loads them, so the file
        reads from the root and fails with a clear message from anywhere else.
        """
        with tempfile.TemporaryDirectory() as temporary:
            root: Path = Path(temporary)
            generated: Path = root / "registries" / "generated"
            generated.mkdir(parents=True)
            (root / "registries" / "aaosa.hocon").write_text("""{ aaosa_call = "shared" }\n""", encoding="utf-8")
            network_path: Path = generated / "net.hocon"
            network_path.write_text(
                """{
    include "registries/aaosa.hocon"
    "tools": [
        { "name": "gate", "call": ${aaosa_call}, "instructions": "MUST: A rule. [ABC-01]", "tools": ["x"] },
        { "instructions": "An entry with no name is skipped." }
    ]
}
""",
                encoding="utf-8",
            )
            self.addCleanup(os.chdir, os.getcwd())
            os.chdir(root)
            expected: dict[str, Any] = {"gate": {"instructions": "MUST: A rule. [ABC-01]", "tools": ["x"]}}
            self.assertEqual(expected, StandardsVerifier.read_network_definition(network_path))

            os.chdir(generated)
            with self.assertRaisesRegex(ValueError, "relative to the repository root"):
                StandardsVerifier.read_network_definition(network_path)

    def test_a_file_that_is_not_an_agent_network_is_rejected(self) -> None:
        """
        A wrong or missing file is an error, not a network with zero coverage.
        """
        with tempfile.TemporaryDirectory() as temporary:
            notes: Path = Path(temporary) / "notes.hocon"
            notes.write_text("""{ "something": "else" }\n""", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not look like an agent network"):
                StandardsVerifier.read_network_definition(notes)
            with self.assertRaisesRegex(ValueError, "Could not read"):
                StandardsVerifier.read_network_definition(Path(temporary) / "missing.hocon")
            malformed: dict[str, str] = {
                "missing_include.hocon": """{ include required("nowhere.hocon")\n "tools": [{ "name": "a" }] }""",
                "list_root.hocon": """[{ "name": "a" }]""",
                "scalar_tools.hocon": """{ "tools": [1, 2] }""",
            }
            malformed_path: Path = Path(temporary) / "unclosed.hocon"
            malformed_path.write_text("""{ "tools": [ """, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, r"unclosed\.hocon: syntax error at line 1, column \d+\. "):
                StandardsVerifier.read_network_definition(malformed_path)
            for file_name, content in malformed.items():
                with self.subTest(file_name=file_name):
                    malformed_path = Path(temporary) / file_name
                    malformed_path.write_text(content, encoding="utf-8")
                    with self.assertRaises(ValueError):
                        StandardsVerifier.read_network_definition(malformed_path)

    @staticmethod
    def write_network_file(path: Path, network: dict[str, Any]) -> Path:
        """
        Write a network as the generated .hocon file the command line reads.

        :param path: Where to write it.
        :param network: Agent name to definition.
        :return: The path.
        """
        tools: list[dict[str, Any]] = []
        for agent_name, agent in network.items():
            tools.append({"name": agent_name, "instructions": agent.get("instructions")})
        # HOCON is a superset of JSON, so the generated file can be written as JSON.
        path.write_text(json.dumps({"tools": tools}), encoding="utf-8")
        return path

    def test_the_command_line_prints_the_report_and_exits_with_the_outcome(self) -> None:
        """
        The report goes to stdout with exit 0 when clean and 1 when not; a usage error goes to stderr with exit 2.
        """
        with tempfile.TemporaryDirectory() as temporary:
            root: Path = Path(temporary)
            clean: str = str(self.write_network_file(root / "clean.hocon", self.network))
            broken: str = str(self.write_network_file(root / "broken.hocon", {"agent": {"instructions": "None."}}))
            own: str = str(
                self.write_network_file(root / "own.hocon", {"agent": {"instructions": "MUST: A. [ABC-01]"}})
            )
            PackFixtures.write_pack(root / "knowdocs", "own_pack", "- ABC-01: A.\n")
            cases: dict[str, tuple[list[str], int, str, str]] = {
                "clean": ([clean, "--domain", self.pack.domain_id], 0, "Every standard is embedded exactly once", ""),
                "failed": ([broken, "--domain", self.pack.domain_id], 1, "COVERAGE: ODB-01 is not embedded", ""),
                "unknown domain": (
                    [clean, "--domain", "nowhere"],
                    2,
                    "",
                    """No knowledge pack for domain "nowhere" under""",
                ),
                "unknown domain named against its own knowdocs": (
                    [clean, "--domain", "nowhere", "--knowdocs", str(root / "knowdocs")],
                    2,
                    "",
                    "\nAvailable curated domains: own_pack",
                ),
                "own knowdocs": (
                    [own, "--domain", "own_pack", "--knowdocs", str(root / "knowdocs")],
                    0,
                    "| **ABC-01** | - | `agent` | verbatim |",
                    "",
                ),
            }
            for case, (argv, exit_code, expected_out, expected_err) in cases.items():
                with self.subTest(case=case):
                    stdout: io.StringIO = io.StringIO()
                    stderr: io.StringIO = io.StringIO()
                    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                        self.assertEqual(exit_code, StandardsVerifier.main(argv))
                    self.assertIn(expected_out, stdout.getvalue())
                    self.assertIn(expected_err, stderr.getvalue())
