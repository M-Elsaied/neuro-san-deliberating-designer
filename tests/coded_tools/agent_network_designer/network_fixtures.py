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
Reference networks and build-failure mutations, for benchmarking the standards verifier.

The verifier's job is to notice when the agent that writes instructions did not preserve a
standard. Testing that needs two things this module supplies:

  * ``reference_network(pack)`` - what a CORRECTLY built network for a pack looks like. Built from
    the pack's own declared roles, so it is derived rather than hand-written, and adding a domain
    gives you its reference network for free.
  * ``MUTATIONS`` - a catalogue of the specific ways a language model degrades embedded text, each
    paired with the finding the verifier is expected to produce.

Two mutations are expected to verify CLEAN. Those matter most: a fidelity check that fires on
re-wrapped text or a swapped dash is noise, and noise gets switched off. Without them the suite
would only prove the check is strict, not that it is right.

Not named test_*, so pytest does not collect it as a test module.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack
from coded_tools.agent_network_designer.knowledge_pack import Standard

# Agent names are deliberately domain-neutral: the topology comes from the pack's declared roles,
# not from knowing anything about databases or clusters.
COORDINATOR: str = "coordinator"
GATE: str = "readiness_gate"
OPERATOR: str = "operator"
VALIDATOR: str = "validator"

_ROLE_OWNERS: dict[str, str] = {
    "precondition": GATE,
    "work": OPERATOR,
    "postcondition": VALIDATOR,
}


def must_line(standard: Standard) -> str:
    """
    Render one standard the way the instructions-writing agent is told to.

    :param standard: The standard to render.
    :return: A single ``MUST: <text> [<id>]`` line.
    """
    return f"MUST: {standard.text} [{standard.standard_id}]"


def owner_of(standard: Standard) -> str:
    """
    Decide which agent owns a standard, from its declared temporal role.

    :param standard: The standard to place.
    :return: The owning agent's name. Standards with no declared role go to the operator.
    """
    return _ROLE_OWNERS.get(standard.role or "", OPERATOR)


def reference_network(pack: KnowledgePack) -> dict[str, Any]:
    """
    Build the network a correct build of this pack would produce.

    Every standard is embedded verbatim, exactly once, in the agent its role implies: preconditions
    gate, work operates, postconditions validate and own hand-back.

    :param pack: The loaded knowledge pack.
    :return: An agent network definition, as agent name to definition.
    """
    instructions: dict[str, list[str]] = {
        COORDINATOR: ["You plan the work and sequence the other agents."],
        GATE: ["You refuse to release the work until every precondition below holds."],
        OPERATOR: ["You perform the operation itself, only once the gate has released it."],
        VALIDATOR: ["You own hand-back and refuse it until every postcondition below passes."],
    }
    for standard in pack.standards:
        instructions[owner_of(standard)].append(must_line(standard))

    network: dict[str, Any] = {}
    for name, lines in instructions.items():
        # An agent that ended up owning no standards still belongs in the network, but only the
        # coordinator is guaranteed to exist for every pack.
        if name != COORDINATOR and len(lines) == 1:
            continue
        network[name] = {"instructions": "\n".join(lines), "description": f"{name} responsibilities"}
    network[COORDINATOR]["tools"] = [name for name in network if name != COORDINATOR]
    return network


def _replace_in_agent(network: dict[str, Any], agent: str, old: str, new: str) -> dict[str, Any]:
    """
    Return a copy of the network with one substring swapped inside one agent's instructions.

    :param network: The network to copy.
    :param agent: The agent whose instructions to edit.
    :param old: The substring to replace.
    :param new: Its replacement.
    :return: The edited copy.
    """
    mutated: dict[str, Any] = {name: dict(definition) for name, definition in network.items()}
    mutated[agent]["instructions"] = mutated[agent]["instructions"].replace(old, new)
    return mutated


def _paraphrase(network: dict[str, Any], pack: KnowledgePack) -> dict[str, Any]:
    """
    Reword a standard while keeping its id - the failure verbatim embedding exists to prevent.

    :param network: The reference network.
    :param pack: The pack it was built from.
    :return: The mutated network.
    """
    standard: Standard = pack.standards[0]
    reworded: str = f"MUST: In summary, {standard.text.split()[0].lower()} as required. [{standard.standard_id}]"
    return _replace_in_agent(network, owner_of(standard), must_line(standard), reworded)


def _truncate(network: dict[str, Any], pack: KnowledgePack) -> dict[str, Any]:
    """
    Drop the tail of a standard, keeping a plausible-looking opening clause.

    :param network: The reference network.
    :param pack: The pack it was built from.
    :return: The mutated network.
    """
    standard: Standard = pack.standards[0]
    words: list[str] = standard.text.split()
    shortened: str = " ".join(words[: max(2, len(words) // 2)])
    return _replace_in_agent(
        network, owner_of(standard), must_line(standard), f"MUST: {shortened} [{standard.standard_id}]"
    )


def _drop(network: dict[str, Any], pack: KnowledgePack) -> dict[str, Any]:
    """
    Omit a standard entirely, as a model summarising a long list would.

    :param network: The reference network.
    :param pack: The pack it was built from.
    :return: The mutated network.
    """
    standard: Standard = pack.standards[-1]
    return _replace_in_agent(network, owner_of(standard), f"\n{must_line(standard)}", "")


def _duplicate_across_agents(network: dict[str, Any], pack: KnowledgePack) -> dict[str, Any]:
    """
    Embed one standard in a second agent too, so nobody actually owns it.

    :param network: The reference network.
    :param pack: The pack it was built from.
    :return: The mutated network.
    """
    standard: Standard = pack.standards[0]
    mutated: dict[str, Any] = {name: dict(definition) for name, definition in network.items()}
    mutated[COORDINATOR]["instructions"] += f"\n{must_line(standard)}"
    return mutated


def _invent(network: dict[str, Any], pack: KnowledgePack) -> dict[str, Any]:
    """
    Add a confident-sounding rule under an id the pack does not define.

    :param network: The reference network.
    :param pack: The pack it was built from.
    :return: The mutated network.
    """
    prefix: str = pack.standards[0].standard_id.split("-")[0]
    mutated: dict[str, Any] = {name: dict(definition) for name, definition in network.items()}
    mutated[COORDINATOR]["instructions"] += f"\nMUST: Always obtain two independent approvals [{prefix}-99]"
    return mutated


def _rewrap_and_smarten(network: dict[str, Any], _pack: KnowledgePack) -> dict[str, Any]:
    """
    Re-wrap every standard across lines and swap in typographic punctuation.

    Pure rendering: no word changes. This must verify CLEAN, or the fidelity check is noise.

    :param network: The reference network.
    :param _pack: Unused; present so every mutation shares one signature.
    :return: The mutated network.
    """
    mutated: dict[str, Any] = {}
    for name, definition in network.items():
        updated: dict[str, Any] = dict(definition)
        lines: list[str] = []
        for line in str(definition.get("instructions", "")).splitlines():
            match: re.Match | None = re.match(r"^MUST: (.*) \[([^\]]+)\]$", line)
            if match is None:
                lines.append(line)
                continue
            body: str = match.group(1).replace("-", "–").replace("'", "’").replace('"', "“")
            words: list[str] = body.split()
            midpoint: int = max(1, len(words) // 2)
            first: str = " ".join(words[:midpoint])
            second: str = " ".join(words[midpoint:])
            # Non-breaking space in the continuation indent, on top of the wrap.
            lines.append(f"MUST: {first}\n    {second} [{match.group(2)}]")
        updated["instructions"] = "\n".join(lines)
        mutated[name] = updated
    return mutated


def _reindent(network: dict[str, Any], _pack: KnowledgePack) -> dict[str, Any]:
    """
    Indent and pad every line, as a model formatting a block would.

    Must verify CLEAN.

    :param network: The reference network.
    :param _pack: Unused; present so every mutation shares one signature.
    :return: The mutated network.
    """
    mutated: dict[str, Any] = {}
    for name, definition in network.items():
        updated: dict[str, Any] = dict(definition)
        text: str = str(definition.get("instructions", ""))
        updated["instructions"] = "\n".join(f"    {line}  " for line in text.splitlines())
        mutated[name] = updated
    return mutated


def _collapse_gate_into_work(network: dict[str, Any], _pack: KnowledgePack) -> dict[str, Any]:
    """
    Merge the gate's standards into the operator, so the gate is also the operation it guards.

    :param network: The reference network.
    :param _pack: Unused; present so every mutation shares one signature.
    :return: The mutated network.
    """
    mutated: dict[str, Any] = {name: dict(definition) for name, definition in network.items()}
    gate_lines: list[str] = [
        line for line in str(mutated[GATE]["instructions"]).splitlines() if line.startswith("MUST:")
    ]
    mutated[OPERATOR]["instructions"] += "\n" + "\n".join(gate_lines)
    del mutated[GATE]
    mutated[COORDINATOR]["tools"] = [name for name in mutated if name != COORDINATOR]
    return mutated


@dataclass(frozen=True)
class Mutation:
    """One way a build can go wrong, and the finding the verifier owes us for it."""

    name: str
    apply: Callable[[dict[str, Any], KnowledgePack], dict[str, Any]]
    expect_ok: bool
    expect_marker: str = ""
    needs_work_role: bool = False


MUTATIONS: tuple[Mutation, ...] = (
    Mutation("paraphrased_standard", _paraphrase, expect_ok=False, expect_marker="FIDELITY"),
    Mutation("truncated_standard", _truncate, expect_ok=False, expect_marker="FIDELITY"),
    Mutation("dropped_standard", _drop, expect_ok=False, expect_marker="is not embedded in any agent"),
    Mutation("duplicated_standard", _duplicate_across_agents, expect_ok=False, expect_marker="ambiguous"),
    Mutation("invented_standard", _invent, expect_ok=False, expect_marker="PROVENANCE"),
    Mutation("rewrapped_and_smartened", _rewrap_and_smarten, expect_ok=True),
    Mutation("reindented", _reindent, expect_ok=True),
    Mutation(
        "gate_collapsed_into_work",
        _collapse_gate_into_work,
        expect_ok=False,
        expect_marker="STRUCTURE",
        needs_work_role=True,
    ),
)
