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
Rendering pack problems for the person who can actually fix them.

The validation messages themselves are written for a reader who knows what a pack is. The person
running this command may be a domain expert who has never opened a Python file, so the difference
between a usable tool and an unusable one is entirely in the presentation: what blocks use versus
what merely wants improving, and what to do next in each case.

The guidance table is the only thing here that can rot - it maps a phrase in a message to advice
about that message. A test asserts every problem a malformed pack can produce is matched by an
entry, so the mapping cannot fall silently behind the messages it explains.
"""

from coded_tools.agent_network_designer.knowledge_pack import KnowledgePack

# (fragment of a validation message, what to do about it). First match wins, so more specific
# fragments must come before more general ones.
GUIDANCE: tuple[tuple[str, str], ...] = (
    (
        "document rather than a standards list",
        "This file is prose. Rewrite each rule as '- <ID>: <the rule>', or extract them from the "
        "document you already have with the 'extract' command.",
    ),
    (
        "none carrying an id",
        "Give each bullet a stable id, e.g. '- ABC-01: <the rule>'. The id is what lets a rule be "
        "traced from this document into the agent network that embeds it.",
    ),
    (
        "not written as a markdown bullet",
        "Put a '- ' in front of the rule. A numbered list or a bare line is not read as a standard.",
    ),
    (
        "not followed by a colon or a full stop",
        "Use a colon straight after the id: '- ABC-01: <the rule>'. A dash or a bracket is not read.",
    ),
    (
        "falls outside the pack's declared standard_id_pattern",
        "Either fix the id, or widen standard_id_pattern in pack.hocon to accept your scheme.",
    ),
    (
        "has no text after the id",
        "Write the rule after the id, or delete the line. An id with no rule cannot be embedded.",
    ),
    (
        "duplicate standard id",
        "Two rules share an id, so neither can be traced unambiguously. Renumber one of them.",
    ),
    (
        "assigns a role to",
        "pack.hocon gives a role to an id this pack no longer defines. Remove the role, or restore the standard.",
    ),
    (
        "declares role",
        "A role must be precondition, work or postcondition. It decides where the rule sits in the "
        "network: a gate before the work, or a check after it.",
    ),
    (
        "not a valid regular expression",
        "standard_id_pattern in pack.hocon is a broken pattern. For ids like ABC-01, use 'ABC-\\\\d{2}'.",
    ),
    (
        "follows a standard but was not read as one",
        "If this line is a rule, give it an id and a '- ' bullet. If it is a closing note, it is "
        "fine as it is - this one is a question, not a fault.",
    ),
    (
        "no operating variables",
        "Add the questions only the requester can answer to open_variables.md.",
    ),
    (
        "no open variables",
        "Add the questions only the requester can answer to open_variables.md, one per line.",
    ),
    (
        "is missing its",
        "Each open variable needs a question, examples and a why. The why is what lets the designer "
        "justify a question it does not itself understand.",
    ),
    (
        "duplicate open variable id",
        "Two questions share an id. Renumber one of them.",
    ),
    (
        "declares no version",
        'Add a version to pack.hocon, e.g. version = "1.0.0". It is recorded in every network built '
        "from this pack, which is what makes one auditable.",
    ),
    (
        "no pack.hocon found",
        "Add a pack.hocon to record the version, the owner and who approved the content. Without it "
        "a generated network cannot say where its rules came from.",
    ),
    (
        "is empty or missing",
        "Write the rules into operating_standards.md, one bullet each.",
    ),
)


def advice_for(problem: str) -> str | None:
    """
    Find the guidance for one validation message.

    :param problem: The message as validate() produced it.
    :return: What to do about it, or None if nothing is mapped.
    """
    for fragment, advice in GUIDANCE:
        if fragment in problem:
            return advice
    return None


def strip_domain(problem: str, domain_id: str) -> str:
    """
    Drop the leading domain name from a message, since it is already the heading.

    :param problem: The message as validate() produced it.
    :param domain_id: The domain the message belongs to.
    :return: The message without its redundant prefix.
    """
    prefix: str = f"{domain_id}: "
    return problem[len(prefix) :] if problem.startswith(prefix) else problem


def render_pack_report(pack: KnowledgePack, show_clean: bool = False) -> str:
    """
    Render one pack's problems, grouped by whether they block use.

    :param pack: The loaded pack.
    :param show_clean: When true, say so explicitly for a pack with nothing wrong.
    :return: The report, or an empty string for a clean pack when show_clean is false.
    """
    domain_id: str = pack.domain_id
    errors: list[str] = pack.validate_errors()
    warnings: list[str] = pack.validate_warnings()

    if not errors and not warnings:
        if not show_clean:
            return ""
        return f"{domain_id} - nothing to fix."

    lines: list[str] = []
    if errors:
        lines.append(f"{domain_id} - this pack cannot be used yet:")
        lines.append("")
        lines.extend(_render_problems(errors, domain_id))
    if warnings:
        if errors:
            lines.append("")
            # Not "but it does work": it does not, and saying so would contradict the block above.
            lines.append(f"{domain_id} - also worth fixing, though these are not what blocks it:")
        else:
            lines.append(f"{domain_id} - worth improving, but it does work:")
        lines.append("")
        lines.extend(_render_problems(warnings, domain_id))
    return "\n".join(lines)


def _render_problems(problems: list[str], domain_id: str) -> list[str]:
    """
    Render a list of messages, each followed by its guidance.

    :param problems: The messages.
    :param domain_id: The domain they belong to, for prefix removal.
    :return: The rendered lines.
    """
    lines: list[str] = []
    for problem in problems:
        lines.append(f"  * {strip_domain(problem, domain_id)}")
        advice: str | None = advice_for(problem)
        if advice is not None:
            lines.append(f"    -> {advice}")
    return lines


def render_summary(packs: list[KnowledgePack]) -> str:
    """
    Render the one-line-per-pack overview printed above the detail.

    :param packs: The loaded packs, in the order to report them.
    :return: The summary block.
    """
    lines: list[str] = []
    for pack in packs:
        if pack.validate_errors():
            state: str = "PROBLEM"
        elif pack.validate_warnings():
            state = "OK*"
        else:
            state = "OK"
        detail: str = (
            f"{plural(len(pack.standards), 'standard')}, "
            f"{plural(len(pack.open_variables), 'question')}, "
            f"v{pack.manifest.version or '?'}"
        )
        lines.append(f"  {pack.domain_id:<34} {state:<8} {detail}")
    return "\n".join(lines)


def plural(count: int, noun: str) -> str:
    """
    Render a count with its noun, singular or plural.

    Public because the command line needs the same courtesy as the report it prints. These messages
    are read by domain experts, and "1 packs" is a small but real signal that nobody proof-read the
    thing telling them their document is wrong.

    :param count: How many.
    :param noun: The singular noun.
    :return: For example "1 standard" or "6 standards".
    """
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"
