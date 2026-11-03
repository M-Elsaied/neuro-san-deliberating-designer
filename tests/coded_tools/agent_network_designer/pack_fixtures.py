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

import copy
import os
from pathlib import Path
from typing import Any
from unittest import TestCase
from unittest import mock

from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack
from coded_tools.agent_network_designer.open_variable import OpenVariable
from coded_tools.agent_network_designer.pack_manifest import PackManifest
from coded_tools.agent_network_designer.pack_reader import PackReader
from coded_tools.agent_network_designer.standard import Standard


class PackFixtures:
    """
    Shared helpers for the agent network designer tests: packs written to disk, the knowdocs root a test reads,
    and the network a correct build of a pack produces.
    """

    # The packs this repository ships. A deployment may add more, so tests check these are present, not alone.
    SHIPPED_DOMAINS: tuple[str, ...] = (
        "clinical_trial_database_lock",
        "kubernetes_cluster_upgrade",
        "oracle_database_patching",
    )
    VARIABLES: str = "- V1 | A question? | examples: a; b | why: it matters.\n"
    # The in-memory equivalents, for packs assembled without touching disk.
    MANIFEST: PackManifest = PackManifest("demo", version="1.0", standard_id_pattern=r"ABC-\d{2}")
    VARIABLE: OpenVariable = OpenVariable("V1", "A question?", "a; b", "it matters.")
    # Which agent of the reference network owns a standard with each role.
    ROLE_OWNERS: dict[str, str] = {"precondition": "readiness_gate", "work": "operator", "postcondition": "validator"}

    @staticmethod
    def use_knowdocs_root(test_case: TestCase, root: Path | None) -> None:
        """
        Point PackReader at a root for the rest of a test, or at the shipped packs when root is None.

        :param test_case: The running test, which undoes the change on cleanup.
        :param root: The knowdocs root to use, or None for the shipped packs.
        """
        patcher: Any = mock.patch.dict(os.environ)
        patcher.start()
        test_case.addCleanup(patcher.stop)
        os.environ.pop(PackReader.KNOWDOCS_ENV_VAR, None)
        if root is not None:
            os.environ[PackReader.KNOWDOCS_ENV_VAR] = str(root)

    @staticmethod
    def load_shipped_pack(test_case: TestCase, domain_id: str) -> KnowledgePack:
        """
        Load one of the packs this repository ships, whatever AGENT_NETWORK_DESIGNER_KNOWDOCS says.

        :param test_case: The running test, which restores the environment on cleanup.
        :param domain_id: The shipped domain to load.
        :return: The loaded pack.
        """
        PackFixtures.use_knowdocs_root(test_case, None)
        return PackReader.load_pack(domain_id)

    @staticmethod
    def build_pack(
        standards: list[Standard],
        manifest: PackManifest = MANIFEST,
        variables: tuple[OpenVariable, ...] = (VARIABLE,),
        unloaded: list[dict[str, str]] | None = None,
    ) -> KnowledgePack:
        """
        Assemble a pack in memory.

        :param standards: The pack's standards.
        :param manifest: The pack's manifest.
        :param variables: The pack's open variables.
        :param unloaded: The bullets that were not loaded, with "standard_id" and "reason" keys.
        :return: The pack.
        """
        return KnowledgePack(
            manifest=manifest, standards=standards, open_variables=list(variables), unloaded_standards=unloaded or []
        )

    @staticmethod
    def write_pack(root: Path, domain_id: str, standards: str, manifest: str | None = None) -> Path:
        """
        Write a pack, with the shared open variables, to disk.

        :param root: The knowdocs root to write under.
        :param domain_id: The pack directory name.
        :param standards: The operating_standards.md text.
        :param manifest: The pack.hocon text, or None to leave the pack without one.
        :return: The pack directory.
        """
        directory: Path = root / domain_id
        directory.mkdir(parents=True)
        (directory / PackReader.STANDARDS_FILENAME).write_text(standards, encoding="utf-8")
        (directory / PackReader.VARIABLES_FILENAME).write_text(PackFixtures.VARIABLES, encoding="utf-8")
        if manifest is not None:
            (directory / PackReader.MANIFEST_FILENAME).write_text(manifest, encoding="utf-8")
        return directory

    @staticmethod
    def get_must_line(standard: Standard) -> str:
        """
        Render a standard the way the designer embeds it.

        :param standard: The standard to embed.
        :return: The standard as the designer embeds it in an agent's instructions.
        """
        return f"MUST: {standard.text} [{standard.standard_id}]"

    @staticmethod
    def build_reference_network(pack: KnowledgePack) -> dict[str, Any]:
        """
        Build the network a correct build of a pack produces.

        :param pack: The pack to build for.
        :return: A network embedding each standard once, verbatim, in the agent its role implies.
        """
        coordinator: dict[str, Any] = {"instructions": "You sequence the other agents.", "tools": []}
        network: dict[str, Any] = {"coordinator": coordinator}
        for standard in pack.standards:
            owner: str = PackFixtures.ROLE_OWNERS.get(standard.role or "work", "operator")
            if owner not in network:
                network[owner] = {"instructions": f"You own the {owner} step."}
                coordinator.get("tools").append(owner)
            agent: dict[str, Any] = network.get(owner)
            agent["instructions"] = f"{agent.get('instructions')}\n{PackFixtures.get_must_line(standard)}"
        return network

    @staticmethod
    def replace_in_network(network: dict[str, Any], old: str, new: str) -> dict[str, Any]:
        """
        Copy a network with text replaced in every agent's instructions.

        :param network: The network to copy.
        :param old: Text to replace in every agent's instructions.
        :param new: Its replacement.
        :return: The edited copy.
        """
        changed: dict[str, Any] = copy.deepcopy(network)
        for agent in changed.values():
            agent["instructions"] = str(agent.get("instructions", "")).replace(old, new)
        return changed

    @staticmethod
    def append_to_agent(network: dict[str, Any], agent_name: str, text: str) -> dict[str, Any]:
        """
        Copy a network with a line appended to one agent's instructions.

        :param network: The network to copy.
        :param agent_name: The agent whose instructions to extend.
        :param text: The line to append.
        :return: The edited copy.
        """
        changed: dict[str, Any] = copy.deepcopy(network)
        agent: dict[str, Any] = changed.get(agent_name)
        agent["instructions"] = f"{agent.get('instructions', '')}\n{text}"
        return changed
