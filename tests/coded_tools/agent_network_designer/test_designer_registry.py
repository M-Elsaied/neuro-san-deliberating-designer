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
from pathlib import Path
from typing import Any
from unittest import TestCase

from neuro_san.internals.run_context.langchain.core.langchain_openai_function_tool import LangChainOpenAIFunctionTool
from pyhocon import ConfigFactory

from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack


class TestDesignerRegistry(TestCase):
    """
    Contract tests over registries/agent_network_designer.hocon: neuro-san accepts every tool it declares, the
    front man can reach the curated knowledge tools, and the prompt keeps its phase gate and names no domain.
    """

    REGISTRY_PATH: Path = Path("registries/agent_network_designer.hocon")
    CODED_TOOLS_DIR: Path = Path("coded_tools/agent_network_designer")
    KNOWLEDGE_TOOLS: tuple[str, ...] = ("ListDomains", "ExtractDocs", "VerifyStandards")
    BUILDING_TOOLS: tuple[str, ...] = (
        "agent_network_editor",
        "agent_network_instructions_editor",
        "agent_network_query_generator",
    )
    # Vocabulary from the shipped packs. A domain noun in the designer's own prompt biases every other domain.
    DOMAIN_NOUNS: tuple[str, ...] = (
        "oracle",
        "rman",
        "opatch",
        "datapatch",
        "exadata",
        "rac",
        "data guard",
        "kubernetes",
        "etcd",
        "poddisruptionbudget",
        "kubelet",
        "aks",
        "eks",
        "clinical",
        "meddra",
        "whodrug",
        "unblinding",
        "sdv",
        "servicenow",
    )

    @classmethod
    def setUpClass(cls) -> None:
        """
        Parse the registry once. Its includes are relative to the repository root, as the server loads them, so
        it is parsed as a string from there rather than with parse_file.
        """
        registry: Any = ConfigFactory.parse_string(cls.REGISTRY_PATH.read_text(encoding="utf-8"))
        cls.agents: list[dict[str, Any]] = []
        for entry in registry.get("tools"):
            cls.agents.append(dict(entry))
        # By neuro-san convention the front man is the first entry.
        cls.front_man: dict[str, Any] = cls.agents[0]
        cls.instructions: str = re.sub(r"\s+", " ", str(cls.front_man.get("instructions") or ""))

    def test_neuro_san_accepts_every_tool_declaration(self) -> None:
        """
        Parsing is not acceptance: an empty "properties" block parses but makes neuro-san refuse to build the tool.
        """
        for agent in self.agents:
            function: Any = agent.get("function")
            if function is None:
                continue
            with self.subTest(tool=agent.get("name")):
                function_json: dict[str, Any] = dict(function)
                function_json.setdefault("name", agent.get("name"))
                LangChainOpenAIFunctionTool.verify_function_json(function_json)

    def test_every_coded_tool_class_resolves_to_a_module(self) -> None:
        """
        A class that does not resolve fails only when the network loads.
        """
        for agent in self.agents:
            class_reference: str = str(agent.get("class") or "")
            if class_reference:
                with self.subTest(class_reference=class_reference):
                    module_name: str = class_reference.split(".", maxsplit=1)[0]
                    self.assertTrue((self.CODED_TOOLS_DIR / f"{module_name}.py").is_file())

    def test_the_front_man_can_call_the_knowledge_tools(self) -> None:
        """
        A tool nobody lists is a tool nobody calls.
        """
        declared: list[str] = []
        for agent in self.agents:
            declared.append(str(agent.get("name")))
        wired: list[str] = list(self.front_man.get("tools"))
        for tool in self.KNOWLEDGE_TOOLS:
            with self.subTest(tool=tool):
                self.assertIn(tool, declared)
                self.assertIn(tool, wired)

    def test_pack_provenance_survives_between_turns(self) -> None:
        """
        Session sly_data is rebuilt from the client each turn, so the provenance ExtractDocs records during the
        interview reaches persistence only if it is allowed upstream.
        """
        allow: dict[str, Any] = dict(self.front_man.get("allow") or {})
        upstream: dict[str, Any] = dict(allow.get("to_upstream") or {})
        self.assertIn(KnowledgePack.PROVENANCE_KEY, list(upstream.get("sly_data", [])))

    def test_the_prompt_names_no_domain(self) -> None:
        """
        Covers the front man's instructions and every tool description, since a description is how the model
        learns what a tool is for.
        """
        surfaces: dict[str, str] = {"front man instructions": self.instructions}
        for agent in self.agents:
            function: Any = agent.get("function")
            if function is not None:
                surfaces[f"{agent.get('name')} description"] = str(dict(function).get("description") or "")
        for where, text in surfaces.items():
            for noun in self.DOMAIN_NOUNS:
                with self.subTest(where=where, noun=noun):
                    self.assertIsNone(re.search(rf"\b{re.escape(noun)}\b", text.lower()))

    def test_phase_a_cannot_build_and_phase_b_prints_the_computed_table(self) -> None:
        """
        The phase gate is the feature, and the model must not write the table that certifies its own work.
        """
        phase_a, _, phase_b = self.instructions.partition("PHASE B - BUILD")
        self.assertIn("PHASE A - DELIBERATE", phase_a)
        for tool in self.BUILDING_TOOLS:
            with self.subTest(tool=tool):
                self.assertIn(tool, phase_a)
        self.assertIn("ListDomains", phase_a)
        self.assertIn("VerifyStandards", phase_b)
        self.assertIn("Do NOT write the coverage table yourself", phase_b)
        self.assertNotIn("| Standard | Owned by |", self.instructions)

    def test_the_shared_scoping_preamble_is_concatenated_onto_the_instructions(self) -> None:
        """
        A stray comma before the triple-quoted block turns the concatenation into a list and drops the preamble.
        """
        self.assertFalse(self.instructions.lstrip().startswith("You are responsible for designing"))

    def test_the_designer_lists_the_catalog_before_matching_a_domain(self) -> None:
        """
        Discovery is worthless if the prompt still assumes it knows which domains exist.
        """
        self.assertIn(
            "Call ListDomains to find out which curated domains this deployment actually has", self.instructions
        )
        self.assertIn("Never assume a domain exists without listing first", self.instructions)
