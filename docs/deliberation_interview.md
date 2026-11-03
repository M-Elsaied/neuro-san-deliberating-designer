# The deliberation interview

The Agent Network Designer gathers requirements before it builds anything. The governing rule is that
**nothing reaches the design brief as a confirmed requirement unless the requester confirmed it.**

## Questions are numbered choices

Each open variable is asked as a question with its pack's `examples` as numbered options, verbatim and in
the pack's order, then two escapes:

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

`InterviewLog` renders this text and the designer prints it, so options cannot be invented, reworded,
reordered or dropped, and each reply asks one question.

## How a reply is interpreted

A number or an exact quote records that option's own text. Any other reply fits an option when everything it
says, the option also says. Fitting none, it is recorded as written; fitting one, that option is offered back
for a yes (`confirm`), since it may say more than the requester did; fitting several, they are offered again
(`ambiguous`).

`1`, `1 or 4`, `option 2`, `#3` and `the second one` name options; `4 hours` and `1.29 to 1.31` are
answers. Naming two numbers is ambiguous, and a number not on the list that fits no option is asked about
again. A narrowed re-ask numbers its options from `1`, and the next number is read against that list,
not the pack's. `I'm not sure` and `something else` take their escapes as their numbers do. A `confirm`
takes `yes` for the option it offered back, and on `no` asks again with every option.

## Correcting an earlier answer

Any earlier answer can be changed before the build, from any question and from the brief. `go back` is the
entry before, `back three` three back (clamped to the first), `Q2` or `change question 2` that entry, and
`change the window answer` the entry whose subject it names. There is no limit on distance or count; labels
never shift; only the named entry is asked again, and the interview resumes at the first one still
unanswered. A subject matching several entries, or a count and a subject that disagree, is put back to the
requester. Going back is never refused as a request to skip.

## Session state and the brief

The interview lives in `sly_data` under `agent_network_interview_log`, which the front man allows upstream,
since session `sly_data` is rebuilt from the client each turn. It is not sent to tracing, because it holds
what the requester said about their estate. A malformed or missing log is an error, never a silent restart.
The brief's "Confirmed requirements" and "Assumptions I made" are taken from the log, so a corrected answer
reaches the brief with its new value.

## Domains without a knowledge pack

When no curated domain matches, the designer derives its own questions, each with at least two example
answers, and starts the same interview with them. It reports `curated: false` throughout, and no standard
may be presented as verified.
