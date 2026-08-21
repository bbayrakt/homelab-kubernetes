"""argocd_render.py - shared rendering core for ArgoCD Application sources.

Reproduces what the ArgoCD repo-server does to generate manifests for a
Helm/git source: resolve the chart revision, pull it (or shallow-clone the
git repo for git-sourced charts), and render it with `helm template
--include-crds` (ArgoCD's default; opt-out via `helm.skipCrds`) using the
exact release name, namespace, and values from the Application manifest.

Used by:
- check-argocd-apps.py    (pre-commit render gate)
- preview-dryrun.py       (render + server-side dry-run of PR changed apps)
- preview-upgrade-diff.py (base vs target structural diff of chart bumps)
"""

import subprocess
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None


def run(cmd, **kwargs):
    return subprocess.run(cmd, capture_output=True, text=True, check=False, **kwargs)


def helm_sources(doc):
    """Yield (app_name, source, dest_namespace, kind) for renderable sources.

    kind is "helm" for chart/OCI registry sources and "git" for git sources
    whose path is expected to contain a Helm chart. Sources with neither a
    chart nor a path (plain manifest apps) are skipped.
    """
    spec = doc.get("spec") or {}
    dest_ns = (spec.get("destination") or {}).get("namespace") or "default"
    sources = spec.get("sources") or ([spec["source"]] if "source" in spec else [])
    for src in sources:
        if src.get("ref"):
            continue
        repo = src.get("repoURL") or ""
        is_oci = repo.startswith("oci://")
        if src.get("chart") or is_oci:
            yield (doc.get("metadata") or {}).get("name", "?"), src, dest_ns, "helm"
        elif src.get("path") and repo.startswith(
            ("https://", "http://", "git@", "ssh://")
        ):
            yield (doc.get("metadata") or {}).get("name", "?"), src, dest_ns, "git"


def pull_args(source):
    """Return (helm pull argv, release_name) for a source."""
    repo = source["repoURL"]
    chart = source.get("chart", "")
    rev = source.get("targetRevision", "")
    version = ["--version", rev] if rev else []

    if repo.startswith("oci://"):
        return ["helm", "pull", repo, *version], chart or repo.rsplit("/", 1)[-1]
    if chart:
        if repo.startswith(("http://", "https://")):
            return ["helm", "pull", chart, "--repo", repo, *version], chart
        # scheme-less OCI-enabled helm repo (e.g. quay.io/..., ghcr.io/...)
        return ["helm", "pull", f"oci://{repo}/{chart}", *version], chart
    raise ValueError(f"unrecognized helm source: {repo} chart={chart!r}")


def values_args(work_dir, helm_block):
    """Write values files and return the helm --values/--set argv."""
    if yaml is None:
        raise RuntimeError("PyYAML is required")
    args = []
    values = helm_block.get("values")
    if values is not None:
        f = work_dir / "values.yaml"
        f.write_text(values)
        args += ["--values", str(f)]
    values_object = helm_block.get("valuesObject")
    if values_object is not None:
        f = work_dir / "values-object.yaml"
        f.write_text(yaml.safe_dump(values_object))
        args += ["--values", str(f)]
    for p in helm_block.get("parameters") or []:
        flag = "--set-string" if p.get("forceString") else "--set"
        args += [flag, f"{p['name']}={p['value']}"]
    return args


def template_args(work_dir, release, source, dest_ns, helm_block):
    """Build the helm template argv for a pulled chart tarball."""
    args = ["helm", "template", release]
    chart_paths = sorted(work_dir.glob("*.tgz"))
    if not chart_paths:
        raise FileNotFoundError(f"no chart tarball pulled into {work_dir}")
    args.append(str(chart_paths[0]))
    args += ["--namespace", dest_ns]
    # ArgoCD renders charts with --include-crds unless helm.skipCrds is set.
    if not helm_block.get("skipCrds"):
        args += ["--include-crds"]
    args += values_args(work_dir, helm_block)
    return args


def git_chart_args(tmp, app, source, dest_ns, helm_block):
    """Shallow-clone a git-source chart; return (release, rev, helm argv).

    Returns None when the path contains no Chart.yaml and the source carries
    no helm block (a plain directory app, not chart-rendered).
    """
    import shutil

    if not shutil.which("git"):
        raise RuntimeError("git not found (required for git-source charts)")
    repo = source["repoURL"]
    path = source.get("path") or "."
    rev = source.get("targetRevision") or "HEAD"
    clone_dir = tmp / "repo"
    if rev != "HEAD":
        res = run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--single-branch",
                "--branch",
                rev,
                repo,
                str(clone_dir),
            ]
        )
    else:
        res = run(["git", "clone", "--depth", "1", repo, str(clone_dir)])
    if res.returncode != 0:
        raise RuntimeError(f"git clone failed:\n{res.stderr.strip()}")
    chart_dir = clone_dir / path
    if not (chart_dir / "Chart.yaml").is_file():
        if helm_block:
            raise RuntimeError(f"no Chart.yaml at {path} (helm block present)")
        return None
    release = helm_block.get("releaseName") or app
    args = [
        "helm",
        "template",
        release,
        str(chart_dir),
        "--namespace",
        dest_ns,
    ]
    # ArgoCD renders charts with --include-crds unless helm.skipCrds is set.
    if not helm_block.get("skipCrds"):
        args += ["--include-crds"]
    args += values_args(tmp, helm_block)
    return release, rev, args


def parse_yaml(text: str, what: str) -> list[dict]:
    """Parse a YAML stream into a list of mapping documents."""
    if yaml is None:
        raise RuntimeError("PyYAML is required")
    try:
        return [d for d in yaml.safe_load_all(text) if isinstance(d, dict)]
    except yaml.YAMLError as err:
        raise RuntimeError(f"{what}: invalid YAML: {err}") from err


def render_helm(
    tmp: Path, app: str, source: dict, dest_ns: str, helm_block: dict
) -> list[dict]:
    """Pull and render a helm/OCI source; return the parsed manifests."""
    release = helm_block.get("releaseName") or source.get("chart", "")
    pull, default_release = pull_args(source)
    res = run(pull + ["--destination", str(tmp)])
    if res.returncode != 0:
        raise RuntimeError(f"helm pull failed:\n{res.stderr.strip()}")
    release = release or default_release
    res = run(template_args(tmp, release, source, dest_ns, helm_block))
    if res.returncode != 0:
        raise RuntimeError(f"helm template failed:\n{res.stderr.strip()}")
    return parse_yaml(res.stdout, f"helm template of {app}")


def render_git(
    tmp: Path, app: str, source: dict, dest_ns: str, helm_block: dict
) -> list[dict] | None:
    """Render a git-source chart; None when the path holds no Chart.yaml."""
    rendered = git_chart_args(tmp, app, source, dest_ns, helm_block)
    if rendered is None:
        return None
    _, rev, args = rendered
    res = run(args)
    if res.returncode != 0:
        raise RuntimeError(f"helm template failed:\n{res.stderr.strip()}")
    return parse_yaml(res.stdout, f"helm template of {app}@{rev}")


def render_directory(path: Path) -> list[dict]:
    """Render a plain-directory source (ArgoCD directory semantics)."""
    if yaml is None:
        raise RuntimeError("PyYAML is required")
    docs: list[dict] = []
    for p in sorted(path.rglob("*.yaml")) + sorted(path.rglob("*.yml")):
        if any(part.startswith(".") for part in p.parts):
            continue
        try:
            docs.extend(parse_yaml(p.read_text(), str(p)))
        except OSError as err:
            raise RuntimeError(f"{p}: {err}") from err
    return docs


def applications_in(path: Path) -> list[dict]:
    """All ArgoCD Application CRs under a path (recursive)."""
    return [d for d in render_directory(path) if d.get("kind") == "Application"]


def git_out(target_dir: Path, args: list[str]) -> str:
    res = run(["git", "-C", str(target_dir), *args])
    if res.returncode != 0:
        raise RuntimeError(f"git {args[0]} failed:\n{res.stderr.strip()}")
    return res.stdout.strip()


def changed_files(base_dir: Path, target_dir: Path) -> list[str]:
    """Files changed between the base and target checkouts."""
    base_sha = git_out(base_dir, ["rev-parse", "HEAD"])
    target_sha = git_out(target_dir, ["rev-parse", "HEAD"])
    try:
        out = git_out(target_dir, ["diff", "--name-only", base_sha, target_sha])
    except RuntimeError:
        # base SHA not in the target checkout's object store (main moved):
        # fall back to the target checkout's own refs.
        out = git_out(target_dir, ["diff", "--name-only", "origin/main...HEAD"])
    return [f for f in out.splitlines() if f]


def app_for_path(path: str) -> str | None:
    """Map a changed file to its app directory (platform/x or apps/x).

    Chart apps live in platform/helm-charts/<chart>/application.yaml and are
    managed per chart dir (the platform ApplicationSet generates one app per
    subdir), so the mapping resolves to the chart dir, not helm-charts.
    """
    parts = path.split("/")
    if len(parts) >= 2 and parts[0] in ("platform", "apps") and parts[1]:
        if len(parts) >= 3 and parts[0] == "platform" and parts[1] == "helm-charts":
            return f"platform/helm-charts/{parts[2]}"
        return f"{parts[0]}/{parts[1]}"
    return None
