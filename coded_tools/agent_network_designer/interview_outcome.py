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
from coded_tools.agent_network_designer.interview_state import InterviewState


@dataclass(frozen=True)
class InterviewOutcome:
    """
    What one step of the interview produced: the state after it, what to do next, and the text to print.
    """

    # The statuses the designer branches on, named for what it must do next.
    START: ClassVar[str] = "start"
    RECORDED: ClassVar[str] = "recorded"
    AMBIGUOUS: ClassVar[str] = "ambiguous"
    CONFIRM: ClassVar[str] = "confirm"
    DESCRIBE: ClassVar[str] = "describe"
    ASSUME: ClassVar[str] = "assume"
    COMPLETE: ClassVar[str] = "complete"
    REOPENED: ClassVar[str] = "reopened"
    CHOOSE: ClassVar[str] = "choose"
    UNKNOWN: ClassVar[str] = "unknown"
    LOG: ClassVar[str] = "log"

    status: str
    state: InterviewState | None = None
    prompt: str = ""
    entry: InterviewEntry | None = None
    # The options a reply was tied between, or the log lines a request to go back could mean.
    candidates: tuple[str, ...] = ()
    note: str = ""
    # The options the prompt showed when they are not the entry's own, which the next state keeps on screen.
    shown: tuple[str, ...] = ()
