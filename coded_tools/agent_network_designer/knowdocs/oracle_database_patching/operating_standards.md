# Operating standards - Oracle database patching

Non-negotiable. Each standard must be embedded verbatim, with its id, in the instructions of the
agent that owns it.

- ODB-01: Apply the latest Release Update (RU) whenever possible; prefer an RU over one-off patches.
- ODB-02: Keep OPatch updated: verify and upgrade OPatch to the minimum version the RU README requires,
  before applying the patch.
- ODB-03: Take a full RMAN backup before applying any patch, and confirm the backup is restorable.
- ODB-04: Run datapatch after applying the database binaries; the patch is not complete, and the
  environment is not handed back, until datapatch has succeeded.
- ODB-05: Review the Oracle Support (MOS) patch README and its known-issues notes carefully before
  implementation.
- ODB-06: Validate application connectivity after patching, before returning the environment to service.
