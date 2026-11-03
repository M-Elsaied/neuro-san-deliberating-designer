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
from typing import ClassVar

from coded_tools.agent_network_designer.interview_entry import InterviewEntry


@dataclass(frozen=True)
class InterviewState:
    """
    The interview so far: every entry, which is on screen, and the options on screen. Held as state, so entries are
    never relabeled, answers never rewritten, and "back three" always lands three back.
    """

    # sly_data key carrying the interview between turns. The front man must also allow it upstream, since session
    # sly_data is rebuilt from the client's payload on every turn.
    SLY_DATA_KEY: ClassVar[str] = "agent_network_interview_log"

    domain_id: str
    # Every question exists from the start, so its label never changes.
    entries: tuple[InterviewEntry, ...]
    cursor: int = 0
    # False when the designer derived the questions for a domain with no pack: no standard may be called verified.
    curated: bool = True
    # The options a re-ask narrowed the list to. They are numbered from 1, so the next reply's number is read
    # against them rather than against the entry's own options. Empty means the entry's own.
    offered: tuple[str, ...] = ()

    @property
    def current(self) -> InterviewEntry:
        """
        Read the entry on screen.

        :return: The entry at the cursor.
        """
        return self.entries[self.cursor]

    @property
    def on_screen(self) -> tuple[str, ...]:
        """
        Read the options the user is looking at.

        :return: The narrowed options, else the current entry's own.
        """
        return self.offered or self.current.options

    @property
    def visible(self) -> tuple[InterviewEntry, ...]:
        """
        Read the entries the user has seen: those answered, and the one on screen.

        :return: The visible entries, in order.
        """
        visible: list[InterviewEntry] = []
        for entry in self.entries:
            if entry.answered or entry.label == self.current.label:
                visible.append(entry)
        return tuple(visible)

    @property
    def outstanding(self) -> tuple[InterviewEntry, ...]:
        """
        Read the entries with no answer on file.

        :return: The unanswered entries, in order.
        """
        outstanding: list[InterviewEntry] = []
        for entry in self.entries:
            if not entry.answered:
                outstanding.append(entry)
        return tuple(outstanding)
