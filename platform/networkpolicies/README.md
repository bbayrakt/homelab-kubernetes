# NetworkPolicies

Supplemental Kubernetes NetworkPolicies (and later, Cilium policies) that
chart values cannot express.

## Conventions

- One file per policy, named after the target (`<workload>-allow-<what>.yaml`).
 Policies here are **additive**. Kubernetes NetworkPolicies union: a narrow
  allow rule supplements chart-rendered policies (it never needs to restate
  them, and it doesn't lift restrictions on anything else). Comment the file
  with the chart it supplements and why its values couldn't express the rule.
- Policies shipped by charts stay with their charts (e.g. ArgoCD's netpols in
  the argocd namespace, Longhorn's `networkPolicies` template).

## Current contents

| File | Purpose |
| --- | --- |
| `longhorn-manager-allow-metrics.yaml` | Allow `alloy-metrics` (grafana-cloud) to scrape longhorn-manager:9500 despite Longhorn's default-deny internal netpols (`networkPolicies.restrictInternalTraffic: true`). The chart's manager netpol hardcodes its ingress allow-list with no extension point, so a supplemental rule is the only way to keep the restriction and get the metrics. |
