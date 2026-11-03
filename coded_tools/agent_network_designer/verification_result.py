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

from coded_tools.agent_network_designer.embedded_standard import EmbeddedStandard


@dataclass
class VerificationResult:  # pylint: disable=too-many-instance-attributes
    """
    The computed outcome of verifying one generated network against one knowledge pack.
    """

    domain_id: str
    provenance: str = ""
    # Standard id to its declared role, or "-" when it has none.
    roles: dict[str, str] = field(default_factory=dict)
    # Standard id to every agent that embeds it.
    owners: dict[str, list[str]] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    ambiguous: list[str] = field(default_factory=list)
    unknown: list[EmbeddedStandard] = field(default_factory=list)
    # One entry per altered standard, with "standard_id", "agent_name" and "detail" keys.
    infidelities: list[dict[str, str]] = field(default_factory=list)
    structural: list[str] = field(default_factory=list)
    pack_errors: list[str] = field(default_factory=list)
    pack_warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """
        Report whether the network carries the pack faithfully.

        :return: True when every check passed and the pack has no errors. Pack warnings do not affect it.
        """
        return not (
            self.missing or self.ambiguous or self.unknown or self.infidelities or self.structural or self.pack_errors
        )
