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


@dataclass(frozen=True)
class PackManifest:  # pylint: disable=too-many-instance-attributes
    """
    Identity and provenance of a knowledge pack, read from its pack.hocon.
    """

    # Any uppercase prefix and a number, such as ODB-01, K8S-01 or SOP-4.2. Used when a pack declares no pattern.
    DEFAULT_STANDARD_ID_PATTERN: ClassVar[str] = r"[A-Z][A-Z0-9]*-[0-9.]+"

    domain_id: str
    title: str = ""
    summary: str = ""
    version: str = ""
    owner: str = ""
    approved_by: str = ""
    effective_date: str = ""
    # Free text for people reading the pack, such as the SOP it was derived from.
    source: str = ""
    standard_id_pattern: str = DEFAULT_STANDARD_ID_PATTERN
    roles: dict[str, str] = field(default_factory=dict)
    # True when the pack has no pack.hocon and its identity was inferred from the directory name.
    synthesized: bool = False

    def get_provenance(self) -> str:
        """
        Describe the pack in one line for a generated network's metadata.

        :return: One line naming the pack, its version, owner, approver and effective date, for a generated network.
        """
        parts: list[str] = [self.title or self.domain_id]
        if self.version:
            parts.append(f"v{self.version}")
        if self.owner:
            parts.append(f"owned by {self.owner}")
        if self.approved_by:
            parts.append(f"approved by {self.approved_by}")
        if self.effective_date:
            parts.append(f"effective {self.effective_date}")
        return ", ".join(parts)
