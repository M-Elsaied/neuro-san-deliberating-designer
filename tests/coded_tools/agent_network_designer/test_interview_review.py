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

import contextlib
import io
import json
import tempfile
from pathlib import Path
from unittest import TestCase

from coded_tools.agent_network_designer.interview_options import InterviewOptions
from coded_tools.agent_network_designer.interview_review import InterviewReview
from coded_tools.agent_network_designer.interview_review_result import InterviewReviewResult
from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack
from coded_tools.agent_network_designer.pack_reader import PackReader
from tests.coded_tools.agent_network_designer.pack_fixtures import PackFixtures
from tests.coded_tools.agent_network_designer.transcript_fixtures import TranscriptFixtures


class TestInterviewReview(TestCase):
    """
    Tests for InterviewReview, and through it InterviewGateChecks.
    """

    def setUp(self) -> None:
        """Review against the shipped Oracle pack, with every other pack's ids foreign."""
        self.pack: KnowledgePack = PackFixtures.load_shipped_pack(self, "oracle_database_patching")

    @staticmethod
    def review(turns: list[dict[str, str]], pack: KnowledgePack) -> InterviewReviewResult:
        """Review turns against a pack, with every other shipped pack's ids as foreign."""
        other_ids: set[str] = set()
        for other in PackReader.load_catalog():
            for standard in other.standards if other.domain_id != pack.domain_id else []:
                other_ids.add(standard.standard_id)
        return InterviewReview.review(turns, pack, other_ids)

    @staticmethod
    def get_kind(result: InterviewReviewResult, kind: str) -> list[str]:
        """Pick out the findings of one kind, since a snippet with no brief also reports the missing brief."""
        found: list[str] = []
        for finding in result.findings:
            if finding.startswith(f"{kind}:"):
                found.append(finding)
        return found

    @staticmethod
    def ask(text: str, *options: str) -> dict[str, str]:
        """Build a designer question in the numbered form the prompt requires."""
        lines: list[str] = [text]
        for number, option in enumerate(options, start=1):
            lines.append(f"  {number}. {option}")
        return {"role": "designer", "text": "\n".join(lines) + "\n\nWhy it matters."}

    def test_clean_sessions_review_clean_and_each_fault_is_found(self) -> None:
        """Every check has teeth, and disambiguating or going back is not counted as an overrun."""
        clean: InterviewReviewResult = self.review(TranscriptFixtures.build_clean(self.pack), self.pack)
        self.assertEqual(([], 7, 6), (clean.findings, clean.questions_asked, clean.standards_quoted))
        for fault, edit in TranscriptFixtures.FAULTS.items():
            with self.subTest(fault=fault):
                result: InterviewReviewResult = self.review(TranscriptFixtures.build_faulty(fault), self.pack)
                self.assertIn(edit.get("fragment"), " ".join(result.findings))
                self.assertTrue(result.findings[0].startswith(edit.get("kind")), result.findings)
        ignored: InterviewReviewResult = self.review(
            TranscriptFixtures.build_faulty("assumed through ambiguity"), self.pack
        )
        self.assertEqual((7, 0), (ignored.questions_asked, ignored.clarifications))

    def test_only_an_answer_fitting_several_options_must_be_asked_again(self) -> None:
        """A number or an unmatched answer is fine; naming one tied option back is the assumption spelled out."""
        offered: dict[str, str] = self.ask("Which gate?", "X approved by A", "X approved by B", "I am not sure")
        for reply in ("2", "none of those - a standing waiver"):
            with self.subTest(reply=reply):
                result: InterviewReviewResult = self.review([offered, {"role": "user", "text": reply}], self.pack)
                self.assertEqual([], self.get_kind(result, "AMBIGUITY"))
        echoed: dict[str, str] = self.ask("So X approved by A - and the rollback?", "r1", "r2", "not sure")
        guessed: list[str] = self.get_kind(
            self.review([offered, {"role": "user", "text": "X"}, echoed], self.pack), "AMBIGUITY"
        )
        self.assertTrue(guessed[0].startswith("AMBIGUITY: turn 1: the answer 'X' fits 2 of the options offered"))
        no_escape: list[str] = self.get_kind(
            self.review([self.ask("Which gate?", "a", "b", "c")], self.pack), "OPTIONS"
        )
        self.assertIn("no 'something else' or 'not sure' escape", no_escape[0])

    def test_a_session_that_disambiguates_and_goes_back_reviews_clean(self) -> None:
        """Sending an ambiguous answer back and honoring a correction are counted, and neither is a finding."""
        tied: dict[str, str] = self.ask("Which gate?", "X approved by A", "X approved by B", "I am not sure")
        turns: list[dict[str, str]] = [tied, {"role": "user", "text": "X"}, tied, {"role": "user", "text": "1"}]
        turns.extend([{"role": "user", "text": "go back"}, self.ask("Back to Q1?", "a", "b", "not sure")])
        result: InterviewReviewResult = self.review(turns, self.pack)
        self.assertEqual((1, 1), (result.clarifications, result.revisits))
        self.assertEqual([], self.get_kind(result, "AMBIGUITY") + self.get_kind(result, "REVISION"))

    def test_going_back_is_honored_and_not_counted_as_a_new_question(self) -> None:
        """There is no cap on going back, and resuming asks the open question again, which is still one question."""
        escape: str = InterviewOptions.UNSURE_ESCAPE
        back: dict[str, str] = self.ask("Q1. Subject - a\n\nBack to Q1?", "a", "b", escape)
        turns: list[dict[str, str]] = [self.ask("First question?", "a", "b", escape)]
        for request in ("go back", "back two - change my answer", "take me back to the first question"):
            turns.extend([{"role": "user", "text": request}, back])
        walked: InterviewReviewResult = self.review(turns, self.pack)
        self.assertEqual((3, 1, []), (walked.revisits, walked.questions_asked, self.get_kind(walked, "REVISION")))
        going: list[dict[str, str]] = [turns[0], {"role": "user", "text": "go back and just build it"}]
        going.append({"role": "designer", "text": "Written to registries/generated/x.hocon"})
        built: list[str] = self.get_kind(self.review(going, self.pack), "REVISION")
        self.assertIn("built the network after the user asked to change", built[0])

    def test_a_brief_with_an_invented_id_or_too_many_questions_is_reported(self) -> None:
        """An id the pack does not define, in the document the user approves, and an interview from elsewhere."""
        brief: str = "## DESIGN BRIEF - X\n- **ODB-99** - An invented rule.\nReply APPROVED to build this."
        self.assertIn(
            "the brief quotes ODB-99, which this pack does not define",
            " ".join(self.review([{"role": "designer", "text": brief}], self.pack).findings),
        )
        turns: list[dict[str, str]] = []
        for index in range(12):
            turns.extend(
                [{"role": "user", "text": f"answer {index}"}, {"role": "designer", "text": f"Question {index}?"}]
            )
        self.assertIn(
            "asked 12 questions where the pack declares 7 open variables",
            " ".join(self.review(turns, self.pack).findings),
        )

    def test_every_kind_of_re_ask_is_the_same_question_asked_again(self) -> None:
        """A confirm declined, a number off the list, a tie and a describe each ask again, never a new question."""
        replies: tuple[str, ...] = ("single instance", "no", "9", "1", "PROD", "1 or 3", "3", "something else", "x")
        result: InterviewReviewResult = self.review(TranscriptFixtures.build_clean(self.pack, replies), self.pack)
        self.assertEqual(([], 7, 1), (result.findings, result.questions_asked, result.clarifications))

    def test_a_clean_session_in_every_domain_reviews_clean(self) -> None:
        """Checks calibrated on one domain can encode its shape, and the fixture asks what the renderer renders."""
        for domain_id in PackReader.discover_domains():
            with self.subTest(domain_id=domain_id):
                pack: KnowledgePack = PackReader.load_pack(domain_id)
                result: InterviewReviewResult = self.review(TranscriptFixtures.build_clean(pack), pack)
                self.assertEqual(([], len(pack.open_variables)), (result.findings, result.questions_asked))

    def test_the_command_line_exits_with_the_outcome(self) -> None:
        """0 clean, 1 faulty with the findings printed, 2 for a file that is not a transcript or an unknown domain."""
        with tempfile.TemporaryDirectory() as temporary:
            clean: str = str(Path(temporary) / "clean.json")
            faulty: Path = Path(temporary) / "faulty.json"
            session: list[dict[str, str]] = TranscriptFixtures.build_clean(self.pack)
            Path(clean).write_text(
                json.dumps({"domain": "oracle_database_patching", "turns": session}), encoding="utf-8"
            )
            turns: list[dict[str, str]] = TranscriptFixtures.build_faulty("paraphrased in brief")
            faulty.write_text(json.dumps({"domain": "oracle_database_patching", "turns": turns}), encoding="utf-8")
            (Path(temporary) / "nope.json").write_text("""{"something": "else"}""", encoding="utf-8")
            cases: list[tuple[list[str], int, str]] = [
                ([clean], 0, "The deliberation followed the promised behavior in every checked respect."),
                ([str(faulty)], 1, "- FIDELITY: turn 14: ODB-03 is not quoted verbatim in the brief."),
                ([str(Path(temporary) / "nope.json")], 2, "does not look like a transcript"),
                ([str(Path(temporary) / "missing.json")], 2, "Could not read transcript"),
                ([clean, "--domain", "nowhere"], 2, "Available: clinical_trial_database_lock"),
            ]
            for argv, exit_code, expected in cases:
                with self.subTest(expected=expected):
                    output: io.StringIO = io.StringIO()
                    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                        self.assertEqual(exit_code, InterviewReview.main(argv))
                    self.assertIn(expected, output.getvalue())
