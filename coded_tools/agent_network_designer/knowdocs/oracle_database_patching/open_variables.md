# Open variables - Oracle database patching

Ask these one at a time, in this order. Each line is: id, the question, example answers, and why the
answer changes the design.

- V1 | Topology: single instance, RAC, Data Guard standby, or Exadata?
  | examples: single instance, no standby; two-node RAC; RAC + physical standby; Exadata X8M
  | why: decides rolling versus a full outage, and whether a standby has to be patched too.
- V2 | Estate and order: which environments, how many databases, and what promotion order?
  | examples: DEV to QA to PROD; only PROD this cycle; DEV/QA shared, PROD separate
  | why: sets the wave plan and how many patch runs are needed.
- V3 | Window: change window length and downtime tolerance - is a rolling patch required?
  | examples: 4 hours, rolling required; 8 hours, full outage acceptable; no fixed window
  | why: decides node-by-node rolling versus a single outage window.
- V4 | Backup ownership: who takes the RMAN backup, and is a verified restore point required before the
  window opens?
  | examples: DBA team, verified restore required; platform team, no restore test; guaranteed restore
  point instead of a new full backup
  | why: determines the backup gate agent and whether patching may start.
- V5 | Approval: which change record gates production, and who approves it?
  | examples: ServiceNow CR approved by CAB; ServiceNow CR approved by the app owner; no formal gate in
  non-prod
  | why: determines the change-control gate before any production work.
- V6 | Rollback: expected rollback route?
  | examples: opatch rollback; flashback to a guaranteed restore point; restore from backup
  | why: decides what the rollback agent must be able to execute.
- V7 | Post-check sign-off: who validates application connectivity and signs the environment back into
  service?
  | examples: DBA team; application owner; operations/NOC synthetic checks
  | why: defines the hand-back gate and its owner.
