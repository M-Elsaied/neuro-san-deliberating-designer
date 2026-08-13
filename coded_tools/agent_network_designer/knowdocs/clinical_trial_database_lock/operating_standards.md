# Operating standards - clinical trial database lock

These represent a TYPICAL clinical database lock SOP as practised across the industry under ICH E6 (GCP)
and 21 CFR Part 11. Individual sponsors' SOPs differ in detail; confirm against the study's own Data
Management Plan before relying on them.

Non-negotiable. Each standard must be embedded verbatim, with its id, in the instructions of the
agent that owns it.

- DBL-01: All data queries must be closed before lock, or formally documented and accepted as unresolved
  with a reason; no query may be silently abandoned.
- DBL-02: Source data verification and review must be complete to the extent required by the monitoring
  plan, and the completion evidenced, before lock.
- DBL-03: Medical coding of adverse events and concomitant medications must be complete and quality
  checked against the dictionary versions named in the Data Management Plan (for example MedDRA and
  WHODrug).
- DBL-04: Protocol deviations must be adjudicated and categorised, and serious adverse events reconciled
  against the safety database, before lock.
- DBL-05: Apply a soft lock first, allow only controlled corrections while it is in force, and record the
  hard lock with an approved electronic signature.
- DBL-06: No treatment unblinding may occur before the hard lock has been authorised; any re-opening of a
  locked database requires documented approval and an audit-trailed reason.
