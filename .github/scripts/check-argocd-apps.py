#!/usr/bin/env python3
"""check-argocd-apps.py - validate ArgoCD Application helm sources.

Reproduces what the ArgoCD repo-server does to generate manifests for a
Helm-source Application (see argocd_render.py): resolve the chart revision,
pull it (or shallow-clone the git repo for git-sourced charts), and render
it with `helm template --include-crds` (matching ArgoCD's default; opt-out
via `helm.skipCrds`) using the exact release name, namespace, and values
from the Application manifest. Catches wrong OCI repo paths, missing
versions, typoed values, and template errors before they reach the cluster.

Usage: check-argocd-apps.py <application.yaml>...
"""

import shutil
import sys
import tempfile
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

import argocd_render


def log(msg: str) -> None:
    print(f"[check-argocd-apps] {msg}")


def check_file(path: Path) -> int:
    if yaml is None:
        log("PyYAML not found, skipping (pip install pyyaml to validate ArgoCD apps)")
        return 0
    try:
        docs = yaml.safe_load_all(path.read_text())
    except yaml.YAMLError as err:
        log(f"FAIL {path}: invalid YAML: {err}")
        return 1
    for doc in docs:
        if not isinstance(doc, dict) or doc.get("kind") != "Application":
            continue
        for app, source, dest_ns, kind in argocd_render.helm_sources(doc):
            helm_block = source.get("helm") or {}
            if helm_block.get("valueFiles"):
                log(f"WARN {path}: {app} uses helm.valueFiles (not checked)")
            rev = source.get("targetRevision") or "latest"
            with tempfile.TemporaryDirectory(prefix="argocd-apps.") as tmp:
                tmp = Path(tmp)
                try:
                    if kind == "git":
                        rendered = argocd_render.render_git(
                            tmp, app, source, dest_ns, helm_block
                        )
                        if rendered is None:
                            log(
                                f"SKIP {path}: {app} ({source['repoURL']}@{rev}):"
                                " no Chart.yaml, not chart-rendered"
                            )
                            continue
                    else:
                        argocd_render.render_helm(
                            tmp, app, source, dest_ns, helm_block
                        )
                except Exception as err:  # noqa: BLE001
                    log(f"FAIL {path}: {app} ({source['repoURL']}@{rev}): {err}")
                    return 1
            log(f"OK   {path}: {app} ({source['repoURL']}@{rev}, ns {dest_ns})")
    return 0


def main() -> int:
    if not shutil.which("helm"):
        log("helm not found, skipping (install helm to validate ArgoCD apps)")
        return 0
    paths = [Path(p) for p in sys.argv[1:]]
    if not paths:
        log("no files given")
        return 0
    failed = 0
    for p in paths:
        if not p.is_file():
            log(f"SKIP {p}: not a file")
            continue
        failed |= check_file(p)
    if failed:
        log("one or more ArgoCD apps failed to resolve/render")
    else:
        log("all ArgoCD apps resolved and rendered")
    return failed


if __name__ == "__main__":
    sys.exit(main())
