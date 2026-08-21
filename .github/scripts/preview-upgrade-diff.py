#!/usr/bin/env python3
"""preview-upgrade-diff.py - structural base-vs-target diff of chart bumps.

Renders each changed chart-sourced ArgoCD app at the base (main) and target
(PR) revisions and summarizes the structural deltas: CRDs added/removed with
version-level changes, object kinds added/removed, and apiVersion changes.
With --index (the CRD baseline JSON written by preview-baseline.py) it also
flags rendered CRDs whose versions differ from what the cluster currently
runs - the classic "will this upgrade break something" signal.

Informational only (exit 0): the render gate and the server-side dry-run own
the hard failures.

Usage:
    preview-upgrade-diff.py --base-dir <dir> --target-dir <dir>
        [--index <crd-baseline.json>] [--output <path>]
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path

import argocd_render


def log(msg: str) -> None:
    print(f"[preview-upgrade-diff] {msg}")


def index_docs(docs: list[dict]) -> dict[tuple[str, str], dict]:
    """Key rendered manifests by (kind, name)."""
    index: dict[tuple[str, str], dict] = {}
    for d in docs:
        meta = d.get("metadata") or {}
        name = meta.get("name")
        if not name:
            continue
        index[(d.get("kind", ""), name)] = d
    return index


def crd_versions(doc: dict) -> list[str]:
    versions = (doc.get("spec") or {}).get("versions") or []
    return sorted(v.get("name", "") for v in versions if v.get("name"))


def chart_sources(app_path: Path) -> list[tuple[str, dict, str, dict]]:
    """(app_name, source, dest_ns, helm_block) for chart sources in a dir."""
    found = []
    for doc in argocd_render.applications_in(app_path):
        spec = doc.get("spec") or {}
        dest_ns = (spec.get("destination") or {}).get("namespace") or "default"
        for app, source, _, kind in argocd_render.helm_sources(doc):
            if kind in ("helm", "git"):
                found.append((app, source, dest_ns, source.get("helm") or {}))
    return found


def render_checkout(checkout: Path, app: str) -> list[dict]:
    """Render all chart sources of an app dir inside a checkout."""
    docs: list[dict] = []
    app_path = checkout / app
    if not app_path.is_dir():
        return docs
    for name, source, dest_ns, helm_block in chart_sources(app_path):
        # Helm sources share no files: give each source its own temp dir
        # (values files and pulled tarballs must not collide).
        with tempfile.TemporaryDirectory(prefix="preview-diff.") as tmp:
            tmp = Path(tmp)
            if source.get("chart") or source.get("repoURL", "").startswith("oci://"):
                docs.extend(
                    argocd_render.render_helm(tmp, name, source, dest_ns, helm_block)
                )
            elif source.get("path"):
                rendered = argocd_render.render_git(
                    tmp, name, source, dest_ns, helm_block
                )
                if rendered is not None:
                    docs.extend(rendered)
    return docs


def delta_row(
    app: str, rev: str, base: dict, target: dict, baseline: dict
) -> list[str]:
    """Lines of structural deltas between base and target renders."""
    lines = [f"### {app}  ({rev})", ""]
    if not target:
        lines.append("_target render produced no manifests_")
        lines.append("")
        return lines

    base_crds = {k: v for k, v in base.items() if k[0] == "CustomResourceDefinition"}
    target_crds = {k: v for k, v in target.items() if k[0] == "CustomResourceDefinition"}
    added_crds = sorted(set(target_crds) - set(base_crds))
    removed_crds = sorted(set(base_crds) - set(target_crds))
    version_changes = [
        (name, crd_versions(base_crds[name]), crd_versions(target_crds[name]))
        for name in sorted(set(base_crds) & set(target_crds))
        if crd_versions(base_crds[name]) != crd_versions(target_crds[name])
    ]

    api_version_changes = sorted(
        name
        for name in set(base) & set(target)
        if base[name].get("apiVersion") != target[name].get("apiVersion")
    )
    added_by_kind: dict[str, int] = {}
    for kind, _ in sorted(set(target) - set(base)):
        if kind != "CustomResourceDefinition":
            added_by_kind[kind] = added_by_kind.get(kind, 0) + 1
    removed_by_kind: dict[str, int] = {}
    for kind, _ in sorted(set(base) - set(target)):
        if kind != "CustomResourceDefinition":
            removed_by_kind[kind] = removed_by_kind.get(kind, 0) + 1

    # Rendered CRDs whose version set is missing from (or newer than) what
    # the cluster currently runs.
    baseline_deltas = []
    for (_, name), doc in target_crds.items():
        versions = crd_versions(doc)
        current = baseline.get(name)
        if current is None:
            baseline_deltas.append(f"{name}: not in cluster baseline (new CRD)")
        elif current != versions:
            baseline_deltas.append(
                f"{name}: chart {', '.join(versions)} vs cluster "
                f"{', '.join(current)}"
            )

    def fmt(items: list[str]) -> str:
        return ", ".join(items) if items else "-"

    lines.append(
        f"- CRDs: +{len(added_crds)} -{len(removed_crds)} "
        f"version_changes={len(version_changes)}"
    )
    if added_crds:
        lines.append(f"  - added: {fmt([name for _, name in added_crds])}")
    if removed_crds:
        lines.append(f"  - removed: {fmt([name for _, name in removed_crds])}")
    for name, base_v, target_v in version_changes:
        lines.append(
            f"  - {name}: versions {', '.join(base_v)} -> {', '.join(target_v)}"
        )
    if added_by_kind:
        lines.append(
            "- objects added: "
            + fmt([f"{kind} x{count}" for kind, count in sorted(added_by_kind.items())])
        )
    if removed_by_kind:
        lines.append(
            "- objects removed: "
            + fmt([f"{kind} x{count}" for kind, count in sorted(removed_by_kind.items())])
        )
    if api_version_changes:
        changes = []
        for kind, name in api_version_changes:
            key = (kind, name)
            changes.append(
                f"{kind}/{name} {base[key].get('apiVersion')} -> "
                f"{target[key].get('apiVersion')}"
            )
        lines.append(f"- apiVersion changes: {fmt(changes)}")
    if baseline_deltas:
        lines.append("- vs cluster baseline:")
        for d in baseline_deltas:
            lines.append(f"  - {d}")
    lines.append("")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dir", required=True)
    parser.add_argument("--target-dir", required=True)
    parser.add_argument("--index", help="CRD baseline JSON from preview-baseline.py")
    parser.add_argument("--output", default="output/upgrade-diff.md")
    args = parser.parse_args()

    base = Path(args.base_dir)
    target = Path(args.target_dir)
    baseline: dict[str, list[str]] = {}
    if args.index:
        try:
            baseline = json.loads(Path(args.index).read_text())
        except (OSError, json.JSONDecodeError) as err:
            log(f"WARN could not read CRD baseline index {args.index}: {err}")

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

    lines = [
        "## Chart upgrade structural diff",
        "",
        (
            "Base (main) vs target (PR) rendered manifests for changed chart "
            "apps: CRD/object/apiVersion deltas, plus rendered-CRD differences "
            "against the live cluster baseline. Informational."
        ),
        "",
    ]
    rendered_any = False
    for app in apps:
        if not (target / app).is_dir():
            continue
        try:
            base_docs = render_checkout(base, app)
            target_docs = render_checkout(target, app)
        except RuntimeError as err:
            lines.append(f"### {app}")
            lines.append("")
            lines.append(f"_render error: {err}_")
            lines.append("")
            continue
        for app_name, source, _, _ in chart_sources(target / app):
            rev = source.get("targetRevision") or "latest"
            rendered_any = True
            lines.extend(
                delta_row(
                    app,
                    f"{app_name}@{rev}",
                    index_docs(base_docs),
                    index_docs(target_docs),
                    baseline,
                )
            )

    if not rendered_any:
        lines.append("_no chart apps changed in this PR_")
        lines.append("")
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text("\n".join(lines))
    log(f"report written to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
