"""Run scanner binaries with the least privilege available inside the worker pod.

Scanners parse untrusted code, so a bug in one must not hand the attacker the worker's
secrets: the child gets a scrubbed environment (no DATABASE_URL / REDIS_*), its own process
group (the whole tree is killed on timeout) and resource limits.
"""
import os
import resource
import signal
import subprocess

SAFE_ENV = ("PATH", "LANG", "LC_ALL", "TZ", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE")
FSIZE = 512 * 1024 * 1024          # largest single file a scanner may write


def clean_env(extra: dict | None = None) -> dict:
    env = {k: os.environ[k] for k in SAFE_ENV if k in os.environ}
    env["HOME"] = "/tmp"
    env.update(extra or {})
    return env


def _limits(cpu_sec: int):
    def apply():
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_FSIZE, (FSIZE, FSIZE))
        resource.setrlimit(resource.RLIMIT_NOFILE, (1024, 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_sec, cpu_sec + 5))
    return apply


def run(cmd: list[str], timeout: int, env: dict | None = None) -> subprocess.CompletedProcess:
    """Like subprocess.run(capture_output, text); `env` = extra variables on top of a clean base.
    Raises FileNotFoundError / subprocess.TimeoutExpired exactly like subprocess.run."""
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         env=clean_env(env), start_new_session=True, preexec_fn=_limits(timeout * 2))  # noqa: PLW1509
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        p.communicate()
        raise
    return subprocess.CompletedProcess(cmd, p.returncode, out, err)
