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

from pyhocon import ConfigFactory
from pyhocon.exceptions import ConfigException
from pyparsing.exceptions import ParseBaseException

from coded_tools.agent_network_designer.embedded_standard import EmbeddedStandard
from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack
from coded_tools.agent_network_designer.pack_catalog import PackCatalog
from coded_tools.agent_network_designer.pack_reader import PackReader
from coded_tools.agent_network_designer.pack_validator import PackValidator
from coded_tools.agent_network_designer.standard import Standard
from coded_tools.agent_network_designer.verification_report import VerificationReport
from coded_tools.agent_network_designer.verification_result import VerificationResult


class StandardsVerifier:
    """
    Checks that a generated network carries its pack's standards: each embedded in exactly one agent (coverage),
    word for word (fidelity), under an id the pack defines (provenance), and with no agent owning both a
    precondition and the work it guards (structure). It uses no language model, so the designer's closing
    coverage table is computed rather than written by the model about its own work.
    """

    # The id is the bracket group ending a line, so brackets inside the text are kept. The text may wrap
    # across lines, since the instructions are written by a model, but a blank line ends it.
    MUST_LINE_RE: re.Pattern = re.compile(
        r"MUST:[ \t]*(?P<text>(?:[^\n]|\n(?![ \t]*\n))+?)[ \t]*\[(?P<id>[^\]\n]+)\][ \t]*$",
        re.MULTILINE,
    )
    # Typography a model may substitute without changing the rule: a non-breaking space, curly quotes, and en and
    # em dashes.
    TYPOGRAPHY: dict[str, str] = {
        "\u00a0": " ",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
    }
    DIFFERENCE_CONTEXT: int = 40

    @staticmethod
    def verify(pack: KnowledgePack, network_definition: dict[str, Any] | None) -> VerificationResult:
        """
        Verify a generated network against the pack it was designed from.

        :param pack: The knowledge pack the network was designed from.
        :param network_definition: The generated network, as agent name to definition.
        :return: The verification result.
        """
        roles: dict[str, str] = {}
        for standard in pack.standards:
            roles[standard.standard_id] = standard.role or "-"
        result = VerificationResult(
            domain_id=pack.domain_id,
            provenance=pack.manifest.get_provenance(),
            roles=roles,
            pack_errors=PackValidator.get_errors(pack),
            pack_warnings=PackValidator.get_warnings(pack),
        )

        for embedded in StandardsVerifier.extract_embedded_standards(network_definition):
            standard: Standard | None = pack.get_standard(embedded.standard_id)
            if standard is None:
                result.unknown.append(embedded)
                continue
            result.owners.setdefault(embedded.standard_id, []).append(embedded.agent_name)
            expected: str = StandardsVerifier.normalize(standard.text)
            found: str = StandardsVerifier.normalize(embedded.text)
            if expected != found:
                result.infidelities.append(
                    {
                        "standard_id": embedded.standard_id,
                        "agent_name": embedded.agent_name,
                        "detail": StandardsVerifier.describe_difference(expected, found),
                    }
                )

        for standard in pack.standards:
            owners: list[str] = result.owners.get(standard.standard_id, [])
            if not owners:
                result.missing.append(standard.standard_id)
            elif len(set(owners)) > 1:
                result.ambiguous.append(standard.standard_id)

        result.structural = StandardsVerifier.check_structure(pack, result.owners)
        return result

    @staticmethod
    def extract_embedded_standards(network_definition: dict[str, Any] | None) -> list[EmbeddedStandard]:
        """
        Find the standards embedded in a network's instructions.

        :param network_definition: Agent name to definition. Agents without instructions are skipped.
        :return: Every "MUST: <text> [<id>]" line in the network, with the agent that carries it.
        """
        embedded: list[EmbeddedStandard] = []
        for agent_name, agent in (network_definition or {}).items():
            if not isinstance(agent, dict):
                continue
            instructions: str = str(agent.get("instructions") or "")
            for match in StandardsVerifier.MUST_LINE_RE.finditer(instructions):
                embedded.append(EmbeddedStandard(match.group("id").strip(), match.group("text").strip(), agent_name))
        return embedded

    @staticmethod
    def normalize(text: str | None) -> str:
        """
        Fold whitespace and typography so that re-wrapping is not reported as a changed standard, while a changed
        word, clause or punctuation mark still is.

        :param text: The text to normalize.
        :return: The normalized text.
        """
        if not text:
            return ""
        for original, replacement in StandardsVerifier.TYPOGRAPHY.items():
            text = text.replace(original, replacement)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def check_structure(pack: KnowledgePack, owners: dict[str, list[str]]) -> list[str]:
        """
        Check that no agent is both a gate and the work it guards.

        :param pack: The knowledge pack. A pack that declares no roles has nothing to check.
        :param owners: Standard id to the agents embedding it.
        :return: One problem per agent that owns both a precondition and a work standard.
        """
        roles_by_agent: dict[str, set[str]] = {}
        for standard in pack.standards:
            if standard.role is not None:
                for agent_name in owners.get(standard.standard_id, []):
                    roles_by_agent.setdefault(agent_name, set()).add(standard.role)

        problems: list[str] = []
        for agent_name, agent_roles in sorted(roles_by_agent.items()):
            if "precondition" in agent_roles and "work" in agent_roles:
                problems.append(
                    f"agent '{agent_name}' owns both a precondition and a work standard; a gate that is also "
                    f"the operation it guards does not gate anything."
                )
        return problems

    @staticmethod
    def describe_difference(expected: str, found: str) -> str:
        """
        Describe where an embedded standard first departs from the pack's text.

        :param expected: The pack's normalized text.
        :param found: The network's normalized text.
        :return: Where the two first differ, with some context, short enough for a report.
        """
        limit: int = min(len(expected), len(found))
        position: int = limit
        for index in range(limit):
            if expected[index] != found[index]:
                position = index
                break
        start: int = max(0, position - StandardsVerifier.DIFFERENCE_CONTEXT)
        end: int = position + StandardsVerifier.DIFFERENCE_CONTEXT
        prefix: str = "..." if start > 0 else ""
        return (
            f'first differs at character {position}: expected {prefix}"{expected[start:end]}" '
            f'but found {prefix}"{found[start:end]}"'
        )

    @staticmethod
    def read_network_definition(path: str | Path) -> dict[str, Any]:
        """
        Read a generated network file, so networks already on disk can be verified offline. The text is parsed
        relative to the working directory, as the server loads it, because a generated network's includes are
        relative to the repository root rather than to the file itself.

        :param path: A generated agent network .hocon file.
        :return: Agent name to a definition carrying its "instructions" and "tools".
        :raises ValueError: If the file cannot be read or parsed, or is not an agent network.
        """
        try:
            content: str = Path(path).read_text(encoding="utf-8")
        except OSError as exception:
            raise ValueError(f"Could not read {path}: {exception}") from exception
        try:
            config: Any = ConfigFactory.parse_string(content)
        except (ConfigException, ParseBaseException, OSError) as exception:
            raise ValueError(
                f"Could not parse {path}: {PackReader.describe_parse_error(exception)}. "
                f"A network's includes are relative to the repository root, so run this from there."
            ) from exception

        try:
            tools: Any = config.get("tools", None)
        except AttributeError as exception:
            raise ValueError(f"{path} is not a HOCON object; it does not look like an agent network.") from exception
        if not tools:
            raise ValueError(f"{path} declares no tools; it does not look like an agent network.")
        definition: dict[str, Any] = {}
        try:
            for entry in tools:
                agent: dict[str, Any] = dict(entry)
                name: str = str(agent.get("name", "")).strip()
                if name:
                    definition[name] = {
                        "instructions": str(agent.get("instructions", "") or ""),
                        "tools": list(agent.get("tools", []) or []),
                    }
        except (TypeError, ValueError) as exception:
            raise ValueError(
                f"{path} has a malformed tools entry; it does not look like an agent network."
            ) from exception
        return definition

    @staticmethod
    def main(argv: list[str] | None = None) -> int:
        """
        Verify a generated network file against a domain from the command line, with no model and no API key.

        :param argv: The arguments, or None to read sys.argv.
        :return: 0 when the network verifies clean, 1 when it does not, 2 on a usage error.
        """
        parser: ArgumentParser = ArgumentParser(
            description="Verify that a generated agent network carries its domain's operating standards."
        )
        parser.add_argument("network", help="path to a generated agent network .hocon file")
        # The domains are listed on the error path rather than in this help, so --help does not scan the packs.
        parser.add_argument("--domain", required=True, help="curated domain to verify against")
        parser.add_argument("--knowdocs", default=None, help="override the knowdocs root")
        arguments: Namespace = parser.parse_args(argv)
        try:
            pack: KnowledgePack = PackCatalog.load_pack(arguments.domain, arguments.knowdocs)
        except (OSError, ValueError) as exception:
            available: str = PackReader.describe_domains(arguments.knowdocs)
            print(f"Error: {exception}\nAvailable curated domains: {available}", file=sys.stderr)
            return 2
        try:
            definition: dict[str, Any] = StandardsVerifier.read_network_definition(arguments.network)
        except (OSError, ValueError) as exception:
            print(f"Error: {exception}", file=sys.stderr)
            return 2
        result: VerificationResult = StandardsVerifier.verify(pack, definition)
        print(VerificationReport.render(result))
        return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(StandardsVerifier.main())
