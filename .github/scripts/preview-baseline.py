#!/usr/bin/env python3
"""preview-baseline.py - maintain the per-PR CRD baseline in the PR vCluster.

Exports the CRDs currently deployed on the HOST cluster (every ArgoCD chart
plus cluster-unit CRDs such as Cilium and Gateway API) and applies them into
the PR vCluster. The baseline is therefore automatically maintained by what
the cluster actually runs: a Renovate bump that installs new CRDs via
ArgoCD is picked up by the next preview run. Nothing is committed to the
repo.

The exported CRD index is also written to --index for
preview-upgrade-diff.py to report "chart CRDs vs baseline" deltas.

Usage:
    preview-baseline.py --host-kubeconfig <path> --vcluster-kubeconfig <path>
        [--index <path>] [--output <path>]
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml


def log(msg: str) -> None:
    print(f"[preview-baseline] {msg}")


def run(cmd, kubeconfig: str, input_text: str | None = None):
    env = dict(os.environ)
    env["KUBECONFIG"] = kubeconfig
    return subprocess.run(
        cmd, env=env, input=input_text, capture_output=True, text=True, check=False
    )


def export_crds(kubeconfig: str) -> list[dict]:
    """Export all CustomResourceDefinitions from a cluster."""
    res = run(["kubectl", "get", "crd", "-o", "yaml"], kubeconfig)
    if res.returncode != 0:
        raise RuntimeError(f"kubectl get crd failed:\n{res.stderr.strip()[:2000]}")
    crds: list[dict] = []
    for doc in yaml.safe_load_all(res.stdout):
        if not isinstance(doc, dict):
            continue
        if doc.get("kind") == "CustomResourceDefinition":
            crds.append(doc)
        elif doc.get("kind") == "List":
            crds.extend(
                item
                for item in doc.get("items", [])
                if isinstance(item, dict)
                and item.get("kind") == "CustomResourceDefinition"
            )
    if not crds:
        raise RuntimeError("no CRDs exported")
    # Stable ordering + dedupe (sorted by name keeps output reproducible).
    crds.sort(key=lambda c: c["metadata"]["name"])
    return crds


def crd_index(crds: list[dict]) -> dict[str, list[str]]:
    """Map CRD name -> served version names (for the upgrade-diff script)."""
    index: dict[str, list[str]] = {}
    for c in crds:
        versions = [v.get("name") for v in (c.get("spec") or {}).get("versions", [])]
        index[c["metadata"]["name"]] = sorted(v for v in versions if v)
    return index


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host-kubeconfig", required=True)
    parser.add_argument("--vcluster-kubeconfig", required=True)
    parser.add_argument("--index", default="output/crd-baseline.json")
    parser.add_argument("--output", default="output/baseline.md")
    args = parser.parse_args()

    try:
        crds = export_crds(args.host_kubeconfig)
    except RuntimeError as err:
        log(f"FAIL: {err}")
        return 1
    log(f"exported {len(crds)} CRDs from the host cluster")

    payload = "---\n".join(yaml.safe_dump(c, sort_keys=False) for c in crds) + "\n"
    res = run(["kubectl", "apply", "-f", "-"], args.vcluster_kubeconfig, payload)
    if res.returncode != 0:
        log(f"FAIL applying CRDs into the vCluster:\n{res.stderr.strip()[:2000]}")
        return 1
    applied = sum(
        1
        for line in res.stdout.splitlines()
        if "customresourcedefinition" in line
        and line.strip().endswith(("configured", "created", "unchanged"))
    )
    log(f"applied into the vCluster: {applied} CRDs (configured/created)")

    index = crd_index(crds)
    Path(args.index).parent.mkdir(parents=True, exist_ok=True)
    Path(args.index).write_text(json.dumps(index, indent=2, sort_keys=True) + "\n")

    lines = [
        "## CRD baseline (live export from prod)",
        "",
        (
            f"{len(crds)} CRDs exported from the host cluster and applied into the "
            "PR vCluster. The baseline follows what the cluster actually runs "
            "(chart bumps that ship new CRDs are picked up automatically). "
            "Deltas against chart-rendered CRDs are reported in the upgrade-diff "
            "section."
        ),
        "",
    ]
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text("\n".join(lines))
    log(f"index + report written to {args.index}, {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
