# Open variables - clinical trial database lock

Ask these one at a time, in this order. Each line is: id, the question, example answers, and why the
answer changes the design.

- V1 | Study profile: phase, number of sites and subjects, and whether the study is blinded?
  | examples: phase III, 120 sites, 900 subjects, double-blind; phase I, single site, open label
  | why: decides how much reconciliation and unblinding control the network must enforce.
- V2 | Systems: which EDC and which safety database, and are there external data vendors?
  | examples: Medidata Rave with Argus safety; Veeva CDMS; central lab and ECG vendors
  | why: determines the reconciliation agents and the external data transfer gates.
- V3 | SDV model: 100% source data verification, or risk-based?
  | examples: 100% SDV; risk-based with critical variables only; remote monitoring
  | why: sets what evidence the SDV completeness gate must collect before lock.
- V4 | Coding: which dictionary versions apply, and who performs medical review of the coding?
  | examples: MedDRA 27.0 and WHODrug Global B3 2024; sponsor medical monitor reviews
  | why: fixes the version check and the reviewer in the coding gate.
- V5 | Authority: who authorises the soft lock and the hard lock, and how is the signature captured?
  | examples: data management lead soft locks, sponsor and biostatistics sign the hard lock in the EDC
  | why: defines the approval gate and the Part 11 electronic signature step.
- V6 | External data: which datasets must be received and reconciled before lock, and by when?
  | examples: central lab, PK, ECG, IRT randomisation data, all received two weeks before lock
  | why: decides the transfer and reconciliation gates and the lock-readiness date.
- V7 | Re-open policy: what happens if an error is found after hard lock?
  | examples: re-open requires sponsor and QA approval with a documented reason; no re-open, corrections
  handled in the statistical analysis
  | why: determines whether a controlled re-open path exists in the network at all.
