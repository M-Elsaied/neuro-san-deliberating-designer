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
import shutil
import tempfile
from pathlib import Path
from unittest import TestCase

from coded_tools.agent_network_designer.pack_authoring import PackAuthoring
from coded_tools.agent_network_designer.pack_reader import PackReader
from coded_tools.agent_network_designer.pack_validator import PackValidator
from tests.coded_tools.agent_network_designer.pack_fixtures import PackFixtures


class TestPackAuthoring(TestCase):
    """
    Tests for PackAuthoring.
    """

    MANIFEST: str = """{ version = "1.0"\n standard_id_pattern = "ABC-\\\\d{2}" }"""

    def setUp(self) -> None:
        """Give each test an empty knowdocs root."""
        self.root: Path = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root)

    def run_command(self, *argv: str, knowdocs: bool = True) -> str:
        """Run "validate", against this test's knowdocs root unless told otherwise."""
        output: io.StringIO = io.StringIO()
        root: list[str] = ["--knowdocs", str(self.root)] if knowdocs else []
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            exit_code: int = PackAuthoring.main(["validate", *argv, *root])
        return f"{exit_code}\n{output.getvalue()}"

    def test_each_pack_is_reported_with_the_exit_code_it_earns(self) -> None:
        """Usable, under-specified only failing under --strict, unreadable reported rather than skipped, and usage."""
        self.assertIn("All 3 packs usable.", self.run_command("--all", knowdocs=False))
        self.assertTrue(self.run_command("--all").startswith("2\nNo knowledge packs found under"))
        PackFixtures.write_pack(self.root, "legacy", "- ABC-01: A rule.\n")
        PackFixtures.write_pack(self.root, "complete", "- ABC-01: A rule.\n", self.MANIFEST)
        cases: dict[tuple[str, ...], list[str]] = {
            ("--all",): [
                "0",
                "  complete" + " " * 27 + "OK       1 standard, 1 question, v1.0",
                "  legacy" + " " * 29 + "OK*",
                "All 2 packs usable. 1 could be more complete (marked OK*).",
            ],
            ("--all", "--strict"): ["1", "1 of 2 packs incomplete, and --strict was given."],
            ("--domain", "complete"): ["0", "complete - nothing to fix.\n\nAll 1 pack usable."],
            ("--domain", "nowhere"): ["2", "Available packs: complete, legacy"],
        }
        for argv, expected in cases.items():
            for fragment in expected:
                with self.subTest(argv=argv, fragment=fragment):
                    self.assertIn(fragment, self.run_command(*argv))
        PackFixtures.write_pack(self.root, "bad", "- ABC-01: A rule.\n", "{ version = ")
        output: str = self.run_command("--all")
        for fragment in (
            "1\n",
            "  bad" + " " * 32 + "PROBLEM  could not be read",
            "    -> Fix pack.hocon at the position",
            "1 of 3 packs cannot be used yet.",
        ):
            self.assertIn(fragment, output)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            PackAuthoring.main(["validate", "--all", "--domain", "complete"])

    def test_a_broken_pack_reports_every_fault_with_advice(self) -> None:
        """Errors come first, each with what to do, and the warnings heading does not claim the pack works."""
        PackFixtures.write_pack(self.root, "change", "- ABC-01 - Bad separator.\n- ABC-02: Fine.\n- ABC-02: Again.\n")
        expected: str = (
            "change - this pack cannot be used yet:\n\n  * duplicate standard id ABC-02.\n"
            "    -> Two rules share an id, so neither can be traced unambiguously. Renumber one of them.\n"
            "  * ABC-01 reads as a standard but its id is not followed by a colon or a full stop, so it was NOT "
            "loaded.\n    -> Use a colon straight after the id: '- ABC-01: <the rule>'. A dash or a bracket is not "
            "read.\n\nchange - also worth fixing, though these are not what blocks it:\n\n  * no pack.hocon found"
        )
        output: str = self.run_command("--domain", "change")
        self.assertIn(expected, output)
        self.assertTrue(output.startswith("1\n") and output.endswith("1 of 1 pack cannot be used yet.\n"))

    def test_every_problem_a_malformed_pack_can_produce_has_advice(self) -> None:
        """Advice is matched on message fragments, so a new message without any, or advice for none, is caught."""
        packs: dict[str, tuple[str, str | None]] = {
            "prose": ("Just prose, no rules at all.\n", self.MANIFEST),
            "no_ids": ("- A rule with no id.\n", self.MANIFEST),
            "numbered": ("1. ABC-01: A numbered rule.\n", self.MANIFEST),
            "mixed": (
                "- ABC-01 - Dash.\n- XYZ-01: Off.\n- ABC-02:\n- ABC-03: Fine.\n- ABC-03: Again.\n\nProse.\n",
                self.MANIFEST,
            ),
            "roles": ("- ABC-01: A rule.\n", """{ version = "1"\n roles { ABC-01 = gate, ABC-09 = work } }"""),
            "regex": ("- ABC-01: A rule.\n", """{ version = "1"\n standard_id_pattern = "ABC-[0-9" }"""),
            "empty": ("", "{ }"),
            "unmanifested": ("- ABC-01: A rule.\n", None),
        }
        for domain_id, (standards, manifest) in packs.items():
            PackFixtures.write_pack(self.root, domain_id, standards, manifest)
        (self.root / "empty" / PackReader.VARIABLES_FILENAME).write_text(
            "- V1 | q\n- V1 | again | examples: a | why: b\n"
        )
        (self.root / "empty" / PackReader.STANDARDS_FILENAME).unlink()
        (self.root / "regex" / PackReader.VARIABLES_FILENAME).write_text("")
        problems: list[str] = []
        for domain_id in packs:
            problems.extend(PackValidator.get_problems(PackReader.load_pack(domain_id, self.root)))
        PackFixtures.write_pack(self.root, "broken", "- ABC-01: A rule.\n", "{ version = ")
        with self.assertRaises(ValueError) as raised:
            PackReader.load_pack("broken", self.root)
        problems.append(str(raised.exception))
        for problem in problems:
            with self.subTest(problem=problem):
                self.assertIsNotNone(PackAuthoring.get_advice(problem))
        for fragment in PackAuthoring.GUIDANCE:
            with self.subTest(fragment=fragment):
                self.assertTrue(any(fragment in problem for problem in problems))
