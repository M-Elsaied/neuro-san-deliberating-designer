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

"""
Tests for the pack author's command line.

The audience for this command is a domain expert, not a developer, so the tests are about whether
the output is actionable as much as whether the exit code is right. No language model, no key.
"""

from pathlib import Path

import pytest

from coded_tools.agent_network_designer.authoring.cli import EXIT_OK
from coded_tools.agent_network_designer.authoring.cli import EXIT_PROBLEM
from coded_tools.agent_network_designer.authoring.cli import EXIT_USAGE
from coded_tools.agent_network_designer.authoring.cli import main
from coded_tools.agent_network_designer.authoring.report import advice_for
from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack
from coded_tools.agent_network_designer.pack_catalogue import load_pack

BROKEN_STANDARDS: str = (
    "- CC-01: Raise a change record before any production change.\n"
    "- CC-01: A duplicate id.\n"
    "- CC-02 - A wrong separator.\n"
    "3. CC-03: Not a bullet.\n"
    "- CC-04:\n"
    "- WRONG-05: An id outside the declared pattern.\n"
    "- CC-06: A rule with a bad role.\n"
    "\n"
    "All changes must additionally be approved by the CAB.\n"
)
BROKEN_MANIFEST: str = (
    '{ domain_id = "change_control"\n'
    '  standard_id_pattern = "CC-\\\\d{2}"\n'
    '  roles { "CC-09" = precondition\n'
    '          "CC-06" = nonsense } }\n'
)


def write_pack(root: Path, domain_id: str, standards: str, variables: str, manifest: str | None = None) -> Path:
    """
    Write a minimal pack on disk.

    :param root: The knowdocs root to write under.
    :param domain_id: The pack directory name.
    :param standards: Contents of operating_standards.md.
    :param variables: Contents of open_variables.md.
    :param manifest: Contents of pack.hocon, or None to omit it.
    :return: The pack directory.
    """
    directory: Path = root / domain_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "operating_standards.md").write_text(standards, encoding="utf-8")
    (directory / "open_variables.md").write_text(variables, encoding="utf-8")
    if manifest is not None:
        (directory / "pack.hocon").write_text(manifest, encoding="utf-8")
    return directory


def test_the_shipped_packs_validate_from_the_command_line(capsys):
    """
    The command an author is told to run, against the packs they are told to copy.
    """
    assert main(["validate", "--all"]) == EXIT_OK
    output: str = capsys.readouterr().out
    assert "oracle_database_patching" in output
    assert "are usable" in output


def test_a_prose_document_is_told_what_shape_a_standard_takes(tmp_path, capsys):
    """
    The most likely first contact: someone pastes their SOP in and runs the check.

    Before this the answer was "no operating standards found", which is true, useless, and reads as
    though the file were empty when it is full of rules.
    """
    write_pack(
        tmp_path,
        "hr_onboarding",
        "# Onboarding SOP\n\nAll new starters must complete security training.\n",
        "- V1 | Which teams? | examples: sales | why: scope\n",
    )

    assert main(["validate", "--domain", "hr_onboarding", "--knowdocs", str(tmp_path)]) == EXIT_PROBLEM
    output: str = capsys.readouterr().out
    assert "document rather than a standards list" in output
    assert "- <ID>:" in output, "the expected shape must appear, not just the complaint"


def test_a_broken_pack_reports_every_fault_with_advice(tmp_path, capsys):
    """
    Each fault gets a line and a "-> what to do". A list of complaints is not a workflow.
    """
    write_pack(tmp_path, "change_control", BROKEN_STANDARDS, "- V1 | q | examples: e\n", BROKEN_MANIFEST)

    assert main(["validate", "--domain", "change_control", "--knowdocs", str(tmp_path)]) == EXIT_PROBLEM
    output: str = capsys.readouterr().out

    for expected in ("duplicate standard id", "colon or a full stop", "markdown bullet", "no text after the id"):
        assert expected in output, expected
    # Every reported problem is followed by guidance.
    complaints: int = output.count("\n  * ")
    guidance: int = output.count("\n    -> ")
    assert guidance == complaints, f"{complaints} problems but {guidance} pieces of advice"


def test_warnings_alone_do_not_make_a_pack_unusable(tmp_path, capsys):
    """
    A pack missing only its provenance still works, and must not be reported as broken - that is
    what keeps a pack written before manifests existed loadable.
    """
    write_pack(tmp_path, "legacy", "- LG-01: A rule.\n", "- V1 | q | examples: e\n")

    assert main(["validate", "--domain", "legacy", "--knowdocs", str(tmp_path)]) == EXIT_OK
    assert "worth improving, but it does work" in capsys.readouterr().out


def test_strict_makes_an_incomplete_pack_a_failure(tmp_path):
    """
    A deployment that requires complete provenance needs to be able to say so.
    """
    write_pack(tmp_path, "legacy", "- LG-01: A rule.\n", "- V1 | q | examples: e\n")

    assert main(["validate", "--domain", "legacy", "--knowdocs", str(tmp_path)]) == EXIT_OK
    assert main(["validate", "--domain", "legacy", "--knowdocs", str(tmp_path), "--strict"]) == EXIT_PROBLEM


def test_the_warning_heading_does_not_claim_a_broken_pack_works(tmp_path, capsys):
    """
    A pack with both errors and warnings must not be told, two lines apart, that it does not work
    and that it does.
    """
    write_pack(tmp_path, "change_control", BROKEN_STANDARDS, "- V1 | q | examples: e\n", BROKEN_MANIFEST)

    main(["validate", "--domain", "change_control", "--knowdocs", str(tmp_path)])
    output: str = capsys.readouterr().out

    assert "cannot be used yet" in output
    assert "but it does work" not in output


def test_an_unknown_domain_names_what_is_available(tmp_path, capsys):
    """
    Naming the alternatives is what turns "no such pack" into something to act on.
    """
    write_pack(tmp_path, "real_pack", "- RP-01: A rule.\n", "- V1 | q | examples: e\n")

    assert main(["validate", "--domain", "typo", "--knowdocs", str(tmp_path)]) == EXIT_USAGE
    assert "real_pack" in capsys.readouterr().err


def test_an_empty_knowdocs_root_is_a_usage_error(tmp_path, capsys):
    """
    Zero packs is a misconfigured root, not a clean bill of health.
    """
    assert main(["validate", "--all", "--knowdocs", str(tmp_path)]) == EXIT_USAGE
    assert "No knowledge packs found" in capsys.readouterr().err


def test_domain_and_all_are_mutually_exclusive():
    """One target or the other: silently preferring one would be a surprising default."""
    with pytest.raises(SystemExit):
        main(["validate", "--domain", "x", "--all"])


def test_every_problem_a_malformed_pack_can_produce_has_advice(tmp_path):
    """
    The guidance table maps message fragments to advice, so it can fall behind the messages it
    explains. This is what stops that happening silently: any new validation message with no
    guidance entry fails here rather than reaching an author as a bare complaint.
    """
    write_pack(tmp_path, "change_control", BROKEN_STANDARDS, "- V1 | q | examples: e\n", BROKEN_MANIFEST)
    write_pack(tmp_path, "prose_pack", "Just prose, no rules at all.\n", "")
    write_pack(tmp_path, "no_ids", "- A rule with no id.\n", "- V1 | q | examples: e | why: w\n")
    write_pack(
        tmp_path,
        "bad_regex",
        "- BR-01: A rule.\n",
        "- V1 | q | examples: e | why: w\n",
        manifest='{ domain_id = "bad_regex"\n version = "1.0"\n standard_id_pattern = "BR-[0-9" }\n',
    )

    unexplained: list[str] = []
    for domain_id in ("change_control", "prose_pack", "no_ids", "bad_regex"):
        pack: KnowledgePack = load_pack(domain_id, tmp_path)
        for problem in pack.validate():
            if advice_for(problem) is None:
                unexplained.append(problem)

    assert not unexplained, "validation messages with no guidance:\n  " + "\n  ".join(unexplained)
