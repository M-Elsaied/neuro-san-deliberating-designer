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
Verify that a generated agent network actually carries its domain's operating standards.

WHY THIS EXISTS
---------------
The designer embeds each operating standard in the agent that owns it as::

    MUST: <the standard's text, verbatim> [<its id>]

and then closes by printing a standards-coverage table. That table is written by the language
model - it is the model asserting its own compliance, in the same breath as doing the work it is
asserting about. Meanwhile the guarantee that a standard reached the network word for word rests
on a downstream instructions-writing agent choosing to honour a formatting instruction embedded
in a string handed to it. If it paraphrases, merges two standards, drops a clause or invents an
id, nothing today notices, and the self-reported table still claims full coverage.

This module computes the table instead. It is deterministic, uses no language model, and turns
three properties the design already claims into checks that either pass or do not:

  coverage    every standard in the pack is owned by exactly one agent
  fidelity    the embedded text matches the pack text
  provenance  every embedded id exists in the pack - nothing was invented
  pack        the pack itself loaded soundly, since a standard that never loaded cannot have
              reached the network however carefully it was built

A fourth, structural check runs when the pack declares temporal roles: a precondition and a work
standard must not be owned by the same agent, because a gate that is also the operation it guards
is not a gate.

Deliberately free of any neuro-san import, so the same checks can run from a script, a pre-commit
hook or a CI job with no agent runtime and no API key. See __main__ at the foot of this file.
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
from coded_tools.agent_network_designer.knowledge_pack import discover_domains
from coded_tools.agent_network_designer.knowledge_pack import load_pack
from coded_tools.agent_network_designer.knowledge_pack import normalise

# A standard as embedded in a generated agent's instructions.
#
# Two properties have to hold at once, and getting either wrong makes the checks below lie:
#
#   * The id is the bracket group ENDING A LINE. Anchoring on `$` means a standard whose own
#     text contains brackets - "review the README [and its notes] carefully. [ODB-05]" - still
#     yields ODB-05 rather than the first bracket group it happens to meet.
#   * The text may WRAP. The instruction says put each standard on its own line, but the agent
#     writing those instructions is a language model and wraps long lines. A line-only pattern
#     would miss a wrapped standard entirely and report it as never embedded, sending a reviewer
#     hunting for a rule that is present and correct. So a newline is accepted inside the text,
#     unless it is followed by a blank line - which ends the paragraph and cannot be a wrap.
MUST_LINE_RE: re.Pattern = re.compile(
    r"MUST:[ \t]*(?P<text>(?:[^\n]|\n(?![ \t]*\n))+?)[ \t]*\[(?P<id>[^\]\n]+)\][ \t]*$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class EmbeddedStandard:
    """One `MUST: ... [id]` line found in a generated agent's instructions."""

    standard_id: str
    text: str
    agent_name: str


@dataclass
class VerificationResult:  # pylint: disable=too-many-instance-attributes
    """The computed outcome of verifying one network against one pack."""

    domain_id: str
    provenance: str = ""
    roles: dict[str, str] = field(default_factory=dict)
    owners: dict[str, list[str]] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    ambiguous: list[str] = field(default_factory=list)
    unknown: list[EmbeddedStandard] = field(default_factory=list)
    infidelities: list[dict[str, str]] = field(default_factory=list)
    structural: list[str] = field(default_factory=list)
    pack_errors: list[str] = field(default_factory=list)
    pack_warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """
        :return: True when the network carries the pack faithfully AND the pack itself is sound.

        Pack errors gate this deliberately. If a standard never loaded - an id outside the declared
        pattern, an empty body, a duplicate - then no amount of correct building can produce a
        network that carries the pack, and the designer is told to speak up only when this is False.
        Reporting such a network as verified would be precisely the self-certification this module
        exists to remove. Pack warnings do not gate: they leave the standards intact.
        """
        return not (
            self.missing or self.ambiguous or self.unknown or self.infidelities or self.structural or self.pack_errors
        )

    def problems(self) -> list[str]:
        """
        :return: Every failure as a flat list of human-readable lines.
        """
        lines: list[str] = [f"PACK: {problem}" for problem in self.pack_errors]
        for standard_id in self.missing:
            lines.append(f"COVERAGE: {standard_id} is not embedded in any agent.")
        for standard_id in self.ambiguous:
            owners: str = ", ".join(sorted(set(self.owners.get(standard_id, []))))
            lines.append(
                f"COVERAGE: {standard_id} is embedded in more than one agent ({owners}); ownership is ambiguous."
            )
        for embedded in self.unknown:
            lines.append(
                f"PROVENANCE: agent '{embedded.agent_name}' carries id {embedded.standard_id}, "
                f"which is not a standard in this pack."
            )
        for mismatch in self.infidelities:
            lines.append(
                f"FIDELITY: {mismatch['standard_id']} in agent '{mismatch['agent_name']}' "
                f"does not match the pack text. {mismatch['detail']}"
            )
        lines.extend(f"STRUCTURE: {message}" for message in self.structural)
        return lines


def _first_difference(expected: str, found: str, window: int = 40) -> str:
    """
    Describe where two normalised strings diverge, compactly enough to print in a report.

    :param expected: The pack's text.
    :param found: The text embedded in the network.
    :param window: How many characters of context to show either side.
    :return: A short human-readable description of the first divergence.
    """
    limit: int = min(len(expected), len(found))
    position: int = limit
    for index in range(limit):
        if expected[index] != found[index]:
            position = index
            break
    if position == limit and len(expected) == len(found):
        return "Texts differ only in characters removed by normalisation."
    start: int = max(0, position - window)
    prefix: str = "..." if start > 0 else ""
    return (
        f'first differs at character {position}: expected {prefix}"{expected[start : position + window]}" '
        f'but found {prefix}"{found[start : position + window]}"'
    )


def extract_embedded_standards(network_definition: dict[str, Any]) -> list[EmbeddedStandard]:
    """
    Find every `MUST: ... [id]` line across all agents in a network definition.

    :param network_definition: Mapping of agent name to its definition. Each value may carry an
        "instructions" string; agents without one (coded tools, toolbox entries) are skipped.
    :return: Every embedded standard found, with its owning agent.
    """
    embedded: list[EmbeddedStandard] = []
    for agent_name, agent in (network_definition or {}).items():
        if not isinstance(agent, dict):
            continue
        instructions: str = str(agent.get("instructions") or "")
        if not instructions:
            continue
        for match in MUST_LINE_RE.finditer(instructions):
            embedded.append(
                EmbeddedStandard(
                    standard_id=match.group("id").strip(),
                    text=match.group("text").strip(),
                    agent_name=agent_name,
                )
            )
    return embedded


def _check_structure(pack: KnowledgePack, owners: dict[str, list[str]]) -> list[str]:
    """
    Check the topology implied by declared temporal roles.

    A precondition becomes a gate agent and the work is the operation it guards, so an agent
    owning both is not gating anything. Packs that declare no roles are skipped entirely, which
    keeps this check opt-in and backward compatible.

    :param pack: The loaded pack.
    :param owners: Mapping of standard id to the agents embedding it.
    :return: Structural problems, empty when the topology holds.
    """
    problems: list[str] = []
    roles_by_agent: dict[str, set[str]] = {}
    for standard in pack.standards:
        if standard.role is None:
            continue
        for agent_name in owners.get(standard.standard_id, []):
            roles_by_agent.setdefault(agent_name, set()).add(standard.role)

    for agent_name, agent_roles in sorted(roles_by_agent.items()):
        if "precondition" in agent_roles and "work" in agent_roles:
            problems.append(
                f"agent '{agent_name}' owns both a precondition and a work standard; a gate that is "
                f"also the operation it guards does not gate anything."
            )
    return problems


def verify(pack: KnowledgePack, network_definition: dict[str, Any]) -> VerificationResult:
    """
    Compute coverage, fidelity, provenance and structure for one network against one pack.

    Pure function: no I/O beyond what the caller already loaded, and no language model. This is
    what makes the check runnable in CI without an API key.

    :param pack: The loaded knowledge pack for the domain.
    :param network_definition: The generated network, as agent name to definition.
    :return: The verification result.
    """
    result = VerificationResult(
        domain_id=pack.domain_id,
        provenance=pack.manifest.provenance(),
        roles={standard.standard_id: standard.role or "-" for standard in pack.standards},
        pack_errors=pack.validate_errors(),
        pack_warnings=pack.validate_warnings(),
    )

    known_ids: set[str] = {standard.standard_id for standard in pack.standards}

    for item in extract_embedded_standards(network_definition):
        if item.standard_id not in known_ids:
            result.unknown.append(item)
            continue
        result.owners.setdefault(item.standard_id, []).append(item.agent_name)

        pack_standard = pack.standard(item.standard_id)
        expected: str = pack_standard.normalised_text if pack_standard else ""
        actual: str = normalise(item.text)
        if expected != actual:
            result.infidelities.append(
                {
                    "standard_id": item.standard_id,
                    "agent_name": item.agent_name,
                    "detail": _first_difference(expected, actual),
                }
            )

    for standard in pack.standards:
        owners: list[str] = result.owners.get(standard.standard_id, [])
        if not owners:
            result.missing.append(standard.standard_id)
        elif len(set(owners)) > 1:
            result.ambiguous.append(standard.standard_id)

    result.structural = _check_structure(pack, result.owners)
    return result


def render_report(result: VerificationResult) -> str:
    """
    Render the verification result as markdown the designer can print verbatim.

    :param result: The verification result.
    :return: A markdown report.
    """
    lines: list[str] = ["## Standards coverage (verified)"]
    if result.provenance:
        lines.append("")
        lines.append(f"_Pack: {result.provenance}_")
    lines.append("")
    lines.append("| Standard | Role | Owned by | Fidelity |")
    lines.append("|---|---|---|---|")

    infidelity_ids: set[str] = {mismatch["standard_id"] for mismatch in result.infidelities}
    for standard_id in sorted(set(result.roles) | set(result.owners)):
        owners: list[str] = result.owners.get(standard_id, [])
        if not owners:
            owner_cell: str = "**not embedded**"
            fidelity_cell: str = "-"
        else:
            owner_cell = ", ".join(f"`{name}`" for name in sorted(set(owners)))
            if len(set(owners)) > 1:
                owner_cell = f"{owner_cell} **(ambiguous)**"
            fidelity_cell = "**altered**" if standard_id in infidelity_ids else "verbatim"
        lines.append(f"| **{standard_id}** | {result.roles.get(standard_id, '-')} | {owner_cell} | {fidelity_cell} |")

    lines.append("")
    if result.ok:
        lines.append("Every standard is embedded exactly once, verbatim, with a valid id.")
    else:
        lines.append("**This network did not verify clean:**")
        lines.append("")
        lines.extend(f"- {problem}" for problem in result.problems())

    if result.pack_warnings:
        lines.append("")
        lines.append("**Pack warnings** (under-specified, but the standards are intact):")
        lines.append("")
        lines.extend(f"- {problem}" for problem in result.pack_warnings)

    return "\n".join(lines)


# --------------------------------------------------------------------------------------
# Offline use: read a generated network file rather than a live sly_data definition
# --------------------------------------------------------------------------------------


def network_definition_from_hocon(path: str | Path) -> dict[str, Any]:
    """
    Read a generated agent network HOCON file into the agent-name-to-definition shape.

    Lets the same checks run over files already on disk - in CI, in a pre-commit hook, or over
    a directory of previously generated networks - without an agent runtime.

    :param path: Path to a generated .hocon file.
    :return: Mapping of agent name to a definition carrying its "instructions".
    :raises ValueError: If the file cannot be parsed as an agent network.
    """
    try:
        config: Any = ConfigFactory.parse_file(str(path))
    except Exception as exception:
        raise ValueError(f"Could not parse {path}: {exception}") from exception

    tools: Any = config.get("tools", None)
    if not tools:
        raise ValueError(f"{path} declares no tools; it does not look like an agent network.")

    definition: dict[str, Any] = {}
    for entry in tools:
        entry_dict: dict[str, Any] = dict(entry)
        name: str = str(entry_dict.get("name", "")).strip()
        if not name:
            continue
        definition[name] = {
            "instructions": str(entry_dict.get("instructions", "") or ""),
            "tools": list(entry_dict.get("tools", []) or []),
        }
    return definition


def main(argv: list[str] | None = None) -> int:
    """
    Command line entry point: verify a generated network file against a curated domain.

    :param argv: Argument vector, or None to read sys.argv.
    :return: 0 when verification passes, 1 when it fails, 2 on a usage error.
    """
    parser = argparse.ArgumentParser(
        description="Verify that a generated agent network carries its domain's operating standards."
    )
    parser.add_argument("network", help="path to a generated agent network .hocon file")
    parser.add_argument("--domain", required=True, help=f"curated domain; available: {', '.join(discover_domains())}")
    parser.add_argument("--knowdocs", default=None, help="override the knowdocs root")
    arguments = parser.parse_args(argv)

    try:
        pack: KnowledgePack = load_pack(arguments.domain, arguments.knowdocs)
    except (FileNotFoundError, OSError) as exception:
        print(f"Error: {exception}", file=sys.stderr)
        return 2

    try:
        definition: dict[str, Any] = network_definition_from_hocon(arguments.network)
    except ValueError as exception:
        print(f"Error: {exception}", file=sys.stderr)
        return 2

    result: VerificationResult = verify(pack, definition)
    print(render_report(result))
    return 0 if result.ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
