#!/usr/bin/env python3
"""preview-dryrun.py - simulate every changed ArgoCD app against the PR vCluster.

Layer 2 of the preview funnel: render each changed app (Helm/git-chart
sources with ArgoCD-exact flags, plain directories as-is) and run it through
`kubectl apply --server-side --dry-run=server` against the PR vCluster's
live API server (including the CRD baseline). Nothing is ever created;
schema, validation and conflict errors are caught before any preview
deploys. This covers host-bound apps too (longhorn, cilium, issuer, ...),
which can never be deployed into a vCluster but whose rendered manifests can
still be validated against the baseline's CRDs.

Classification per app:
- OK: the server accepts the rendered set
- schema/validation/conflict error -> FAIL (workflow check fails)
- "no matches for kind" -> MISSING CRD (warning only: charts that ship their
  own CRDs register them on a real sync, so this is expected for bundled
  CRDs that the baseline does not have yet)
- "namespace ... not found" -> MISSING NAMESPACE (warning only)

Usage:
    preview-dryrun.py --base-dir <dir> --target-dir <dir>
        --kubeconfig <vcluster-kubeconfig>
        [--output <path>]
"""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import argocd_render
import yaml


def log(msg: str) -> None:
    print(f"[preview-dryrun] {msg}")


def run(cmd, kubeconfig: str, input_text: str | None = None):
    env = dict(os.environ)
    env["KUBECONFIG"] = kubeconfig
    return subprocess.run(
        cmd, env=env, input=input_text, capture_output=True, text=True, check=False
    )


def render_app(app_dir: Path) -> list[dict]:
    """Render an app directory the way ArgoCD would sync it.

    Chart-sourced apps (directories with Application CRs) render each chart
    via helm and add the directory's plain manifests (namespaces, Application
    CRs, ...). Plain directories render as-is.
    """
    apps = argocd_render.applications_in(app_dir)
    docs: list[dict] = []
    plain = [d for d in argocd_render.render_directory(app_dir) if d not in apps]
    docs.extend(plain)
    for doc in apps:
        spec = doc.get("spec") or {}
        dest_ns = (spec.get("destination") or {}).get("namespace") or "default"
        for app, source, _, kind in argocd_render.helm_sources(doc):
            helm_block = source.get("helm") or {}
            # Helm sources share no files: give each source its own temp dir
            # (values files and pulled tarballs must not collide).
            with tempfile.TemporaryDirectory(prefix="preview-dryrun.") as src_tmp:
                if kind == "git":
                    rendered = argocd_render.render_git(
                        Path(src_tmp), app, source, dest_ns, helm_block
                    )
                    if rendered is None:
                        continue  # plain directory inside a git source
                else:
                    rendered = argocd_render.render_helm(
                        Path(src_tmp), app, source, dest_ns, helm_block
                    )
            docs.extend(rendered)
    return docs


def classify(stderr: str) -> tuple[str, str]:
    """Map kubectl stderr to (result, detail)."""
    if "no matches for kind" in stderr:
        kinds = sorted(
            {
                line.split("no matches for kind")[1].split('"')[1]
                for line in stderr.splitlines()
                if "no matches for kind" in line
            }
        )
        return "MISSING CRD", ", ".join(kinds) or stderr.strip()[:400]
    if "not found" in stderr and "namespace" in stderr:
        return "MISSING NAMESPACE", stderr.strip()[:400]
    return "FAIL", stderr.strip()[:4000]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dir", required=True)
    parser.add_argument("--target-dir", required=True)
    parser.add_argument("--kubeconfig", required=True)
    parser.add_argument("--output", default="output/dryrun.md")
    args = parser.parse_args()

    base = Path(args.base_dir)
    target = Path(args.target_dir)
    apps = sorted(
        {
            a
            for a in (
                argocd_render.app_for_path(f)
                for f in argocd_render.changed_files(base, target)
            )
            if a
        }
    )
    log(f"changed apps: {apps}")

    rows: list[str] = []
    failures = 0
    for app in apps:
        app_path = target / app
        if not app_path.is_dir():
            rows.append(f"| {app} | :fast_forward: Removed in PR | app directory deleted |")
            continue
        try:
            docs = render_app(app_path)
            if not docs:
                rows.append(f"| {app} | :warning: Empty | no manifests rendered |")
                continue
            manifest = "---\n".join(
                yaml.safe_dump(d, sort_keys=False) for d in docs
            )
            res = run(
                ["kubectl", "apply", "--server-side", "--dry-run=server", "-f", "-"],
                args.kubeconfig,
                manifest,
            )
            detail = "server accepted"
            if res.returncode != 0:
                result, detail = classify(res.stderr)
                if result == "FAIL":
                    failures += 1
                rows.append(
                    f"| {app} | :{ 'x' if result == 'FAIL' else 'warning'}: "
                    f"{result} | {detail.replace('|', '/')} |"
                )
                log(f"{app}: {result} - {detail[:200]}")
                continue
            rows.append(f"| {app} | :white_check_mark: OK | {len(docs)} resources |")
            log(f"{app}: server accepted {len(docs)} resources")
        except RuntimeError as err:
            failures += 1
            rows.append(f"| {app} | :x: FAIL | render error: {str(err).replace('|', '/')[:400]} |")
            log(f"{app}: render error: {err}")

    lines = [
        "## Server-side dry-run (simulation)",
        "",
        (
            "Every changed app was rendered at the PR revision and validated "
            "against the PR vCluster's live API server (`kubectl apply "
            "--server-side --dry-run=server`) - nothing was created. Schema and "
            "validation errors are hard failures; missing CRDs/namespaces are "
            "warnings (charts that ship their own CRDs register them on a real "
            "sync)."
        ),
        "",
        "| App | Result | Details |",
        "| --- | --- | --- |",
    ]
    lines.extend(rows)
    lines.append("")
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text("\n".join(lines))
    log(f"report written to {args.output} ({failures} failure(s))")
    if failures:
        log(f"{failures} app(s) failed the server-side dry-run")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
