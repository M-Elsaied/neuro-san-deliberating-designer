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

import sys
from argparse import ArgumentParser
from argparse import Namespace
from typing import Any

from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack
from coded_tools.agent_network_designer.pack_reader import PackReader
from coded_tools.agent_network_designer.pack_validator import PackValidator


class PackAuthoring:
    """
    The pack author's command line. "validate" checks that a pack loads and says what is wrong and what to do about
    it, for a reader who may be a domain expert rather than a developer. No model, key or server is needed.
    """

    EXIT_OK: int = 0
    EXIT_PROBLEM: int = 1
    EXIT_USAGE: int = 2
    # A fragment of a problem message, mapped to what to do about it. The first match wins, so a specific fragment
    # comes before a general one, and a test checks every problem a malformed pack can produce has advice.
    GUIDANCE: dict[str, str] = {
        "document rather than a standards list": (
            "This file is prose. Rewrite each rule as '- <ID>: <the rule>', or extract them from the document "
            "you already have."
        ),
        "none carrying an id": (
            "Give each bullet a stable id, e.g. '- ABC-01: <the rule>'. The id is what lets a rule be traced from "
            "this document into the agent network that embeds it."
        ),
        "ids appear in the file": "Fix each line the errors below name, and its standard will load.",
        "not written as a markdown bullet": (
            "Put a '- ' in front of the rule. A numbered list or a bare line is not read as a standard."
        ),
        "not followed by a colon or a full stop": (
            "Use a colon straight after the id: '- ABC-01: <the rule>'. A dash or a bracket is not read."
        ),
        "falls outside the pack's declared standard_id_pattern": (
            "Either fix the id, or widen standard_id_pattern in pack.hocon to accept your scheme."
        ),
        "has no text after the id": (
            "Write the rule after the id, or delete the line. An id with no rule cannot be embedded."
        ),
        "duplicate standard id": (
            "Two rules share an id, so neither can be traced unambiguously. Renumber one of them."
        ),
        "assigns a role to": (
            "pack.hocon gives a role to an id this pack no longer defines. Remove the role, or restore the standard."
        ),
        "declares role": (
            "A role must be precondition, work or postcondition. It decides where the rule sits in the network: a "
            "gate before the work, or a check after it."
        ),
        "not a valid regular expression": (
            "standard_id_pattern in pack.hocon is a broken pattern. For ids like ABC-01, use 'ABC-\\\\d{2}'."
        ),
        "follows a standard but was not read as one": (
            "If this line is a rule, give it an id and a '- ' bullet. If it is a closing note, it is fine as it "
            "is - this one is a question, not a fault."
        ),
        "no open variables": "Add the questions only the requester can answer to open_variables.md, one per line.",
        "is missing its": (
            "Each open variable needs a question, examples and a why. The why is what lets the designer justify a "
            "question it does not itself understand."
        ),
        "duplicate open variable id": "Two questions share an id. Renumber one of them.",
        "declares no version": (
            'Add a version to pack.hocon, e.g. version = "1.0.0". It is recorded in every network built from this '
            "pack, which is what makes one auditable."
        ),
        "no pack.hocon found": (
            "Add a pack.hocon to record the version, the owner and who approved the content. Without it a generated "
            "network cannot say where its rules came from."
        ),
        "is empty or missing": "Write the rules into operating_standards.md, one bullet each.",
        "Could not parse": "Fix pack.hocon at the position the error names, then check the pack again.",
    }

    @staticmethod
    def get_advice(problem: str) -> str | None:
        """
        Find what to do about one problem.

        :param problem: A problem message, as PackValidator wrote it.
        :return: The advice for the first matching fragment, or None.
        """
        for fragment, advice in PackAuthoring.GUIDANCE.items():
            if fragment in problem:
                return advice
        return None

    @staticmethod
    def render_pack(domain_id: str, result: KnowledgePack | str, show_clean: bool = False) -> str:
        """
        Render one pack's problems, those that stop it being used first.

        :param domain_id: The pack's domain id.
        :param result: The loaded pack, or the error that stopped it loading.
        :param show_clean: When True, say so for a pack with nothing wrong.
        :return: The report, or "" for a clean pack when show_clean is False.
        """
        errors: list[str] = [result]
        warnings: list[str] = []
        if isinstance(result, KnowledgePack):
            errors = PackValidator.get_errors(result)
            warnings = PackValidator.get_warnings(result)
        if not errors and not warnings:
            return f"{domain_id} - nothing to fix." if show_clean else ""
        # After errors, not "but it does work", which would contradict the block above.
        later: str = (
            "also worth fixing, though these are not what blocks it" if errors else "worth improving, but it does work"
        )
        prefix: str = f"{domain_id}: "
        lines: list[str] = []
        for heading, problems in (("this pack cannot be used yet", errors), (later, warnings)):
            if problems:
                lines.extend(["", f"{domain_id} - {heading}:", ""])
            for problem in problems:
                lines.append(f"  * {problem.removeprefix(prefix)}")
                advice: str | None = PackAuthoring.get_advice(problem)
                if advice is not None:
                    lines.append(f"    -> {advice}")
        return "\n".join(lines[1:])

    @staticmethod
    def render_summary(results: dict[str, KnowledgePack | str]) -> str:
        """
        Render one line per pack: OK, OK* when usable but under-specified, or PROBLEM.

        :param results: Domain id to the loaded pack, or to the error that stopped it loading.
        :return: The summary.
        """
        lines: list[str] = []
        for domain_id, result in results.items():
            if not isinstance(result, KnowledgePack):
                lines.append(f"  {domain_id:<34} {'PROBLEM':<8} could not be read")
                continue
            state: str = "OK"
            if PackValidator.get_errors(result):
                state = "PROBLEM"
            elif PackValidator.get_warnings(result):
                state = "OK*"
            standards: str = PackValidator.pluralize(len(result.standards), "standard")
            questions: str = PackValidator.pluralize(len(result.open_variables), "question")
            lines.append(f"  {domain_id:<34} {state:<8} {standards}, {questions}, v{result.manifest.version or '?'}")
        return "\n".join(lines)

    @staticmethod
    def validate(arguments: Namespace) -> int:
        """
        Check one pack or every pack. A pack that cannot be read is reported as unusable rather than skipped.

        :param arguments: The parsed arguments.
        :return: 0 when every pack is usable, 1 when one is not, or is incomplete under --strict, 2 on a usage error.
        """
        root: str | None = arguments.knowdocs
        domains: list[str] = PackReader.discover_domains(root) if arguments.all else [arguments.domain]
        if not domains:
            print(f"No knowledge packs found under {PackReader.get_knowdocs_root(root)}", file=sys.stderr)
            return PackAuthoring.EXIT_USAGE
        results: dict[str, KnowledgePack | str] = {}
        for domain_id in domains:
            try:
                results[domain_id] = PackReader.load_pack(domain_id, root)
            except FileNotFoundError as exception:
                if not arguments.all:
                    print(f"{exception}\nAvailable packs: {PackReader.describe_domains(root)}", file=sys.stderr)
                    return PackAuthoring.EXIT_USAGE
                results[domain_id] = str(exception)
            except (OSError, ValueError) as exception:
                results[domain_id] = str(exception)
        return PackAuthoring.report(results, arguments)

    @staticmethod
    def report(results: dict[str, KnowledgePack | str], arguments: Namespace) -> int:
        """
        Print the checked packs' problems, then the verdict.

        :param results: Domain id to the loaded pack, or to the error that stopped it loading.
        :param arguments: The parsed arguments.
        :return: The exit code, as validate() describes it.
        """
        count: str = PackValidator.pluralize(len(results), "pack")
        where: str = str(PackReader.get_knowdocs_root(arguments.knowdocs))
        print(f"Checking {count if arguments.all else arguments.domain} in {where}\n")
        if arguments.all:
            print(PackAuthoring.render_summary(results))
        unusable: int = 0
        incomplete: int = 0
        for domain_id, result in results.items():
            report: str = PackAuthoring.render_pack(domain_id, result, show_clean=not arguments.all)
            if report:
                print(f"\n{report}")
            if not isinstance(result, KnowledgePack) or PackValidator.get_errors(result):
                unusable += 1
            elif PackValidator.get_warnings(result):
                incomplete += 1
        print()
        if unusable:
            print(f"{unusable} of {count} cannot be used yet.")
            return PackAuthoring.EXIT_PROBLEM
        if arguments.strict and incomplete:
            print(f"{incomplete} of {count} incomplete, and --strict was given.")
            return PackAuthoring.EXIT_PROBLEM
        if incomplete:
            print(f"All {count} usable. {incomplete} could be more complete (marked OK*).")
        else:
            print(f"All {count} usable.")
        return PackAuthoring.EXIT_OK

    @staticmethod
    def main(argv: list[str] | None = None) -> int:
        """
        Run an authoring command from the command line.

        :param argv: The arguments, or None to read sys.argv.
        :return: The command's exit code.
        """
        parser: ArgumentParser = ArgumentParser(
            prog="python -m coded_tools.agent_network_designer.pack_authoring",
            description="Author and check curated knowledge packs.",
        )
        commands: Any = parser.add_subparsers(dest="command", required=True)
        validate: ArgumentParser = commands.add_parser(
            "validate", help="check that a pack loads, and report exactly what is wrong if it does not"
        )
        target: Any = validate.add_mutually_exclusive_group(required=True)
        target.add_argument("--domain", help="the pack to check, i.e. its directory name")
        target.add_argument("--all", action="store_true", help="check every pack under the knowdocs root")
        validate.add_argument("--knowdocs", default=None, help="override the knowdocs root")
        validate.add_argument(
            "--strict",
            action="store_true",
            help="treat warnings as failures, for a deployment that requires complete provenance",
        )
        return PackAuthoring.validate(parser.parse_args(argv))


if __name__ == "__main__":
    sys.exit(PackAuthoring.main())
