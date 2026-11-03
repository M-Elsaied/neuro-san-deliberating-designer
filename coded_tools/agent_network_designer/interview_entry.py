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
class InterviewEntry:
    """
    One question of the interview and its answer, replaced rather than edited when the answer changes.
    """

    # Assigned once when the interview starts, so "back to Q3" always means the same entry.
    label: str
    variable_id: str
    question: str
    options: tuple[str, ...]
    why: str
    answer: str = ""
    # True when the designer chose the answer as a default rather than the user giving it.
    assumed: bool = False

    @property
    def answered(self) -> bool:
        """
        Check whether this entry has an answer on file.

        :return: True when it has one.
        """
        return bool(self.answer)
