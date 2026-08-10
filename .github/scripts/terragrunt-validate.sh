#!/usr/bin/env bash
# Runs `terragrunt validate --all` across infra/ (pre-commit hook).
# env.hcl sops-decrypts infra/secrets.sops.yaml, so without an age key the
# units can't be evaluated. Skip instead of failing.
set -e

root="$(cd "$(dirname "$0")/../.." && pwd)"
age_key_file="${SOPS_AGE_KEY_FILE:-$HOME/.config/sops/age/keys.txt}"

if [[ -z "${SOPS_AGE_KEY:-}" && ! -f "$age_key_file" ]]; then
  echo "terragrunt-validate: no SOPS age key available, skipping (set SOPS_AGE_KEY to enable)"
  exit 0
fi

cd "$root/infra"
${TERRAGRUNT_CMD:-terragrunt} validate --all
