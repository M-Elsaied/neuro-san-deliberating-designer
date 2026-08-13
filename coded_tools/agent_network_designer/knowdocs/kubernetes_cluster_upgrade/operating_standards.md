# Operating standards - Kubernetes cluster upgrade

Non-negotiable. Each standard must be embedded verbatim, with its id, in the instructions of the
agent that owns it.

- K8S-01: Upgrade one minor version at a time and never skip a minor version; the control plane may run
  at most one minor version ahead of the kubelets it serves.
- K8S-02: Back up etcd (or confirm the managed control-plane backup) before the upgrade begins, and
  verify the snapshot is restorable.
- K8S-03: Scan every workload manifest and controller for APIs removed or deprecated in the target
  version, and remediate them before the upgrade rather than during it.
- K8S-04: Upgrade the control plane first and confirm it is healthy before any node pool is touched.
- K8S-05: Cordon and drain each node, honouring PodDisruptionBudgets and termination grace periods;
  never force-delete pods to make a drain finish faster.
- K8S-06: Validate workload readiness and ingress health after each node or pool before moving to the
  next one; the upgrade is not complete while any workload is degraded.
