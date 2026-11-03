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
from typing import Any
from unittest import TestCase

from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack
from coded_tools.agent_network_designer.network_audit import NetworkAudit
from coded_tools.agent_network_designer.pack_reader import PackReader
from tests.coded_tools.agent_network_designer.pack_fixtures import PackFixtures


class TestNetworkAudit(TestCase):
    """
    Tests for NetworkAudit.
    """

    def setUp(self) -> None:
        """Give each test an empty directory of generated networks and the shipped Oracle pack."""
        self.directory: Path = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.directory)
        self.pack: KnowledgePack = PackFixtures.load_shipped_pack(self, "oracle_database_patching")
        self.network: dict[str, Any] = PackFixtures.build_reference_network(self.pack)

    def write(self, name: str, version: str | None, network: dict[str, Any] | None = None) -> None:
        """Write a generated network recording the provenance of a build of the pack at a version."""
        metadata: dict[str, str] | None = None if version is None else {"knowledge_pack": f"Oracle, v{version}, owned"}
        PackFixtures.write_network_file(self.directory / f"{name}.hocon", network or self.network, metadata)

    def test_each_network_is_placed_against_the_pack_its_ids_name(self) -> None:
        """Current, stale, drifted without a bump, unstamped, unknown, traceless and mislabeled are told apart."""
        first: str = self.pack.standards[0].text
        self.write("current", "1.0.0")
        self.write("drifted", "1.0.0", PackFixtures.replace_in_network(self.network, first, f"{first} Reworded."))
        self.write("stale", "0.9.0")
        self.write("unstamped", None)
        self.write("orphan", "1.0.0", {"agent": {"instructions": "MUST: A rule from nowhere. [XYZ-01]"}})
        self.write("plain", None, {"agent": {"instructions": "Do something."}})
        self.write(
            "mislabeled",
            "1.0.0",
            PackFixtures.build_reference_network(PackReader.load_pack("kubernetes_cluster_upgrade")),
        )
        (self.directory / "broken.hocon").write_text("[1, 2]", encoding="utf-8")
        (self.directory / "manifest.hocon").write_text("""{ "current.hocon": true }""", encoding="utf-8")
        broken: Path = self.directory / "broken.hocon"
        statuses: dict[str, str] = {}
        for audited in NetworkAudit.audit_directory(self.directory, PackReader.load_catalog()):
            statuses[audited.path.stem] = f"{audited.domain_id or '-'} {audited.status}: {audited.detail}"
        expected: dict[str, str] = {
            "broken": f"- unknown pack: {broken} is not a HOCON object; it does not look like an agent network.",
            "current": "oracle_database_patching current: ",
            "drifted": "oracle_database_patching drifted: ODB-01 no longer matches the pack text, so this network "
            "implements a rule the document no longer contains",
            "mislabeled": "kubernetes_cluster_upgrade current: ",
            "orphan": "- unknown pack: embeds XYZ-01, which belong to no pack on this deployment",
            "plain": "- no standards: no MUST: <text> [<id>] lines, so this network carries no traceable standards",
            "stale": "oracle_database_patching stale: built at v0.9.0, pack is now v1.0.0",
            "unstamped": "oracle_database_patching unstamped: no recorded pack version, so it predates provenance "
            "stamping",
        }
        self.assertEqual(expected, statuses)

    def test_the_command_line_exits_with_whether_anything_needs_attention(self) -> None:
        """Exit codes let the audit run as a scheduled check, and traceability answers "what implements this"."""
        cases: list[tuple[list[str], int, str]] = [
            ([], 0, "No generated networks found."),
            ([], 0, "All 1 networks are current against the packs they were built from."),
            (["--standard", "ODB-03"], 0, "- `current.hocon` - built against v1.0.0, currently current"),
            (["--pack", "nowhere"], 0, "No generated network implements pack nowhere."),
            ([], 1, "| `stale.hocon` | oracle_database_patching | v0.9.0 | v1.0.0 | **stale** |"),
            (["--knowdocs", str(self.directory)], 2, "Error: no knowledge packs found"),
        ]
        for index, (extra, exit_code, expected) in enumerate(cases):
            if index in (1, 4):
                self.write("current" if index == 1 else "stale", "1.0.0" if index == 1 else "0.9.0")
            with self.subTest(expected=expected):
                output: io.StringIO = io.StringIO()
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                    self.assertEqual(exit_code, NetworkAudit.main([str(self.directory), *extra]))
                self.assertIn(expected, output.getvalue())
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(2, NetworkAudit.main([str(self.directory / "nowhere")]))
