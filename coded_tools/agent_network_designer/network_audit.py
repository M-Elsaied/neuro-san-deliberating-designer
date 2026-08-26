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

"""
Audit a whole estate of generated networks against the packs they were built from.

WHY THIS EXISTS
---------------
Verification answers "does this network carry its pack faithfully?" at the moment of building.
Packs then change - a standard is reworded, a control is added, a version is cut - and every
network built before that change quietly stops matching the document it claims to implement.
Nothing noticed. In a regulated context an out-of-date control is the whole problem, not an
edge case.

This module answers the two questions that follow from that, both deterministically, with no
language model and no API key:

  STALENESS       which generated networks were built from a pack version that is no longer
                  current, and specifically WHICH standards have drifted since
  TRACEABILITY    which networks embed a given pack, or a given standard - the question an
                  auditor actually asks, in the form "show me everything that implements this"

HOW A NETWORK IS MATCHED TO ITS PACK
------------------------------------
By its embedded standard ids, not by its metadata. Every standard is embedded as
`MUST: <text> [<id>]`, and ids are exact, so counting which pack's ids appear identifies the
source pack unambiguously. That choice matters for three reasons: it needs no parsing of a
human-readable provenance line, it still works on networks generated before provenance stamping
existed at all, and it cannot be fooled by metadata that says one thing while the instructions
say another - which is exactly the discrepancy an audit is for.

The recorded version is read from the metadata, because that is the one fact the artifact alone
knows: which version of the pack it was built against.
"""

import argparse
import re
import sys
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any

from pyhocon import ConfigFactory

from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack
from coded_tools.agent_network_designer.standards_verifier import EmbeddedStandard
from coded_tools.agent_network_designer.standards_verifier import VerificationResult
from coded_tools.agent_network_designer.standards_verifier import extract_embedded_standards
from coded_tools.agent_network_designer.standards_verifier import verify

# The provenance line is generated as "<title>, v<version>, owned by <owner>", so the version is
# recoverable from it exactly. Only the version is taken from here; identity comes from the ids.
VERSION_RE: re.Pattern = re.compile(r"\bv(\d+(?:\.\d+)*)")

STATUS_CURRENT: str = "current"
STATUS_STALE: str = "stale"
STATUS_DRIFTED: str = "drifted"
STATUS_UNSTAMPED: str = "unstamped"
STATUS_UNKNOWN_PACK: str = "unknown pack"
STATUS_NO_STANDARDS: str = "no standards"


@dataclass
class AuditedNetwork:  # pylint: disable=too-many-instance-attributes
    """One generated network, placed against the pack it was built from."""

    path: Path
    domain_id: str = ""
    built_version: str = ""
    current_version: str = ""
    status: str = STATUS_NO_STANDARDS
    standard_ids: list[str] = field(default_factory=list)
    drifted: list[str] = field(default_factory=list)
    detail: str = ""

    @property
    def needs_attention(self) -> bool:
        """
        :return: True when this network is not demonstrably current against its pack.

        An unstamped network is deliberately NOT flagged: it predates provenance stamping and its
        standards may be perfectly current. Text drift is what actually matters, and that is
        checked independently of the version.
        """
        return self.status in (STATUS_STALE, STATUS_DRIFTED, STATUS_UNKNOWN_PACK)


def read_network(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Read a generated network into its agent definitions and its metadata.

    Includes resolve from the current working directory, not the file's own, for the reason
    documented on standards_verifier.network_definition_from_hocon: a generated network lives in
    registries/generated/ but writes its includes relative to the repository root.

    :param path: Path to a generated .hocon file.
    :return: (agent name to definition, the metadata block).
    :raises ValueError: If the file cannot be read or parsed.
    """
    try:
        content: str = path.read_text(encoding="utf-8")
    except OSError as exception:
        raise ValueError(f"Could not read {path}: {exception}") from exception
    try:
        config: Any = ConfigFactory.parse_string(content)
    except Exception as exception:
        raise ValueError(
            f"Could not parse {path}: {exception}. "
            f"A network's includes are relative to the repository root, so run this from there."
        ) from exception

    definition: dict[str, Any] = {}
    for entry in config.get("tools", None) or []:
        entry_dict: dict[str, Any] = dict(entry)
        name: str = str(entry_dict.get("name", "")).strip()
        if name:
            definition[name] = {"instructions": str(entry_dict.get("instructions", "") or "")}
    metadata: Any = config.get("metadata", None)
    return definition, dict(metadata) if metadata else {}


def identify_pack(embedded: list[EmbeddedStandard], packs: list[KnowledgePack]) -> KnowledgePack | None:
    """
    Work out which pack a network was built from, using the ids it embeds.

    :param embedded: The standards found in the network.
    :param packs: The live packs.
    :return: The best-matching pack, or None if no pack shares an id with this network.
    """
    found: set[str] = {standard.standard_id for standard in embedded}
    best: KnowledgePack | None = None
    best_score: int = 0
    for pack in packs:
        score: int = len({standard.standard_id for standard in pack.standards} & found)
        if score > best_score:
            best, best_score = pack, score
    return best


def audit_network(path: Path, packs: list[KnowledgePack]) -> AuditedNetwork:
    """
    Place one generated network against the live packs.

    :param path: Path to the generated .hocon file.
    :param packs: The live packs.
    :return: The audit result for this network.
    """
    audited = AuditedNetwork(path=path)
    try:
        definition, metadata = read_network(path)
    except ValueError as exception:
        audited.status = STATUS_UNKNOWN_PACK
        audited.detail = str(exception)
        return audited

    embedded: list[EmbeddedStandard] = extract_embedded_standards(definition)
    audited.standard_ids = sorted({standard.standard_id for standard in embedded})
    if not embedded:
        audited.status = STATUS_NO_STANDARDS
        audited.detail = "no MUST: <text> [<id>] lines, so this network carries no traceable standards"
        return audited

    pack: KnowledgePack | None = identify_pack(embedded, packs)
    if pack is None:
        audited.status = STATUS_UNKNOWN_PACK
        audited.detail = f"embeds {', '.join(audited.standard_ids)}, which belong to no pack on this deployment"
        return audited

    audited.domain_id = pack.domain_id
    audited.current_version = pack.manifest.version
    stamp: str = str(metadata.get("knowledge_pack", ""))
    version_match: re.Match | None = VERSION_RE.search(stamp)
    audited.built_version = version_match.group(1) if version_match else ""

    # Text drift is checked against the CURRENT pack, which is the point: a standard reworded
    # since the build shows up as a fidelity failure even when the version was never bumped.
    result: VerificationResult = verify(pack, definition)
    audited.drifted = sorted({mismatch["standard_id"] for mismatch in result.infidelities})

    if audited.drifted:
        audited.status = STATUS_DRIFTED
        verb: str = "no longer matches" if len(audited.drifted) == 1 else "no longer match"
        audited.detail = (
            f"{', '.join(audited.drifted)} {verb} the pack text, so this network implements a "
            f"rule the document no longer contains"
        )
    elif not audited.built_version:
        audited.status = STATUS_UNSTAMPED
        audited.detail = "no recorded pack version, so it predates provenance stamping"
    elif audited.built_version != audited.current_version:
        audited.status = STATUS_STALE
        audited.detail = f"built at v{audited.built_version}, pack is now v{audited.current_version}"
    else:
        audited.status = STATUS_CURRENT
    return audited


def audit_directory(directory: Path, packs: list[KnowledgePack]) -> list[AuditedNetwork]:
    """
    Audit every generated network in a directory.

    :param directory: The directory of generated .hocon files.
    :param packs: The live packs.
    :return: One result per network, in filename order.
    """
    audited: list[AuditedNetwork] = []
    for path in sorted(directory.glob("*.hocon")):
        if path.name == "manifest.hocon":
            continue
        audited.append(audit_network(path, packs))
    return audited


def render_audit(results: list[AuditedNetwork]) -> str:
    """
    Render the estate audit as markdown.

    :param results: The audited networks.
    :return: A markdown report.
    """
    if not results:
        return "No generated networks found."

    lines: list[str] = [
        "## Estate audit",
        "",
        "| Network | Pack | Built at | Pack now | Status |",
        "|---|---|---|---|---|",
    ]
    for audited in results:
        lines.append(
            f"| `{audited.path.name}` | {audited.domain_id or '-'} | "
            f"{('v' + audited.built_version) if audited.built_version else '-'} | "
            f"{('v' + audited.current_version) if audited.current_version else '-'} | "
            f"{'**' + audited.status + '**' if audited.needs_attention else audited.status} |"
        )

    attention: list[AuditedNetwork] = [audited for audited in results if audited.needs_attention]
    if attention:
        lines.append("")
        lines.append(f"**{len(attention)} of {len(results)} networks need attention:**")
        lines.append("")
        for audited in attention:
            lines.append(f"- `{audited.path.name}`: {audited.detail}")
    else:
        lines.append("")
        lines.append(f"All {len(results)} networks are current against the packs they were built from.")
    return "\n".join(lines)


def render_traceability(results: list[AuditedNetwork], pack_id: str | None, standard_id: str | None) -> str:
    """
    Render the answer to "show me everything that implements this".

    :param results: The audited networks.
    :param pack_id: Filter to networks built from this pack, or None.
    :param standard_id: Filter to networks embedding this standard, or None.
    :return: A markdown report.
    """
    matched: list[AuditedNetwork] = [
        audited
        for audited in results
        if (pack_id is None or audited.domain_id == pack_id)
        and (standard_id is None or standard_id in audited.standard_ids)
    ]
    subject: str = " and ".join(filter(None, [f"pack {pack_id}" if pack_id else "", standard_id or ""]))
    if not matched:
        return f"No generated network implements {subject}."

    lines: list[str] = [f"## Networks implementing {subject}", ""]
    for audited in matched:
        version: str = f"v{audited.built_version}" if audited.built_version else "version not recorded"
        lines.append(f"- `{audited.path.name}` - built against {version}, currently {audited.status}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """
    Command line entry point: audit a directory of generated networks.

    :param argv: Argument vector, or None to read sys.argv.
    :return: 0 when nothing needs attention, 1 when something does, 2 on a usage error.
    """
    parser = argparse.ArgumentParser(
        description="Audit generated agent networks against the knowledge packs they were built from."
    )
    parser.add_argument("directory", help="directory of generated .hocon networks")
    parser.add_argument("--knowdocs", default=None, help="override the knowdocs root")
    parser.add_argument("--pack", default=None, help="list only networks built from this pack")
    parser.add_argument("--standard", default=None, help="list only networks embedding this standard id")
    arguments = parser.parse_args(argv)

    # Imported here so the checks above stay usable against packs held in memory.
    from coded_tools.agent_network_designer.pack_catalogue import (  # pylint: disable=import-outside-toplevel
        load_catalogue,
    )

    directory: Path = Path(arguments.directory)
    if not directory.is_dir():
        print(f"Error: {directory} is not a directory", file=sys.stderr)
        return 2

    packs: list[KnowledgePack] = load_catalogue(arguments.knowdocs)
    if not packs:
        print("Error: no knowledge packs found, so nothing can be audited against them", file=sys.stderr)
        return 2

    results: list[AuditedNetwork] = audit_directory(directory, packs)
    if arguments.pack or arguments.standard:
        print(render_traceability(results, arguments.pack, arguments.standard))
        return 0

    print(render_audit(results))
    return 1 if any(audited.needs_attention for audited in results) else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
