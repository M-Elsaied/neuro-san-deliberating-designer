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


@dataclass
class InterviewReviewResult:
    """
    The outcome of reviewing one recorded deliberation.
    """

    domain_id: str
    # Each as "<KIND>: turn <index>: <detail>", or "<KIND>: <detail>" for the transcript as a whole.
    findings: list[str] = field(default_factory=list)
    questions_asked: int = 0
    open_variables: int = 0
    standards_quoted: int = 0
    # Counted apart from questions: an ambiguous answer sent back finishes a question, and a revisit reopens one.
    clarifications: int = 0
    revisits: int = 0

    @property
    def ok(self) -> bool:
        """
        Check whether the deliberation kept every promise checked.

        :return: True when there are no findings.
        """
        return not self.findings
