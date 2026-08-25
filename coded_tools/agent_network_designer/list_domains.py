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
Report which curated knowledge domains are available, at run time.

A language model only learns that a tool exists, and what it can be asked for, from that tool's
written description - the description is the interface, not documentation. So listing the
available domains inside a tool description means the catalogue is hardcoded into the designer's
prompt, and a deployment cannot add a domain without editing the prompt as well as the code.

This tool removes that coupling. The designer asks what exists instead of being told, so the
method layer contains no domain nouns at all: L1 purity enforced structurally rather than by
discipline. Dropping a folder into the knowdocs root is sufficient to make a domain reachable.
"""

import logging
from typing import Any

from neuro_san.interfaces.coded_tool import CodedTool

from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack
from coded_tools.agent_network_designer.knowledge_pack import knowdocs_root
from coded_tools.agent_network_designer.knowledge_pack import load_catalogue

logger = logging.getLogger(__name__)


class ListDomains(CodedTool):
    """CodedTool that lists the curated knowledge domains discoverable on this deployment."""

    def invoke(self, args: dict[str, Any], sly_data: dict[str, Any]) -> dict[str, Any] | str:
        """
        :param args: An argument dictionary. No keys are required.

        :param sly_data: A dictionary whose keys are defined by the agent hierarchy, but whose
            values are meant to be kept out of the chat stream.

            Keys expected for this implementation are:
                None

        :return:
            If successful:
                A dictionary with the keys:
                - "domains" (list): one entry per domain, each with "id", "title", "summary",
                  "version" and "standard_ids".
                - "count" (int): how many domains were found.
            Otherwise:
                A text string error message in the format:
                "Error: <error message>"
        """
        packs: list[KnowledgePack] = load_catalogue()
        if not packs:
            return (
                f"Error: No curated knowledge domains found under {knowdocs_root()}. "
                f"The designer can still proceed on general knowledge, but must say so."
            )

        domains: list[dict[str, Any]] = []
        for pack in packs:
            domains.append(
                {
                    "id": pack.domain_id,
                    "title": pack.manifest.title or pack.domain_id,
                    "summary": pack.manifest.summary,
                    "version": pack.manifest.version,
                    "standard_ids": [standard.standard_id for standard in pack.standards],
                }
            )

        logger.debug("Curated knowledge catalogue: %d domain(s)", len(domains))
        return {"domains": domains, "count": len(domains)}

    async def async_invoke(self, args: dict[str, Any], sly_data: dict[str, Any]) -> dict[str, Any] | str:
        """
        Delegates to the synchronous implementation: this is a directory scan.

        :param args: See invoke().
        :param sly_data: See invoke().
        :return: See invoke().
        """
        return self.invoke(args, sly_data)
