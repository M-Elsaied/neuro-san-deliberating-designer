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
from unittest import TestCase

from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack
from coded_tools.agent_network_designer.open_variable import OpenVariable
from coded_tools.agent_network_designer.pack_manifest import PackManifest
from coded_tools.agent_network_designer.pack_parser import PackParser
from coded_tools.agent_network_designer.pack_reader import PackReader
from coded_tools.agent_network_designer.pack_validator import PackValidator
from coded_tools.agent_network_designer.standard import Standard
from tests.coded_tools.agent_network_designer.pack_fixtures import PackFixtures


class TestPackValidator(TestCase):
    """
    Tests for PackValidator.
    """

    def test_the_shipped_packs_are_clean(self) -> None:
        """
        The packs that ship satisfy the format they document.
        """
        PackFixtures.use_knowdocs_root(self, None)
        for domain_id in PackFixtures.SHIPPED_DOMAINS:
            with self.subTest(domain_id=domain_id):
                pack: KnowledgePack = PackReader.load_pack(domain_id)
                self.assertEqual([], PackValidator.get_errors(pack))
                self.assertEqual([], PackValidator.get_warnings(pack))

    def test_a_pack_without_standards_is_an_error_that_says_why(self) -> None:
        """No standards is an error that names what was written instead: nothing, prose, bare bullets, or bad ids."""
        cases: dict[str, str] = {
            "": "demo: operating_standards.md is empty or missing.",
            "# SOP\n\nEvery change needs a record.\n": "it has no bullets and 1 line of prose, so it is a document",
            "- Never deploy on a Friday.\n- Back up first.\n": "it has 2 bullets, none carrying an id.",
            "1. ABC-01: Never deploy.\n": "ids appear in the file, so these are standards written in a shape",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                pack: KnowledgePack = KnowledgePack(
                    manifest=PackFixtures.MANIFEST, documents={PackReader.STANDARDS_FILENAME: text}
                )
                error: str = PackValidator.get_missing_standards_errors(pack)[0]
                self.assertIn(expected, error)
                self.assertTrue(not text or error.endswith("extract them from the source document you already have."))

    def test_prose_after_a_standard_is_only_a_warning(self) -> None:
        """Only the author can tell a dropped rule from a closing note, so it must not fail verification."""
        with tempfile.TemporaryDirectory() as root:
            PackFixtures.write_pack(
                Path(root),
                "mixed",
                "- ABC-01: Never deploy on a Friday.\n\nAll changes need the CAB.\n",
                '{ version = "1.0"\n standard_id_pattern = "ABC-\\\\d{2}" }',
            )
            pack: KnowledgePack = PackReader.load_pack("mixed", root)
        self.assertEqual([], PackValidator.get_errors(pack))
        expected: str = (
            "mixed: operating_standards.md line 3 follows a standard but was not read as one: "
            "'All changes need the CAB.'. If it is a rule, write it as '- <ID>: <the rule, word for word>'."
        )
        self.assertEqual([expected], PackValidator.get_warnings(pack))

    def test_a_duplicate_standard_id_is_an_error(self) -> None:
        """
        Two rules under one id make ownership meaningless.
        """
        pack: KnowledgePack = PackFixtures.build_pack([Standard("ABC-01", "First."), Standard("ABC-01", "Second.")])
        self.assertEqual(["demo: duplicate standard id ABC-01."], PackValidator.get_errors(pack))

    def test_an_unloaded_standard_is_an_error(self) -> None:
        """
        A rule that never loaded cannot reach the network, so it must fail verification.
        """
        pack: KnowledgePack = PackFixtures.build_pack(
            [Standard("ABC-01", "A rule.")],
            unloaded=[{"standard_id": "XYZ-99", "reason": PackParser.UNLOADED_OFF_PATTERN}],
        )
        expected: str = (
            "demo: XYZ-99 reads as a standard but its id falls outside the pack's declared standard_id_pattern, "
            "so it was NOT loaded."
        )
        self.assertEqual([expected], PackValidator.get_errors(pack))

    def test_an_invalid_id_pattern_is_an_error(self) -> None:
        """
        A typo in the pattern is reported rather than raised at interview time.
        """
        manifest: PackManifest = PackManifest("demo", version="1.0", standard_id_pattern="ABC-[0-9")
        errors: list[str] = PackValidator.get_errors(
            PackFixtures.build_pack([Standard("ABC-01", "A rule.")], manifest)
        )
        self.assertEqual(1, len(errors))
        self.assertTrue(errors[0].startswith("demo: standard_id_pattern is not a valid regular expression"))

    def test_bad_or_dangling_roles_are_errors(self) -> None:
        """
        Roles drive topology, so a misspelled role or one for a removed standard must not pass silently.
        """
        manifest: PackManifest = PackManifest(
            "demo", version="1.0", standard_id_pattern=r"ABC-\d{2}", roles={"ABC-01": "preconditon", "ABC-77": "work"}
        )
        pack: KnowledgePack = PackFixtures.build_pack([Standard("ABC-01", "A rule.", "preconditon")], manifest)
        expected: list[str] = [
            "demo: standard ABC-01 declares role 'preconditon'; expected one of precondition, work, postcondition.",
            "demo: pack.hocon assigns a role to ABC-77, which is not a standard in this pack.",
        ]
        self.assertEqual(expected, PackValidator.get_errors(pack))

    def test_incomplete_open_variables_are_only_warnings(self) -> None:
        """
        A thin interview script weakens the questions, but the standards are intact.
        """
        variables: tuple[OpenVariable, ...] = (
            OpenVariable("V1", "Which?", "a; b"),
            OpenVariable("V1", "Again?", "c", "d"),
        )
        pack: KnowledgePack = PackFixtures.build_pack([Standard("ABC-01", "A rule.")], variables=variables)
        self.assertEqual([], PackValidator.get_errors(pack))
        expected: list[str] = [
            "demo: open variable V1 is missing its why.",
            "demo: duplicate open variable id V1.",
        ]
        self.assertEqual(expected, PackValidator.get_warnings(pack))

    def test_a_missing_manifest_or_version_is_only_a_warning(self) -> None:
        """
        A pack without provenance still delivers its standards.
        """
        synthesized: PackManifest = PackManifest("demo", synthesized=True)
        unversioned: PackManifest = PackManifest("demo")
        for manifest in (synthesized, unversioned):
            with self.subTest(synthesized=manifest.synthesized):
                pack: KnowledgePack = PackFixtures.build_pack([Standard("ABC-01", "A rule.")], manifest)
                self.assertEqual([], PackValidator.get_errors(pack))
                self.assertEqual(1, len(PackValidator.get_warnings(pack)))

    def test_an_off_pattern_or_empty_standard_is_an_error(self) -> None:
        """
        A pack assembled in code is held to the same rules as one parsed from disk.
        """
        pack: KnowledgePack = PackFixtures.build_pack([Standard("XYZ-01", "A rule."), Standard("ABC-02", " ")])
        expected: list[str] = [
            "demo: standard id XYZ-01 does not match the pack's declared pattern 'ABC-\\\\d{2}'.",
            "demo: standard ABC-02 has no text.",
        ]
        self.assertEqual(expected, PackValidator.get_errors(pack))

    def test_get_problems_lists_errors_and_warnings_in_document_order(self) -> None:
        """
        The full list reads top to bottom: manifest, then missing files, then each standard and each variable.
        """
        pack: KnowledgePack = PackFixtures.build_pack([], PackManifest("demo"), variables=())
        expected: list[str] = [
            "demo: pack.hocon declares no version.",
            "demo: operating_standards.md is empty or missing.",
            "demo: no open variables found in open_variables.md.",
        ]
        self.assertEqual(expected, PackValidator.get_problems(pack))
        self.assertEqual([expected[1]], PackValidator.get_errors(pack))
        self.assertEqual([expected[0], expected[2]], PackValidator.get_warnings(pack))
