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
import tempfile
from pathlib import Path
from unittest import TestCase

from pypdf import PdfWriter

from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack
from coded_tools.agent_network_designer.pack_reader import PackReader
from coded_tools.agent_network_designer.standard import Standard
from tests.coded_tools.agent_network_designer.pack_fixtures import PackFixtures


class TestPackReader(TestCase):
    """
    Tests for PackReader.
    """

    MANIFEST: str = """{ domain_id = "extra"\n version = "1.0"\n standard_id_pattern = "ABC-\\\\d{2}" }\n"""

    def setUp(self) -> None:
        """
        Give each test an empty directory to use as a knowdocs root.
        """
        # enterContext() removes the directory on cleanup, which pylint does not recognize.
        self.root: Path = Path(self.enterContext(tempfile.TemporaryDirectory()))  # pylint: disable=consider-using-with

    def test_shipped_domains_are_found_from_any_working_directory(self) -> None:
        """
        The default root is relative to the module, so the server works wherever it was started.
        """
        PackFixtures.use_knowdocs_root(self, None)
        self.addCleanup(os.chdir, Path.cwd())
        os.chdir(self.root)
        self.assertLessEqual(set(PackFixtures.SHIPPED_DOMAINS), set(PackReader.discover_domains()))

    def test_only_visible_directories_holding_documents_are_domains(self) -> None:
        """
        Scratch and hidden directories under the root are not packs.
        """
        (self.root / "scratch").mkdir()
        (self.root / ".hidden").mkdir()
        (self.root / ".hidden" / "notes.md").write_text("notes", encoding="utf-8")
        PackFixtures.write_pack(self.root, "real", "- ABC-01: A rule.\n")
        PackFixtures.use_knowdocs_root(self, self.root)
        self.assertEqual(["real"], PackReader.discover_domains())

    def test_a_missing_root_has_no_domains(self) -> None:
        """
        A misconfigured root means no curated knowledge rather than an error at startup.
        """
        PackFixtures.use_knowdocs_root(self, self.root / "missing")
        self.assertEqual([], PackReader.discover_domains())

    def test_an_unknown_domain_raises(self) -> None:
        """
        An unknown domain is an explicit miss, never a fallback to another domain's documents.
        """
        PackFixtures.use_knowdocs_root(self, self.root)
        with self.assertRaises(FileNotFoundError):
            PackReader.load_pack("no_such_domain")

    def test_the_manifest_sets_identity_pattern_and_roles(self) -> None:
        """
        A pack declares its own id pattern and roles, and its manifest supplies the provenance line.
        """
        manifest: str = (
            """{ domain_id = "house_rules"\n title = "House rules"\n version = "2.4"\n owner = "Platform"\n"""
            """ source = "SOP-7 rev 2"\n"""
            """ standard_id_pattern = "std-\\\\d{3}"\n roles { "std-001" = Precondition } }\n"""
        )
        PackFixtures.write_pack(
            self.root, "house_rules", "- std-001: Never ship on a Friday.\n- std-002: Two approvals.\n", manifest
        )
        PackFixtures.use_knowdocs_root(self, self.root)

        pack: KnowledgePack = PackReader.load_pack("house_rules")
        expected: list[Standard] = [
            Standard("std-001", "Never ship on a Friday.", "precondition"),
            Standard("std-002", "Two approvals."),
        ]
        self.assertEqual(expected, pack.standards)
        self.assertEqual("House rules, v2.4, owned by Platform", pack.manifest.get_provenance())
        self.assertEqual("SOP-7 rev 2", pack.manifest.source)

    def test_a_pack_without_a_manifest_is_named_after_its_directory(self) -> None:
        """
        A pack with no pack.hocon still loads.
        """
        PackFixtures.write_pack(self.root, "legacy_pack", "- LEG-01: Something invariant.\n")
        PackFixtures.use_knowdocs_root(self, self.root)

        pack: KnowledgePack = PackReader.load_pack("legacy_pack")
        self.assertTrue(pack.manifest.synthesized)
        self.assertEqual("legacy pack", pack.manifest.title)
        self.assertEqual([Standard("LEG-01", "Something invariant.")], pack.standards)

    def test_every_document_is_read_but_only_the_standards_file_is_parsed(self) -> None:
        """
        A README next to the pack is returned to the designer but adds no standards, and an unreadable PDF
        is returned as an error line rather than failing the load.
        """
        directory: Path = PackFixtures.write_pack(self.root, "extra", "- ABC-01: A rule.\n", self.MANIFEST)
        (directory / "README.md").write_text("- ABC-02: Just a note.\n", encoding="utf-8")
        (directory / "broken.pdf").write_bytes(b"not a pdf")
        (directory / "image.png").write_bytes(b"not a document")
        PackFixtures.use_knowdocs_root(self, self.root)

        pack: KnowledgePack = PackReader.load_pack("extra")
        self.assertEqual([Standard("ABC-01", "A rule.")], pack.standards)
        self.assertEqual(
            ["README.md", "broken.pdf", "open_variables.md", "operating_standards.md"], sorted(pack.documents)
        )
        self.assertTrue(pack.documents.get("broken.pdf").startswith("ERROR: Error reading PDF"))

    def test_load_catalog_returns_every_pack_in_order(self) -> None:
        """
        The catalog is what ListDomains reports.
        """
        PackFixtures.write_pack(self.root, "beta", "- B-01: Two.\n")
        PackFixtures.write_pack(self.root, "alpha", "- A-01: One.\n")
        PackFixtures.use_knowdocs_root(self, self.root)

        catalog: list[KnowledgePack] = PackReader.load_catalog()
        self.assertEqual(2, len(catalog))
        self.assertEqual("alpha", catalog[0].domain_id)
        self.assertEqual("beta", catalog[1].domain_id)

    def test_the_oracle_pack_loads_its_shipped_contents(self) -> None:
        """
        Spot-check the reference pack against its documents.
        """
        pack: KnowledgePack = PackFixtures.load_shipped_pack(self, "oracle_database_patching")
        self.assertEqual(6, len(pack.standards))
        self.assertEqual(7, len(pack.open_variables))
        self.assertEqual("1.0.0", pack.manifest.version)
        self.assertEqual("precondition", pack.get_standard("ODB-03").role)
        self.assertEqual("postcondition", pack.get_standard("ODB-04").role)

    def test_an_explicit_root_takes_precedence_over_the_environment(self) -> None:
        """
        A caller can read packs from a root of its own whatever the environment says.
        """
        PackFixtures.write_pack(self.root, "explicit", "- EXP-01: A rule.\n")
        PackFixtures.use_knowdocs_root(self, self.root / "elsewhere")
        self.assertEqual(self.root.resolve(), PackReader.get_knowdocs_root(self.root))
        self.assertEqual(["explicit"], PackReader.discover_domains(self.root))
        self.assertEqual("explicit", PackReader.load_pack("explicit", self.root).domain_id)
        self.assertEqual(1, len(PackReader.load_catalog(self.root)))

    def test_a_pdf_is_read_with_a_marker_before_each_page(self) -> None:
        """
        Page markers let the designer cite where in a PDF a standard came from.
        """
        writer: PdfWriter = PdfWriter()
        writer.add_blank_page(width=72, height=72)
        writer.add_blank_page(width=72, height=72)
        pdf_path: Path = self.root / "two_pages.pdf"
        with pdf_path.open("wb") as pdf_file:
            writer.write(pdf_file)
        self.assertEqual("\n\n--- Page 1 ---\n\n\n\n--- Page 2 ---\n\n", PackReader.read_pdf(pdf_path))

    def test_a_symlinked_pack_directory_is_still_a_domain(self) -> None:
        """
        A deployment can link a pack in from elsewhere on disk.
        """
        stored: Path = PackFixtures.write_pack(self.root / "store", "linked", "- ABC-01: A rule.\n")
        knowdocs: Path = self.root / "knowdocs"
        knowdocs.mkdir()
        (knowdocs / "linked").symlink_to(stored, target_is_directory=True)
        self.assertEqual(["linked"], PackReader.discover_domains(knowdocs))
        self.assertEqual([Standard("ABC-01", "A rule.")], PackReader.load_pack("linked", knowdocs).standards)
