#!/usr/bin/env python3
"""pr-preview.py - deploy changed ArgoCD apps into the preview vCluster.

The PR preview workflow checks out the base (main) and target
(refs/pull/N/merge) branches and runs this script, which:

1. computes the changed files and maps them to app directories
   (platform/<app> or apps/<app>)
2. filters them against an allowlist of apps that can run in a vCluster
   (no CRDs, no host infrastructure, no storage/credentials dependencies)
3. creates one ArgoCD Application per changed, testable app
   (preview-pr-<N>-<app>, targetRevision refs/pull/N/merge, automated
   sync with prune + selfHeal, resources finalizer) in the ArgoCD that
   runs inside the vCluster
4. waits for Synced + Healthy per app, collecting the last operation
   error and pod crash details on failure
5. writes a markdown report and exits non-zero if any tested app failed
   to become healthy (the workflow still posts the comment)

Everything talks to the vCluster through kubectl, so the script is
dependency-free (Python stdlib only).

Usage:
    pr-preview.py --repo-url <url> --pr <number>
        --base-dir <dir> --target-dir <dir>
        [--argocd-namespace <ns>] [--kubeconfig <path>]
        [--timeout <seconds>] [--output <path>]
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

APP_LABEL_KEY = "preview.homelab/pr"

# Apps that can run meaningfully inside the vCluster: plain manifests,
# namespace-scoped workloads, no CRDs, no host-only controllers.
ALLOWLIST = {
    "platform/metrics-server": "plain manifests, no CRDs",
    "platform/kubelet-serving-cert-approver": (
        "self-contained namespace + RBAC + Deployment"
    ),
}

# Prefixes that are never testable in a vCluster, with the reason shown in
# the report. The longest matching prefix wins.
SKIP_PREFIXES = [
    (
        "platform/helm-charts",
        (
            "Helm chart - CRD installer or host infrastructure "
            "(cert-manager, external-dns, Longhorn, ARC, ...)"
        ),
    ),
    (
        "platform/network",
        "Cilium Gateway API resources - require the host Cilium controllers",
    ),
    (
        "platform/issuer",
        "cert-manager ClusterIssuer - requires the host cert-manager",
    ),
    ("platform/homelab-runner", "host-cluster runner RBAC"),
    (
        "platform/cluster-viewer",
        "cluster-scoped view RBAC - not testable in a vCluster",
    ),
    ("apps", "not yet on the preview allowlist"),
]

DEFAULT_SKIP_REASON = (
    "not on the preview allowlist (CRD installer / host infrastructure / credentials)"
)

REVISION_PREFIX = "refs/pull"
DESTINATION_SERVER = "https://kubernetes.default.svc"


def log(msg: str) -> None:
    print(f"[pr-preview] {msg}")


def run(cmd, **kwargs):
    return subprocess.run(cmd, capture_output=True, text=True, check=False, **kwargs)


def git_run(target_dir: Path, args: list[str]) -> str:
    res = run(["git", "-C", str(target_dir), *args])
    if res.returncode != 0:
        raise RuntimeError(f"git {args[0]} failed:\n{res.stderr.strip()}")
    return res.stdout.strip()


def changed_files(base_dir: Path, target_dir: Path) -> list[str]:
    """Files changed between the base and target checkouts."""
    base_sha = git_run(base_dir, ["rev-parse", "HEAD"])
    target_sha = git_run(target_dir, ["rev-parse", "HEAD"])
    try:
        out = git_run(target_dir, ["diff", "--name-only", base_sha, target_sha])
    except RuntimeError:
        # base SHA not in the target checkout's object store (main moved):
        # fall back to the target checkout's own refs.
        out = git_run(target_dir, ["diff", "--name-only", "origin/main...HEAD"])
    return [f for f in out.splitlines() if f]


def app_for_path(path: str) -> str | None:
    """Map a changed file to its app directory (platform/x or apps/x)."""
    parts = path.split("/")
    if len(parts) >= 2 and parts[0] in ("platform", "apps") and parts[1]:
        return f"{parts[0]}/{parts[1]}"
    return None


def classify_app(app: str) -> tuple[bool, str]:
    """Return (testable, reason) for an app directory."""
    if app in ALLOWLIST:
        return True, ALLOWLIST[app]
    for prefix, reason in SKIP_PREFIXES:
        if app == prefix or app.startswith(prefix + "/"):
            return False, reason
    return False, DEFAULT_SKIP_REASON


def app_name(app: str, pr: int) -> str:
    """DNS-safe Application name for a preview deployment."""
    basename = app.rsplit("/", 1)[-1].lower()
    sanitized = "".join(c if c.isalnum() or c == "-" else "-" for c in basename)
    return f"preview-pr-{pr}-{sanitized}"


def application_manifest(
    name: str, namespace: str, repo_url: str, path: str, revision: str, pr: int
) -> str:
    """Render the ArgoCD Application CR for a preview deployment."""
    return f"""apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: {name}
  namespace: {namespace}
  labels:
    {APP_LABEL_KEY}: "{pr}"
  finalizers:
    - resources-finalizer.argoproj.io
spec:
  project: default
  source:
    repoURL: {repo_url}
    targetRevision: {revision}
    path: {path}
    directory:
      recurse: true
  destination:
    server: {DESTINATION_SERVER}
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    retry:
      limit: 5
      backoff:
        duration: 30s
        maxDuration: 5m
        factor: 2
"""


class Kubectl:
    """Thin wrapper around kubectl against the preview cluster."""

    def __init__(self, kubeconfig: str | None):
        self.kubeconfig = kubeconfig
        self.env = dict(os.environ)
        if kubeconfig:
            self.env["KUBECONFIG"] = kubeconfig

    def _run(self, args: list[str]) -> subprocess.CompletedProcess:
        return run(["kubectl", *args], env=self.env)

    def apply(self, manifest: str) -> None:
        res = subprocess.run(
            ["kubectl", "apply", "-f", "-"],
            input=manifest,
            capture_output=True,
            text=True,
            check=False,
            env=self.env,
        )
        if res.returncode != 0:
            raise RuntimeError(f"kubectl apply failed:\n{res.stderr.strip()}")

    def get_json(self, *args: str) -> dict:
        res = self._run(["get", *args, "-o", "json"])
        if res.returncode != 0:
            raise RuntimeError(f"kubectl get failed:\n{res.stderr.strip()}")
        try:
            return json.loads(res.stdout)
        except json.JSONDecodeError as err:
            raise RuntimeError(f"kubectl returned invalid JSON: {err}") from err

    def get_text(self, *args: str) -> str:
        res = self._run(["get", *args])
        return res.stdout.strip() if res.returncode == 0 else ""

    def delete(self, *args: str) -> None:
        res = self._run(["delete", *args])
        if res.returncode != 0:
            log(f"WARN kubectl delete failed: {res.stderr.strip()}")

    def logs(self, namespace: str, pod: str, previous: bool = False) -> str:
        args = ["logs", "-n", namespace, pod, "--tail", "50"]
        if previous:
            args.append("--previous")
        res = self._run(args)
        if res.returncode != 0:
            return f"(no logs: {res.stderr.strip()[:200]})"
        return res.stdout.strip() or "(empty)"


def sync_health(doc: dict) -> tuple[str | None, str | None]:
    status = doc.get("status") or {}
    sync = (status.get("sync") or {}).get("status")
    health = (status.get("health") or {}).get("status")
    return sync, health


def operation_error(doc: dict) -> str | None:
    status = doc.get("status") or {}
    op = status.get("operationState") or {}
    if op.get("message"):
        return op["message"][:4000]
    phase = op.get("phase")
    if phase and phase not in ("Succeeded", ""):
        return f"operation phase: {phase}"
    conditions = status.get("conditions") or []
    msgs = [c.get("message", "") for c in conditions if c.get("message")]
    return msgs[0][:4000] if msgs else None


def wait_healthy(
    kubectl: Kubectl, ns: str, name: str, timeout: int
) -> tuple[bool, str]:
    """Wait for Synced + Healthy. Returns (ok, detail)."""
    deadline = time.monotonic() + timeout
    last_detail = "not yet synced"
    while time.monotonic() < deadline:
        doc = kubectl.get_json("application", name, "-n", ns)
        sync, health = sync_health(doc)
        if sync == "Synced":
            if health == "Healthy":
                return True, "Synced + Healthy"
            if health in (None, "", "Missing"):
                return True, "Synced (no health reported)"
        err = operation_error(doc)
        if err:
            return False, f"sync failed: {err}"
        last_detail = f"sync={sync or 'n/a'}, health={health or 'n/a'}"
        time.sleep(10)
    return False, f"timed out after {timeout}s ({last_detail})"


def pod_issues(kubectl: Kubectl, ns: str, name: str) -> str:
    """Collect pod state and crash log excerpts for an Application's resources.

    Namespaces and workload names come from the Application's own resource
    list (status.resources), so this also works when the manifests don't
    propagate the ArgoCD tracking label into pod templates (metrics-server).
    """
    workload_kinds = {"Deployment", "StatefulSet", "DaemonSet", "Job"}
    try:
        app_doc = kubectl.get_json("application", name, "-n", ns)
    except RuntimeError as err:
        return f"(could not read application: {err})"
    resources = (app_doc.get("status") or {}).get("resources") or []
    namespaces = sorted({r.get("namespace") for r in resources if r.get("namespace")})
    workload_names = [
        r.get("name") for r in resources if r.get("kind") in workload_kinds
    ]

    pods: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add_pod(pod: dict) -> None:
        meta = pod.get("metadata") or {}
        key = (meta.get("namespace", ""), meta.get("name", ""))
        if key not in seen:
            seen.add(key)
            pods.append(pod)

    try:
        labeled = kubectl.get_json(
            "pods", "-A", "-l", f"app.kubernetes.io/instance={name}"
        )
        for pod in labeled.get("items", []):
            add_pod(pod)
        for namespace in namespaces:
            by_ns = kubectl.get_json("pods", "-n", namespace)
            for pod in by_ns.get("items", []):
                pod_name = (pod.get("metadata") or {}).get("name", "")
                if any(pod_name.startswith(w) for w in workload_names if w):
                    add_pod(pod)
    except RuntimeError as err:
        return f"(could not list pods: {err})"

    lines = []
    for pod in pods:
        meta = pod.get("metadata") or {}
        ns_name = meta.get("namespace", "?")
        pod_name = meta.get("name", "?")
        phase = (pod.get("status") or {}).get("phase", "?")
        restarts = 0
        problems = []
        for container in (pod.get("status") or {}).get("containerStatuses", []):
            restarts += container.get("restartCount", 0)
            state = container.get("state") or {}
            if "waiting" in state:
                waiting = state["waiting"]
                problems.append(
                    f"{container['name']}: waiting "
                    f"({waiting.get('reason', '?')}) {waiting.get('message', '')}".strip()
                )
            if "terminated" in state and state["terminated"].get("exitCode") not in (
                None,
                0,
            ):
                problems.append(
                    f"{container['name']}: exited "
                    f"{state['terminated'].get('exitCode')} "
                    f"({state['terminated'].get('reason', '?')})"
                )
        lines.append(f"pod {ns_name}/{pod_name}: phase={phase} restarts={restarts}")
        for problem in problems:
            lines.append(f"  {problem}")
            for container in (pod.get("status") or {}).get("containerStatuses", []):
                state = container.get("state") or {}
                if "waiting" not in state and "terminated" not in state:
                    continue
                lines.append(f"  --- last logs ({container['name']}) ---")
                previous = container.get("restartCount", 0) > 0
                lines.append(kubectl.logs(ns_name, pod_name, previous=previous))
    return "\n".join(lines) if lines else "(no pods found)"


def stale_apps(kubectl: Kubectl, ns: str, pr: int, keep: set[str]) -> list[str]:
    """Applications previously created for this PR that are no longer changed."""
    doc = kubectl.get_json("applications", "-n", ns, "-l", f"{APP_LABEL_KEY}={pr}")
    return [
        item["metadata"]["name"]
        for item in doc.get("items", [])
        if item["metadata"]["name"] not in keep
    ]


def row(app: str, status: str, detail: str) -> str:
    return f"| {app} | {status} | {detail} |"


def write_report(
    output: Path, pr: int, changed: list[str], rows: list[str], failures: dict[str, str]
) -> None:
    lines = [f"## Preview deployment report (PR #{pr})", ""]
    lines.append("<details>")
    lines.append("<summary>Changed files</summary>")
    lines.append("")
    lines.append("```text")
    lines.extend(changed)
    lines.append("```")
    lines.append("")
    lines.append("</details>")
    lines.append("")
    lines.append("| App | Result | Details |")
    lines.append("| --- | --- | --- |")
    lines.extend(rows)
    for app, detail in failures.items():
        lines.append("")
        lines.append("<details>")
        lines.append(f"<summary>:x: {app} - failure details</summary>")
        lines.append("")
        lines.append("```text")
        lines.append(detail)
        lines.append("```")
        lines.append("")
        lines.append("</details>")
    lines.append("")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-url", required=True, help="git repo URL (https)")
    parser.add_argument("--pr", required=True, type=int, help="pull request number")
    parser.add_argument("--base-dir", required=True, help="base (main) checkout")
    parser.add_argument("--target-dir", required=True, help="target branch checkout")
    parser.add_argument("--argocd-namespace", default="argocd-preview")
    parser.add_argument(
        "--kubeconfig", default=os.environ.get("KUBECONFIG"), help="vCluster kubeconfig"
    )
    parser.add_argument("--timeout", type=int, default=300, help="per-app wait (s)")
    parser.add_argument("--output", default="output/preview-report.md")
    args = parser.parse_args()

    kubectl = Kubectl(args.kubeconfig)
    namespace = args.argocd_namespace
    revision = f"{REVISION_PREFIX}/{args.pr}/merge"

    changed = changed_files(Path(args.base_dir), Path(args.target_dir))
    apps = sorted({a for a in (app_for_path(f) for f in changed) if a})
    log(f"changed files: {len(changed)}, apps: {apps}")

    plan = {app: classify_app(app) for app in apps}
    rows = []
    failures: dict[str, str] = {}
    deployed: set[str] = set()
    failed = 0

    for app, (testable, reason) in plan.items():
        if not testable:
            rows.append(row(app, ":fast_forward: Skipped", reason))
            continue
        name = app_name(app, args.pr)
        deployed.add(name)
        log(f"deploying {app} as {name} ({revision})")
        try:
            kubectl.apply(
                application_manifest(
                    name, namespace, args.repo_url, app, revision, args.pr
                )
            )
            started = time.monotonic()
            ok, detail = wait_healthy(kubectl, namespace, name, args.timeout)
            elapsed = int(time.monotonic() - started)
            if ok:
                rows.append(
                    row(app, ":white_check_mark: Healthy", f"{detail} after {elapsed}s")
                )
            else:
                failed += 1
                rows.append(row(app, ":x: Degraded", f"{detail}"))
                failures[app] = detail
        except RuntimeError as err:
            failed += 1
            rows.append(row(app, ":x: Error", str(err)))
            failures[app] = str(err)
        if app in failures:
            failures[app] += "\n\n" + pod_issues(kubectl, namespace, name)

    # Remove preview applications for apps this PR no longer touches.
    try:
        for stale in stale_apps(kubectl, namespace, args.pr, deployed):
            log(f"removing stale preview app {stale}")
            kubectl.delete("application", stale, "-n", namespace, "--wait=false")
    except RuntimeError as err:
        log(f"WARN could not list stale apps: {err}")

    write_report(Path(args.output), args.pr, changed, rows, failures)
    log(f"report written to {args.output}")

    if not apps:
        log("no app changes detected in platform/ or apps/")
    if failed:
        log(f"{failed} app(s) failed to become healthy")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
