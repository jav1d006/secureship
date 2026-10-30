"""One cheap walk over the extracted project, so scanners that have nothing to look at can be skipped
(the heavy ones - Semgrep, Checkov - cost many seconds just to start)."""
import os
from dataclasses import dataclass, field
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "vendor", "dist", "build", "__pycache__",
             ".next", "target", ".tox", ".mypy_cache"}
MAX_PATHS = 20000

SOURCE_EXTS = {"py", "js", "jsx", "mjs", "cjs", "ts", "tsx", "go", "java", "kt", "scala", "rb", "php",
               "cs", "c", "h", "cpp", "cc", "rs", "swift", "m", "lua", "ex", "exs", "yaml", "yml", "tf"}
SEMGREP_SOURCE_EXTS = SOURCE_EXTS - {"yaml", "yml", "tf"} | {"tf"}   # tf is scanned by Semgrep too
DEP_FILES = {"requirements.txt", "pipfile.lock", "poetry.lock", "package-lock.json", "yarn.lock",
             "pnpm-lock.yaml", "go.mod", "go.sum", "gemfile.lock", "composer.lock", "cargo.lock",
             "pom.xml", "gradle.lockfile", "packages.lock.json", "mix.lock", "conan.lock", "pubspec.lock"}


@dataclass
class Inventory:
    exts: set = field(default_factory=set)
    names: set = field(default_factory=set)
    paths: list = field(default_factory=list)

    def any_ext(self, *exts: str) -> bool:
        return bool(self.exts.intersection(exts))

    def any_name(self, pred) -> bool:
        return any(pred(n) for n in self.names)

    def any_path(self, pred) -> bool:
        return any(pred(p) for p in self.paths)


def inventory(root: Path) -> Inventory:
    inv = Inventory()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            low = name.lower()
            inv.names.add(low)
            if "." in low:
                inv.exts.add(low.rsplit(".", 1)[1])
            if len(inv.paths) < MAX_PATHS:
                inv.paths.append(os.path.relpath(os.path.join(dirpath, name), root).replace(os.sep, "/").lower())
    return inv


def is_dockerfile(name: str) -> bool:
    return name.startswith("dockerfile") or name.endswith(".dockerfile") or name == "containerfile"


# scanner key -> (predicate over Inventory, reason shown when skipped)
RELEVANT = {
    "secrets": (lambda i: True, ""),
    "dependencies": (lambda i: i.any_name(lambda n: n in DEP_FILES or n.endswith((".csproj", ".gemspec"))),
                     "no dependency manifest or lock file found"),
    "code": (lambda i: i.any_ext("py"), "no Python files found"),
    "semgrep": (lambda i: i.any_ext(*SEMGREP_SOURCE_EXTS), "no supported source files found"),
    "iac": (lambda i: i.any_ext("tf", "tfvars", "yaml", "yml", "bicep") or i.any_name(is_dockerfile)
            or i.any_path(lambda p: p.endswith((".template", "template.json"))),
            "no infrastructure files found"),
    "checkov": (lambda i: i.any_ext("tf", "tfvars", "yaml", "yml", "bicep") or i.any_name(is_dockerfile)
                or i.any_path(lambda p: p.endswith((".template", "template.json"))),
                "no infrastructure or CI configuration files found"),
    "docker": (lambda i: i.any_name(is_dockerfile), "no Dockerfile found"),
    "shell": (lambda i: i.any_ext("sh", "bash"), "no shell scripts found"),
}


def skip_reason(key: str, inv: Inventory) -> str | None:
    pred, reason = RELEVANT.get(key, (lambda i: True, ""))
    return None if pred(inv) else reason


def checkov_frameworks(inv: Inventory) -> str:
    """Only the Checkov frameworks that can match something in this project (each one costs time)."""
    fw = []
    if inv.any_ext("tf", "tfvars"):
        fw.append("terraform")
    if inv.any_name(is_dockerfile):
        fw.append("dockerfile")
    if inv.any_ext("bicep"):
        fw.append("bicep")
    if inv.any_ext("yaml", "yml", "json"):
        fw += ["kubernetes", "cloudformation"]
        if inv.any_path(lambda p: p.startswith(".github/workflows/")):
            fw.append("github_actions")
        if ".gitlab-ci.yml" in inv.names:
            fw.append("gitlab_ci")
        if "serverless.yml" in inv.names or "serverless.yaml" in inv.names:
            fw.append("serverless")
        if inv.any_name(lambda n: n.startswith(("openapi", "swagger"))):
            fw.append("openapi")
        if inv.any_path(lambda p: "playbook" in p or p.startswith(("roles/", "playbooks/"))):
            fw.append("ansible")
    if inv.any_ext("json") and inv.any_path(lambda p: p.endswith(("template.json", ".template"))):
        fw += ["arm", "cloudformation"]
    return ",".join(dict.fromkeys(fw)) or "kubernetes"
