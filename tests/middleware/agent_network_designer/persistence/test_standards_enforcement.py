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
Tests for the gate that stops an unfaithful network being persisted.

Verification used to be advisory everywhere: the report said a standard had been paraphrased or
invented, and the network was written anyway. That left the one guarantee this design provides
resting on someone noticing a line in a report - the same weakness as the model writing its own
coverage table, moved one step later.

The line these tests defend is which failures gate and which do not. A paraphrased standard and an
invented id are not judgement calls, so they block. Coverage, ambiguity and topology stay advisory,
because a network carrying five of six standards with the sixth flagged is genuinely useful and a
gate that refuses it would be turned off. Getting that boundary wrong in either direction is how
the check ends up either useless or disabled.

No language model: the checks are text comparison against the packs on disk.
"""

from typing import Any

import pytest

from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack
from coded_tools.agent_network_designer.pack_catalogue import load_pack
from middleware.agent_network_designer.persistence import agent_network_persistence_middleware as persistence
from middleware.agent_network_designer.persistence.agent_network_persistence_middleware import (
    AgentNetworkPersistenceMiddleware,
)
from tests.coded_tools.agent_network_designer.network_fixtures import reference_network

DOMAIN: str = "oracle_database_patching"


@pytest.fixture(name="pack")
def pack_fixture() -> KnowledgePack:
    """
    :return: The Oracle reference pack.
    """
    return load_pack(DOMAIN)


@pytest.fixture(name="middleware")
def middleware_fixture() -> AgentNetworkPersistenceMiddleware:
    """
    :return: The middleware, with no reservationist - the gate does not use one.
    """
    return AgentNetworkPersistenceMiddleware(reservationist=None, sly_data={})


def one_agent_carrying(text: str) -> dict[str, Any]:
    """
    :param text: The instructions for the single agent.
    :return: A one-agent network definition.
    """
    return {"only_agent": {"instructions": text}}


def test_a_faithful_network_is_not_blocked(middleware, pack):
    """
    The baseline. If this fires, the designer cannot build anything at all.
    """
    assert middleware._standards_errors(reference_network(pack)) == []  # pylint: disable=protected-access


def test_a_paraphrased_standard_blocks_persistence(middleware, pack):
    """
    The failure the verbatim design exists to prevent, and the one a human skim will not spot.

    A rule stated in words nobody in the domain agreed to is not a lesser version of the rule; it
    is a different rule wearing its id.
    """
    network: dict[str, Any] = {name: dict(value) for name, value in reference_network(pack).items()}
    target: str = pack.standards[2].standard_id
    for definition in network.values():
        definition["instructions"] = str(definition["instructions"]).replace(
            "Take a full RMAN backup", "Take an RMAN backup"
        )

    errors: list[str] = middleware._standards_errors(network)  # pylint: disable=protected-access

    assert errors, "a paraphrased standard must not reach disk"
    assert any(target in error and "word for word" in error for error in errors)
    # The message has to route to the agent that can fix it, or the repair loop cannot converge.
    assert any("agent_network_instructions_editor" in error for error in errors)


def test_an_invented_standard_id_blocks_persistence(middleware, pack):
    """
    A rule with no source is worse than no rule: it is unchallengeable and untraceable.
    """
    network: dict[str, Any] = {name: dict(value) for name, value in reference_network(pack).items()}
    first: str = next(iter(network))
    network[first]["instructions"] = str(network[first]["instructions"]) + "\nMUST: Always take two backups [ODB-99]"

    errors: list[str] = middleware._standards_errors(network)  # pylint: disable=protected-access

    assert any("ODB-99" in error and "does not define" in error for error in errors)


def test_a_missing_standard_does_not_block_persistence(middleware, pack):
    """
    The deliberate limit of the gate.

    A network covering five of six standards with the sixth reported is more useful than an
    exception, and a gate that refuses it gets switched off - taking the paraphrase check with it.
    Coverage is reported to the user in the computed table; it does not stop the build.
    """
    network: dict[str, Any] = {name: dict(value) for name, value in reference_network(pack).items()}
    dropped: str = pack.standards[-1].standard_id
    for definition in network.values():
        definition["instructions"] = "\n".join(
            line for line in str(definition["instructions"]).splitlines() if f"[{dropped}]" not in line
        )

    assert middleware._standards_errors(network) == []  # pylint: disable=protected-access


def test_a_network_built_without_curated_knowledge_is_not_blocked(middleware):
    """
    The pizza control case, at the persistence layer.

    A network designed on general knowledge embeds no curated ids, and must still be buildable -
    the designer tells the user its standards are unverified. Blocking here would mean the tool
    only works for domains someone has already written a pack for.
    """
    assert middleware._standards_errors(one_agent_carrying("Deliver the pizza promptly.")) == []  # pylint: disable=protected-access


def test_the_gate_can_be_turned_off(middleware, pack, monkeypatch):
    """
    It is a behaviour change, so a deployment that is not ready for it can opt out.
    """
    network: dict[str, Any] = {name: dict(value) for name, value in reference_network(pack).items()}
    for definition in network.values():
        definition["instructions"] = str(definition["instructions"]).replace(
            "Take a full RMAN backup", "Take an RMAN backup"
        )

    assert middleware._standards_errors(network)  # pylint: disable=protected-access
    monkeypatch.setattr(persistence, "ENFORCE_STANDARDS", False)
    assert middleware._standards_errors(network) == []  # pylint: disable=protected-access


def test_an_unreadable_knowdocs_root_does_not_stop_a_build(middleware, pack, monkeypatch):
    """
    This gate exists to catch a lossy build, not to make the designer depend on the filesystem.

    A knowdocs root that cannot be read is a deployment problem; turning it into "no network can be
    built" would be a far worse failure than the one being prevented.
    """

    def explode(*_args: Any, **_kwargs: Any) -> Any:
        raise OSError("knowdocs is on fire")

    monkeypatch.setattr(persistence, "load_catalogue", explode)

    assert middleware._standards_errors(reference_network(pack)) == []  # pylint: disable=protected-access


def test_standards_errors_reach_the_instructions_category(middleware, pack, monkeypatch):
    """
    Enforcement is wired through the EXISTING repair loop rather than a new refusal path.

    That matters more than it looks: the loop already hands the failure back to the instructions
    editor, retries within a budget, and - only if the wording still cannot be reproduced - ends
    without persisting. So the first outcome of a paraphrase is a correction, not a dead end.
    """
    network: dict[str, Any] = {name: dict(value) for name, value in reference_network(pack).items()}
    for definition in network.values():
        definition["instructions"] = str(definition["instructions"]).replace(
            "Take a full RMAN backup", "Take an RMAN backup"
        )

    async def no_errors(*_args: Any, **_kwargs: Any) -> list[str]:
        return []

    monkeypatch.setattr(persistence.AgentNetworkStructureValidationMiddleware, "validate", no_errors)
    monkeypatch.setattr(persistence.AgentNetworkInstructionsValidationMiddleware, "validate", no_errors)

    import asyncio  # pylint: disable=import-outside-toplevel

    structure_errors, instructions_errors = asyncio.run(
        middleware._validate_network(network)  # pylint: disable=protected-access
    )

    assert structure_errors == []
    assert instructions_errors, "a standards failure must arrive as an instructions failure"
    assert any("word for word" in error for error in instructions_errors)
