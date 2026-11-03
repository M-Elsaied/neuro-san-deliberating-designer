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

import asyncio
import logging
from typing import Any

from neuro_san.interfaces.coded_tool import CodedTool

from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack
from coded_tools.agent_network_designer.pack_catalog import PackCatalog
from coded_tools.agent_network_designer.pack_reader import PackReader

logger = logging.getLogger(__name__)


class ListDomains(CodedTool):
    """
    CodedTool that lists the knowledge domains on this deployment, so the designer's prompt names none itself.
    """

    def invoke(self, args: dict[str, Any], sly_data: dict[str, Any]) -> dict[str, Any] | str:
        """
        List every knowledge pack on this deployment.

        :param args: No keys are read.
        :param sly_data: No keys are read.
        :return: "domains", one entry per pack with its "id", "title", "summary", "version" and "standard_ids",
            and their "count"; or an "Error: ..." string when the deployment has no packs.
        """
        packs: list[KnowledgePack] = PackCatalog.load_catalog()
        if not packs:
            return (
                f"Error: No curated knowledge domains found under {PackReader.get_knowdocs_root()}. "
                f"The designer can still proceed on general knowledge, but must say so."
            )

        domains: list[dict[str, Any]] = []
        for pack in packs:
            standard_ids: list[str] = []
            for standard in pack.standards:
                standard_ids.append(standard.standard_id)
            domains.append(
                {
                    "id": pack.domain_id,
                    "title": pack.manifest.title or pack.domain_id,
                    "summary": pack.manifest.summary,
                    "version": pack.manifest.version,
                    "standard_ids": standard_ids,
                }
            )
        logger.debug("Curated knowledge catalog: %d domain(s)", len(domains))
        return {"domains": domains, "count": len(domains)}

    async def async_invoke(self, args: dict[str, Any], sly_data: dict[str, Any]) -> dict[str, Any] | str:
        """
        Runs invoke() in a worker thread, since it reads every pack from disk.

        :param args: See invoke().
        :param sly_data: See invoke().
        :return: See invoke().
        """
        return await asyncio.to_thread(self.invoke, args, sly_data)
