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

import re
import sys
from argparse import ArgumentParser
from argparse import Namespace
from pathlib import Path
from typing import Any

from coded_tools.agent_network_designer.audited_network import AuditedNetwork
from coded_tools.agent_network_designer.embedded_standard import EmbeddedStandard
from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack
from coded_tools.agent_network_designer.pack_reader import PackReader
from coded_tools.agent_network_designer.standards_verifier import StandardsVerifier
from coded_tools.agent_network_designer.verification_result import VerificationResult


class NetworkAudit:
    """
    Audits a directory of generated networks against the packs they were built from, with no model: which are stale
    or have drifted, and which implement a given pack or standard. A network is matched to its pack by the ids it
    embeds rather than by its metadata, so the match works on networks built before provenance was recorded.
    """

    STATUS_CURRENT: str = "current"
    STATUS_STALE: str = "stale"
    STATUS_DRIFTED: str = "drifted"
    STATUS_UNSTAMPED: str = "unstamped"
    STATUS_UNKNOWN_PACK: str = "unknown pack"
    STATUS_NO_STANDARDS: str = "no standards"
    # An unstamped network predates provenance recording and may be current, so it is reported but not flagged.
    ATTENTION_STATUSES: tuple[str, ...] = (STATUS_STALE, STATUS_DRIFTED, STATUS_UNKNOWN_PACK)
    # The provenance line reads "<title>, v<version>, ...", so the built version is recoverable from it.
    VERSION_RE: re.Pattern = re.compile(r"\bv(\d+(?:\.\d+)*)")

    @staticmethod
    def identify_pack(embedded: list[EmbeddedStandard], packs: list[KnowledgePack]) -> KnowledgePack | None:
        """
        Work out which pack a network was built from, from the standard ids it embeds.

        :param embedded: The standards found in the network.
        :param packs: The packs on this deployment.
        :return: The pack sharing the most ids, the first on a tie, or None if no pack shares one.
        """
        found: set[str] = set()
        for standard in embedded:
            found.add(standard.standard_id)
        best: KnowledgePack | None = None
        best_score: int = 0
        for pack in packs:
            score: int = 0
            for standard in pack.standards:
                score += standard.standard_id in found
            if score > best_score:
                best = pack
                best_score = score
        return best

    @staticmethod
    def audit_network(path: Path, packs: list[KnowledgePack]) -> AuditedNetwork:
        """
        Place one generated network against the packs on this deployment.

        :param path: A generated .hocon file.
        :param packs: The packs on this deployment.
        :return: The network's status, and why.
        """
        audited: AuditedNetwork = AuditedNetwork(path=path)
        try:
            config: Any = StandardsVerifier.read_network_config(path)
            definition: dict[str, Any] = StandardsVerifier.get_network_definition(config, path, require_tools=False)
        except ValueError as exception:
            audited.status = NetworkAudit.STATUS_UNKNOWN_PACK
            audited.detail = str(exception)
            return audited
        embedded: list[EmbeddedStandard] = StandardsVerifier.extract_embedded_standards(definition)
        standard_ids: set[str] = set()
        for standard in embedded:
            standard_ids.add(standard.standard_id)
        audited.standard_ids = sorted(standard_ids)
        pack: KnowledgePack | None = NetworkAudit.identify_pack(embedded, packs)
        if not embedded:
            audited.status = NetworkAudit.STATUS_NO_STANDARDS
            audited.detail = "no MUST: <text> [<id>] lines, so this network carries no traceable standards"
        elif pack is None:
            audited.status = NetworkAudit.STATUS_UNKNOWN_PACK
            audited.detail = f"embeds {', '.join(audited.standard_ids)}, which belong to no pack on this deployment"
        else:
            metadata: Any = config.get("metadata", None)
            stamp: str = str(metadata.get("knowledge_pack", "")) if isinstance(metadata, dict) else ""
            version_match: re.Match | None = NetworkAudit.VERSION_RE.search(stamp)
            NetworkAudit.compare_with_pack(audited, pack, definition, version_match.group(1) if version_match else "")
        return audited

    @staticmethod
    def audit_directory(directory: Path, packs: list[KnowledgePack]) -> list[AuditedNetwork]:
        """
        Audit every generated network in a directory. Its manifest.hocon lists the networks; it is not one.

        :param directory: A directory of generated .hocon files.
        :param packs: The packs on this deployment.
        :return: One result per network, in file name order.
        """
        audited: list[AuditedNetwork] = []
        for path in sorted(directory.glob("*.hocon")):
            if path.name != "manifest.hocon":
                audited.append(NetworkAudit.audit_network(path, packs))
        return audited

    @staticmethod
    def compare_with_pack(
        audited: AuditedNetwork, pack: KnowledgePack, definition: dict[str, Any], built_version: str
    ) -> None:
        """
        Fill in how a network compares with the current version of its pack. Drift is checked against the current
        text, so a reworded standard shows even without a version bump.

        :param audited: The audited network, updated in place.
        :param pack: The pack it was built from.
        :param definition: The network's agent definitions.
        :param built_version: The pack version the network records, or "".
        """
        audited.domain_id = pack.domain_id
        audited.current_version = pack.manifest.version
        audited.built_version = built_version
        result: VerificationResult = StandardsVerifier.verify(pack, definition)
        drifted: set[str] = set()
        for infidelity in result.infidelities:
            drifted.add(infidelity.get("standard_id"))
        audited.drifted = sorted(drifted)
        if audited.drifted:
            audited.status = NetworkAudit.STATUS_DRIFTED
            verb: str = "no longer matches" if len(audited.drifted) == 1 else "no longer match"
            audited.detail = (
                f"{', '.join(audited.drifted)} {verb} the pack text, so this network implements a rule the "
                f"document no longer contains"
            )
        elif not audited.built_version:
            audited.status = NetworkAudit.STATUS_UNSTAMPED
            audited.detail = "no recorded pack version, so it predates provenance stamping"
        elif audited.built_version != audited.current_version:
            audited.status = NetworkAudit.STATUS_STALE
            audited.detail = f"built at v{audited.built_version}, pack is now v{audited.current_version}"
        else:
            audited.status = NetworkAudit.STATUS_CURRENT

    @staticmethod
    def render(results: list[AuditedNetwork]) -> str:
        """
        Render the audit as markdown.

        :param results: The audited networks.
        :return: A table of each network's pack, versions and status, then what needs attention and why.
        """
        if not results:
            return "No generated networks found."
        lines: list[str] = [
            "## Estate audit",
            "",
            "| Network | Pack | Built at | Pack now | Status |",
            "|---|---|---|---|---|",
        ]
        attention: list[str] = []
        for audited in results:
            built: str = f"v{audited.built_version}" if audited.built_version else "-"
            current: str = f"v{audited.current_version}" if audited.current_version else "-"
            status: str = audited.status
            if audited.status in NetworkAudit.ATTENTION_STATUSES:
                status = f"**{audited.status}**"
                attention.append(f"- `{audited.path.name}`: {audited.detail}")
            lines.append(f"| `{audited.path.name}` | {audited.domain_id or '-'} | {built} | {current} | {status} |")
        lines.append("")
        if not attention:
            lines.append(f"All {len(results)} networks are current against the packs they were built from.")
            return "\n".join(lines)
        return "\n".join([*lines, f"**{len(attention)} of {len(results)} networks need attention:**", "", *attention])

    @staticmethod
    def render_traceability(results: list[AuditedNetwork], pack_id: str | None, standard_id: str | None) -> str:
        """
        Render the networks that implement a pack, a standard, or both.

        :param results: The audited networks.
        :param pack_id: Only networks built from this pack, or None for any.
        :param standard_id: Only networks embedding this standard, or None for any.
        :return: A markdown list of the matching networks, with the version each was built against.
        """
        subjects: list[str] = []
        if pack_id:
            subjects.append(f"pack {pack_id}")
        if standard_id:
            subjects.append(standard_id)
        subject: str = " and ".join(subjects)
        matched: list[str] = []
        for audited in results:
            if (pack_id is None or audited.domain_id == pack_id) and (
                standard_id is None or standard_id in audited.standard_ids
            ):
                version: str = f"v{audited.built_version}" if audited.built_version else "version not recorded"
                matched.append(f"- `{audited.path.name}` - built against {version}, currently {audited.status}")
        if not matched:
            return f"No generated network implements {subject}."
        return "\n".join([f"## Networks implementing {subject}", "", *matched])

    @staticmethod
    def main(argv: list[str] | None = None) -> int:
        """
        Audit a directory of generated networks from the command line.

        :param argv: The arguments, or None to read sys.argv.
        :return: 0 when nothing needs attention or a traceability question was answered, 1 when something needs
            attention, 2 on a usage error.
        """
        parser: ArgumentParser = ArgumentParser(
            description="Audit generated agent networks against the knowledge packs they were built from."
        )
        parser.add_argument("directory", help="directory of generated .hocon networks")
        parser.add_argument("--knowdocs", default=None, help="override the knowdocs root")
        parser.add_argument("--pack", default=None, help="list only networks built from this pack")
        parser.add_argument("--standard", default=None, help="list only networks embedding this standard id")
        arguments: Namespace = parser.parse_args(argv)
        directory: Path = Path(arguments.directory)
        if not directory.is_dir():
            print(f"Error: {directory} is not a directory", file=sys.stderr)
            return 2
        packs: list[KnowledgePack] = PackReader.load_catalog(arguments.knowdocs)
        if not packs:
            print("Error: no knowledge packs found, so nothing can be audited against them", file=sys.stderr)
            return 2
        results: list[AuditedNetwork] = NetworkAudit.audit_directory(directory, packs)
        needs_attention: bool = False
        for audited in results:
            needs_attention = needs_attention or audited.status in NetworkAudit.ATTENTION_STATUSES
        if arguments.pack or arguments.standard:
            print(NetworkAudit.render_traceability(results, arguments.pack, arguments.standard))
            return 0
        print(NetworkAudit.render(results))
        return 1 if needs_attention else 0


if __name__ == "__main__":
    sys.exit(NetworkAudit.main())
