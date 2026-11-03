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


@dataclass(frozen=True)
class Standard:
    """
    One operating standard: an invariant rule with a stable id. The role (precondition, work or postcondition)
    comes from the pack manifest and decides which agent owns the standard.
    """

    standard_id: str
    text: str
    role: str | None = None
