# The deliberation interview

The Agent Network Designer gathers requirements before it builds anything. This document describes
how that interview behaves: how questions are put, how a reply is interpreted, what happens when a
reply does not settle the question, and how a requester corrects an earlier answer.

The governing rule is that **nothing reaches the design brief as a confirmed requirement unless the
requester confirmed it.** Everything below follows from that.

## Questions are numbered choices

Each open variable is presented as a question followed by a numbered list, built from the variable's
own `examples` in its knowledge pack, verbatim and in the pack's order, with two escapes appended:

```text
Approval: which change record gates production, and who approves it?
  1. ServiceNow CR approved by CAB
  2. ServiceNow CR approved by the app owner
  3. no formal gate in non-prod
  4. Something else - I will describe it
  5. I am not sure - choose a sensible default for me

Determines the change-control gate before any production work.
Reply with a number, or in your own words. Say "go back" to change an earlier answer.
```

Characteristics:

- **The list is computed, not composed.** `InterviewLog` renders the text and the designer prints it,
  so options cannot be invented, reworded, reordered or dropped.
- **The escapes are mandatory.** Without them a numbered list narrows the answer to whatever was
  enumerated, and a requester whose situation is not listed has no honest reply.
- **One question per reply**, and exactly one question mark in it.

## How a reply is interpreted

Interpretation is split in two, and the split is the design:

| Stage | Question | Decided by |
| --- | --- | --- |
| Recognition | which offered options is this reply consistent with? | a matcher |
| Policy | is that enough to record as a requirement? | code |

A matcher returns a **set of candidates**. It never returns a decision. The policy is arithmetic
over the size of that set:

| Candidates | Outcome | Reason |
| --- | --- | --- |
| 0 | recorded as written | the requester answered in their own words |
| 1 | `confirm` | the option may say more than the requester did |
| 2 or more | `ambiguous` | the reply does not distinguish them |

The single-candidate case is the subtle one. An option such as
`DBA team, verified restore required` bundles two facts. A reply of `DBA team` identifies *which*
option without agreeing to everything it says, so recording the option would attribute the verified
restore to the requester. Recording the shorthand instead would drop the part nobody disputed. The
option is therefore offered back for a single confirmation, and the variable stays open until it
gets one.

### Numbers versus prose

A reply names options only when it consists of digits and connectives and nothing else, so `1`,
`1 or 4`, `option 2` and `#3` choose options while `4 hours`, `40 databases` and `1.29 to 1.31` are
answers. Naming two numbers (`1 or 4`) is ambiguous rather than resolved to the first.

Because a narrowed re-ask renumbers from `1`, the list actually displayed is carried in session state
and a subsequent number is resolved against **that**, not against the pack's ordering.

## Reply matching

Two matchers exist behind one interface.

- **Deterministic** (default): proper-substring containment. Needs no model, no key and no network.
- **Model-backed** (opt-in): a language model reads the reply against the options.

Set `AGENT_NETWORK_DESIGNER_MATCH_MODEL` to a model name to enable the second; unset, `off`, `none`
or `false` selects the first. The model resolves references containment cannot see — a paraphrase, a
position (`the second one`), or a description (`the one with a standby`).

A matcher's output is untrusted input, and is validated before it can mean anything:

- only positions in the list already held by the caller may cross the boundary, so an invented
  option cannot enter the interview;
- out-of-range indices are dropped rather than clamped;
- escapes are stripped, so uncertainty cannot be recorded as a requirement;
- duplicates are collapsed, so one option named twice does not read as ambiguity;
- any provider failure degrades to the deterministic matcher rather than ending the session.

Deterministic resolution runs first: a number or an exact quote never reaches a matcher.

The matcher is reached from inside `InterviewLog`. It is not a separate agent the front man elects
to call, so the policy applies whether or not the front man cooperates.

## Correcting an earlier answer

A requester may change any earlier answer at any point before the build, from any question and from
the design brief. The session keeps a labelled answer log:

```text
Q1. Topology - two-node RAC
Q2. Estate and order - DEV to QA to PROD
Q3. Window - 4 hours, rolling required
Q4. Backup ownership - DBA team, verified restore required
```

Recognised forms, all resolved in code rather than inferred by the model:

| Form | Meaning |
| --- | --- |
| `go back` | the entry before the one on screen |
| `back three` | three entries back, clamped to the first |
| `Q2`, `change question 2` | that entry, by its stable label |
| `change the window answer` | the entry whose subject it names |
| `take me back to the first question` | the first entry |

Guarantees:

- **No limit** on distance or on how many times. Going further back than the first entry lands on
  the first and says so.
- **Labels never shift.** Re-answering `Q3` leaves it `Q3`, so a later reference means the same thing.
- **Only the named entry is re-asked.** Every other answer keeps its value, and the interview resumes
  at the first variable still unanswered, so nothing passed on the way back is asked twice.
- **Two readings are never resolved silently.** A subject matching several entries, or a count and a
  subject that disagree (`back two - change the topology answer`), are put back to the requester.
- Going back is **not** a request to skip the deliberation and is never refused as one.

## Session state

The question list, every answer, the current position and the displayed option list live in the
`InterviewLog` coded tool, in `sly_data`, under `agent_network_interview_log`. The key is declared in
the front man's `allow.to_upstream.sly_data`; session `sly_data` is rebuilt from the client payload
each turn, so without that declaration the log would not survive a turn. It is deliberately absent
from `to_tracing`, because it holds what the requester said about their own estate.

A malformed or missing payload is an error, never a silent restart: an interview that began again
would have the requester answering the same questions with no explanation.

## The design brief

The brief's two answer sections are derived from the log rather than recalled:

- **Confirmed requirements** — answers the requester gave.
- **Assumptions I made** — defaults the designer chose, flagged when recorded.

A corrected answer therefore reaches the brief with its new value. The distinction between confirmed
and assumed is recorded at the moment it is known, which is the only moment it is reliable.

## Domains without a knowledge pack

A pack buys **verified operating standards**. It is not a precondition for the interview itself.

When no curated domain matches, the designer derives its own questions and starts the same interview
with them, so numbered options, ambiguity handling and correction all apply. Such an interview
reports `curated: false` for its whole life, and no operating standard may be presented as verified.
Derived questions require at least two example answers each, since one option is nothing to choose
between.

## Verification

The interview is checked at two levels, both without a model.

`interview_review` reviews a recorded transcript against the promised behaviour and reports:
`OPTIONS` (a question offered no numbered choice or no escape), `AMBIGUITY` (a reply consistent with
several options was resolved rather than queried), `REVISION` (a correction was answered past),
alongside the existing interview, brief, fidelity and phase-gate checks. Clarifications and
revisits are counted separately from questions, and distinct questions are counted rather than
question turns, so disambiguating and correcting cannot be mistaken for an interview that overran
its pack.

The state machine, the matcher boundary and the matcher guards are covered by unit tests that
inject a matcher, so the policy is exercised against readings a model might return — including
malformed and hostile ones — with no provider involved. A clean deliberation is generated for every
shipped pack and must review clean, and no domain vocabulary is permitted in the method layer's
executable code.

## Configuration

| Variable | Effect |
| --- | --- |
| `AGENT_NETWORK_DESIGNER_MATCH_MODEL` | Model used to read free-text replies. Unset or `off` uses containment. |
| `AGENT_NETWORK_DESIGNER_KNOWDOCS` | Root the knowledge packs are read from. |
