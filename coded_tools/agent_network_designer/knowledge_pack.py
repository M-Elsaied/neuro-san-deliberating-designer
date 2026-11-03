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

from dataclasses import dataclass
from dataclasses import field
from typing import ClassVar

from coded_tools.agent_network_designer.open_variable import OpenVariable
from coded_tools.agent_network_designer.pack_manifest import PackManifest
from coded_tools.agent_network_designer.standard import Standard


@dataclass(frozen=True)
class KnowledgePack:
    """
    A loaded knowledge pack: its manifest, its parsed standards and open variables, and every document verbatim.
    See docs/knowledge_packs.md for the format.
    """

    # sly_data key carrying the provenance of the pack a network is built from. The persistence middleware
    # stamps it into the generated network's metadata.
    PROVENANCE_KEY: ClassVar[str] = "agent_network_pack_provenance"

    manifest: PackManifest
    standards: list[Standard] = field(default_factory=list)
    open_variables: list[OpenVariable] = field(default_factory=list)
    documents: dict[str, str] = field(default_factory=dict)
    # Bullets that read as a standard but were not loaded, each with "standard_id" and "reason" keys, so
    # validation can report them.
    unloaded_standards: list[dict[str, str]] = field(default_factory=list)

    @property
    def domain_id(self) -> str:
        """
        Read the domain id from the manifest.

        :return: The pack's domain id.
        """
        return self.manifest.domain_id

    def get_standard(self, standard_id: str) -> Standard | None:
        """
        Look up one of the pack's standards by id.

        :param standard_id: The id to look up.
        :return: The standard with that id, or None if this pack does not define it.
        """
        for standard in self.standards:
            if standard.standard_id == standard_id:
                return standard
        return None
