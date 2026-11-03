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

from coded_tools.agent_network_designer.interview_entry import InterviewEntry
from coded_tools.agent_network_designer.interview_options import InterviewOptions
from coded_tools.agent_network_designer.interview_state import InterviewState


class InterviewRenderer:
    """
    Renders the interview as finished text for the designer to print, so the options shown are the pack's own,
    in its order, rather than the model's memory of them.
    """

    CLOSING_LINE: str = """Reply with a number, or in your own words. Say "go back" to change an earlier answer."""

    @staticmethod
    def render(state: InterviewState, options: tuple[str, ...] | None = None, lead: str = "") -> str:
        """
        Render the entry on screen as a numbered question, with the two escapes after its options.

        :param state: The interview.
        :param options: Options to offer instead of those on screen, to narrow an ambiguous answer.
        :param lead: A first line saying why the question is asked again. A lead that is itself a question replaces
            the entry's question, so one reply never asks two.
        :return: The question, ready to print verbatim.
        """
        entry: InterviewEntry = state.current
        lines: list[str] = [lead] if lead else []
        if not lead.rstrip().endswith("?"):
            lines.append(entry.question if entry.question.rstrip().endswith("?") else f"{entry.question}?")
        shown: list[str] = list(options if options is not None else state.on_screen)
        for number, option in enumerate([*shown, InterviewOptions.DESCRIBE_ESCAPE, InterviewOptions.UNSURE_ESCAPE], 1):
            on_file: str = " (currently on file)" if entry.answered and option == entry.answer else ""
            lines.append(f"  {number}. {option}{on_file}")
        lines.append("")
        if entry.why:
            lines.append(entry.why[0].upper() + entry.why[1:])
        lines.append(InterviewRenderer.CLOSING_LINE)
        return "\n".join(lines)

    @staticmethod
    def get_log_lines(state: InterviewState) -> list[str]:
        """
        Render the answer log, as "Q1." rather than "1." since a number opening a line offers an option.

        :param state: The interview.
        :return: One line per visible entry.
        """
        lines: list[str] = []
        for entry in state.visible:
            answer: str = f"{entry.answer or 'not yet answered'}{' (assumed)' if entry.assumed else ''}"
            lines.append(f"{entry.label}. {InterviewRenderer.get_subject(entry)} - {answer}")
        return lines

    @staticmethod
    def get_brief_lines(state: InterviewState, assumed: bool) -> list[str]:
        """
        Render one of the brief's answer sections from the log, so a corrected answer reaches it.

        :param state: The interview.
        :param assumed: True for the defaults the designer chose, False for the answers the user gave.
        :return: One "<subject>: <answer>" line per answered entry of that kind.
        """
        lines: list[str] = []
        for entry in state.entries:
            if entry.answered and entry.assumed == assumed:
                lines.append(f"{InterviewRenderer.get_subject(entry)}: {entry.answer}")
        return lines

    @staticmethod
    def get_subject(entry: InterviewEntry) -> str:
        """
        Name an entry for the log by the part of its question before the first colon, the pack author's own name.

        :param entry: The entry.
        :return: That name, or the question without its question mark when there is no such part.
        """
        head: str = entry.question.split(":", 1)[0].strip()
        return head if head and len(head) < len(entry.question) else entry.question.rstrip("?").strip()
