# Dashboard JSON exports

Each file here is the raw JSON export of a dashboard from the Grafana Cloud UI
(Share → Export → Download JSON), named after the resource in `../main.tf`.

Requirements:

- Keep the dashboard's existing `uid` — the matching `grafana_dashboard`
  resource in `../main.tf` must reference the same uid, otherwise Terraform
  creates a duplicate.
- Keep the export as-is (the `id`/`version` fields are accepted by the
  provider); the `check-json` pre-commit hook validates the files.
- Don't re-export with a fresh uid on every tweak — Terraform would replace
  the dashboard instead of updating it. Edit the JSON file directly and let
  `terragrunt apply` push the change.

## `cilium-hubble-flows.json` (template, not a raw export)

One exception to the raw-export rule: this dashboard is generated from the
hubble-observer chart's `dashboard/cilium-hubble-flows.json` (grafana.com
#23862), because it ships with `__inputs` placeholders instead of concrete
values. In this file they are already resolved:

- `${VAR_HUBBLEOBSERVERNAMESPACE}` → `hubble-observer` (release namespace)
- `${VAR_HUBBLEOBSERVERCF2CNPURL}` → `https://cf2cnp.icaninto.space`
- `${DS_LOKI}` → left as-is; the `grafana_dashboard.cilium_hubble_flows`
  resource in `../main.tf` replaces it with the managed Loki datasource uid
  (`data.grafana_data_source.logs`, name `grafanacloud-<slug>-logs`) at apply
  time.

Re-generate from the chart when the upstream dashboard changes:

```sh
cd platform/helm-charts/hubble-observer  # or the helm/dashboard dir of the chart
python3 - <<'EOF'
import json
raw = open('dashboard/cilium-hubble-flows.json').read()  # adjust path
out = json.dumps(json.loads(raw), indent=2)
out = out.replace('${VAR_HUBBLEOBSERVERNAMESPACE}', 'hubble-observer')
out = out.replace('${VAR_HUBBLEOBSERVERCF2CNPURL}', 'https://cf2cnp.icaninto.space')
assert '${DS_LOKI}' in out
open('../../infra/grafana-cloud-config/dashboards/cilium-hubble-flows.json', 'w').write(out)
EOF
```
