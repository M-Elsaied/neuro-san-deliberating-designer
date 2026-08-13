# Open variables - Kubernetes cluster upgrade

Ask these one at a time, in this order. Each line is: id, the question, example answers, and why the
answer changes the design.

- V1 | Platform: managed or self-managed, and which distribution?
  | examples: AKS; EKS; GKE; self-managed kubeadm; OpenShift
  | why: decides whether the control-plane upgrade is a cloud operation or a kubeadm runbook, and who
  owns etcd backup.
- V2 | Estate and order: how many clusters, in which environments, and in what promotion order?
  | examples: dev then staging then prod; one prod cluster per region; a single shared cluster
  | why: sets the wave plan and how far a bad upgrade can spread.
- V3 | Version jump: current and target versions?
  | examples: 1.29 to 1.30; 1.28 to 1.31; latest patch release only
  | why: more than one minor version means several sequential upgrades, never a single jump.
- V4 | Node strategy: how are nodes replaced during the upgrade?
  | examples: surge upgrade with extra capacity; blue-green node pools; in-place rolling
  | why: decides spare capacity, cost and the rollback route.
- V5 | Workload risk: are there stateful workloads, singletons, or strict PodDisruptionBudgets?
  | examples: stateful sets with persistent volumes; single-replica services; strict PDBs that block
  drain
  | why: determines whether nodes can drain unattended and what may need a maintenance window.
- V6 | Window and approval: what is the change window, and which change record gates production?
  | examples: 4-hour Saturday window, ServiceNow CR approved by CAB; rolling with no fixed window
  | why: sets the change-control gate and the pace of the rollout.
- V7 | Validation and sign-off: who confirms workloads and ingress are healthy, and signs the cluster
  back into service?
  | examples: platform team via synthetic checks; app owners per namespace; SRE on-call
  | why: defines the hand-back gate and its owner.
