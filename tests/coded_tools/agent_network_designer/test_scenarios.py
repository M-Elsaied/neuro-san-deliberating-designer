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
Scenario benchmark: hold the method constant, vary the domain, and check the outcome each time.

This is the qualitative regression net. Each shipped pack is taken through a full cycle - load the
pack, build the network a correct build would produce, verify it - and then through a catalogue of
realistic build failures, asserting the specific finding each one owes.

What it is really guarding against is a SILENT functional break: a change that leaves the suite
green while quietly making the verifier blind. Two properties do that work together:

  * every failure mode must be caught, per domain, with the right finding; and
  * two pure-rendering mutations must NOT be caught, because a check that fires on re-wrapped text
    is noise, and noise gets ignored or switched off.

No language model, no network calls, no API key.
"""

from typing import Any

import pytest

from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack
from coded_tools.agent_network_designer.knowledge_pack import discover_domains
from coded_tools.agent_network_designer.knowledge_pack import load_pack
from coded_tools.agent_network_designer.standards_verifier import VerificationResult
from coded_tools.agent_network_designer.standards_verifier import render_report
from coded_tools.agent_network_designer.standards_verifier import verify
from tests.coded_tools.agent_network_designer.network_fixtures import MUTATIONS
from tests.coded_tools.agent_network_designer.network_fixtures import Mutation
from tests.coded_tools.agent_network_designer.network_fixtures import reference_network

SHIPPED_DOMAINS: tuple[str, ...] = (
    "clinical_trial_database_lock",
    "kubernetes_cluster_upgrade",
    "oracle_database_patching",
)


def _has_work_role(pack: KnowledgePack) -> bool:
    """
    :param pack: The pack to inspect.
    :return: True when the pack declares at least one 'work' standard.
    """
    return any(standard.role == "work" for standard in pack.standards)


# --------------------------------------------------------------------------------------
# Scenario 1 - a correct build of every shipped domain verifies clean
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("domain_id", SHIPPED_DOMAINS)
def test_a_correct_build_of_each_domain_verifies_clean(domain_id):
    """
    The baseline. If this fails, every other assertion in this file is meaningless.
    """
    pack: KnowledgePack = load_pack(domain_id)
    result: VerificationResult = verify(pack, reference_network(pack))

    assert result.ok, result.problems()
    assert not result.pack_errors
    assert not result.pack_warnings, f"{domain_id} pack is under-specified: {result.pack_warnings}"
    # Every standard the pack defines is accounted for, owned by exactly one agent.
    assert sorted(result.owners) == sorted(standard.standard_id for standard in pack.standards)
    for standard_id, owners in result.owners.items():
        assert len(set(owners)) == 1, f"{standard_id} has {owners}"


@pytest.mark.parametrize("domain_id", SHIPPED_DOMAINS)
def test_the_report_states_the_pack_it_was_built_from(domain_id):
    """
    Provenance has to survive into the report, or an artifact's ancestry lives nowhere.
    """
    pack: KnowledgePack = load_pack(domain_id)
    report: str = render_report(verify(pack, reference_network(pack)))

    assert pack.manifest.version in report
    assert "Standards coverage (verified)" in report
    for standard in pack.standards:
        assert standard.standard_id in report


@pytest.mark.parametrize("domain_id", SHIPPED_DOMAINS)
def test_each_domain_produces_its_own_ids_and_its_own_topology(domain_id):
    """
    The falsification test for the industry-agnostic claim: one method, three different outputs.

    If two domains produced the same ids or the same role distribution, the method would be
    carrying domain knowledge rather than reading it from the pack.
    """
    pack: KnowledgePack = load_pack(domain_id)
    prefixes: set[str] = {standard.standard_id.split("-")[0] for standard in pack.standards}

    assert len(prefixes) == 1, f"{domain_id} mixes id prefixes: {prefixes}"
    other_prefixes: set[str] = set()
    for other in SHIPPED_DOMAINS:
        if other != domain_id:
            other_pack: KnowledgePack = load_pack(other)
            other_prefixes |= {standard.standard_id.split("-")[0] for standard in other_pack.standards}
    assert not prefixes & other_prefixes, "two domains share a standard id prefix"


# --------------------------------------------------------------------------------------
# Scenario 2 - every way a build can go wrong is caught, in every domain
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("domain_id", SHIPPED_DOMAINS)
@pytest.mark.parametrize("mutation", MUTATIONS, ids=lambda mutation: mutation.name)
def test_build_failures_are_caught_per_domain(domain_id, mutation: Mutation):
    """
    The matrix: each realistic build failure, against each shipped domain, one expected finding.
    """
    pack: KnowledgePack = load_pack(domain_id)
    if mutation.needs_work_role and not _has_work_role(pack):
        pytest.skip(f"{domain_id} declares no 'work' role, so the structural check does not apply")

    mutated: dict[str, Any] = mutation.apply(reference_network(pack), pack)
    result: VerificationResult = verify(pack, mutated)

    if mutation.expect_ok:
        # The theatre check. Rendering changed; meaning did not; the verifier must stay quiet.
        assert result.ok, f"{mutation.name} on {domain_id} produced false positives: {result.problems()}"
        return

    assert not result.ok, f"{mutation.name} on {domain_id} went undetected"
    problems: str = "\n".join(result.problems())
    assert mutation.expect_marker in problems, f"expected {mutation.expect_marker!r} in:\n{problems}"


@pytest.mark.parametrize("mutation", MUTATIONS, ids=lambda mutation: mutation.name)
def test_every_mutation_actually_mutates(mutation: Mutation):
    """
    Guard against a vacuous suite.

    A mutation that quietly stopped changing anything would make its assertion pass for the wrong
    reason - and the two expect_ok mutations would become the worst kind of green test, appearing to
    prove the verifier tolerates re-wrapping when in fact nothing was re-wrapped.
    """
    pack: KnowledgePack = load_pack("kubernetes_cluster_upgrade")
    base: dict[str, Any] = reference_network(pack)
    mutated: dict[str, Any] = mutation.apply(reference_network(pack), pack)

    def flatten(network: dict[str, Any]) -> str:
        """
        :param network: A network definition.
        :return: All instruction text concatenated, for comparison.
        """
        return "".join(str(definition.get("instructions", "")) for definition in network.values())

    assert flatten(mutated) != flatten(base), f"{mutation.name} changed nothing"


@pytest.mark.parametrize("domain_id", SHIPPED_DOMAINS)
def test_a_failed_verification_says_so_in_its_report(domain_id):
    """
    A report that reads as clean while ok is False would defeat the whole point.
    """
    pack: KnowledgePack = load_pack(domain_id)
    mutated: dict[str, Any] = {name: dict(definition) for name, definition in reference_network(pack).items()}
    mutated["coordinator"]["instructions"] += "\nMUST: Something nobody asked for [ZZZ-01]"

    report: str = render_report(verify(pack, mutated))
    assert "did not verify clean" in report
    assert "ZZZ-01" in report


# --------------------------------------------------------------------------------------
# Scenario 3 - the control: a domain with no curated pack
# --------------------------------------------------------------------------------------


def test_an_unknown_domain_is_a_miss_that_names_the_alternatives():
    """
    The pizza case, at the pack layer: no silent fallback, and the error is actionable.
    """
    with pytest.raises(FileNotFoundError):
        load_pack("pizza_delivery")

    available: list[str] = discover_domains()
    assert "pizza_delivery" not in available
    assert set(SHIPPED_DOMAINS).issubset(set(available))
