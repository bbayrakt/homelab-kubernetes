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
