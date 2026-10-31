import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app import config, jobs, run_scan_job, worker

SID = "ab" * 16


def test_job_spec_is_isolated():
    spec = jobs.build_job(SID, ["secrets", "code"])
    pod = spec["spec"]["template"]["spec"]
    c = pod["containers"][0]
    assert pod["automountServiceAccountToken"] is False and pod["restartPolicy"] == "Never"
    assert spec["spec"]["activeDeadlineSeconds"] == config.SANDBOX_JOB_TIMEOUT
    assert {e["name"] for e in c["env"]} == {"SCAN_SCANNERS", "WORK_DIR", "HOME"}   # no DB / Redis variables
    assert "envFrom" not in c
    mounts = {m["mountPath"]: m for m in c["volumeMounts"]}
    assert mounts["/work/src"]["readOnly"] is True and mounts["/work/src"]["subPath"] == f"{SID}/src"
    assert mounts["/work/out"]["subPath"] == f"{SID}/out"          # only this scan's own folders
    assert c["securityContext"]["readOnlyRootFilesystem"] and c["securityContext"]["capabilities"] == {"drop": ["ALL"]}
    assert spec["metadata"]["labels"] == {"app": "scan-job"}


def write(tmp_path, obj):
    p = tmp_path / "result.json"
    p.write_text(obj if isinstance(obj, str) else json.dumps(obj))
    return p


def test_load_output_filters_untrusted_data(tmp_path):
    good = {"results": {"code": {"findings": [{"severity": "high"}, "junk"]}, "evil": {"findings": []}},
            "errors": {"secrets": "x" * 999}, "skipped": {}, "timings": {"code": 1.234, "evil": 9}}
    res, err, skipped, timings = jobs.load_output(write(tmp_path, good))
    assert res == {"code": {"findings": [{"severity": "high"}]}} and len(err["secrets"]) == 200
    assert timings == {"code": 1.23}


@pytest.mark.parametrize("bad", ["not json", {"results": []}, {"results": {}}, "[]"])
def test_load_output_rejects_malformed(tmp_path, bad):
    with pytest.raises(jobs.JobFailed):
        jobs.load_output(write(tmp_path, bad))


def test_load_output_size_cap_and_missing(tmp_path, monkeypatch):
    with pytest.raises(jobs.JobFailed):
        jobs.load_output(tmp_path / "nope.json")
    monkeypatch.setattr(jobs, "MAX_OUT_BYTES", 5)
    with pytest.raises(jobs.JobFailed):
        jobs.load_output(write(tmp_path, {"results": {}}))


class FakeKube:
    def __init__(self, status, on_create=None):
        self.status, self.on_create, self.calls = status, on_create, []

    def create_job(self, spec):
        self.calls.append("create")
        self.on_create and self.on_create()

    def get_job(self, name):
        self.calls.append("get")
        return {"status": self.status}

    def delete_job(self, name):
        self.calls.append("delete")


def test_run_in_job_success_and_always_deletes(tmp_path):
    def produce():
        (tmp_path / "out" / "result.json").write_text(json.dumps(
            {"results": {"code": {"findings": []}}, "errors": {}, "skipped": {}, "timings": {"code": 1}}))
    k = FakeKube({"succeeded": 1}, produce)
    res, *_ = jobs.run_in_job(SID, ["code"], tmp_path, client=k, poll=0)
    assert "code" in res and k.calls == ["create", "get", "delete"]


def test_run_in_job_failure_still_deletes(tmp_path):
    k = FakeKube({"failed": 1})
    with pytest.raises(jobs.JobFailed):
        jobs.run_in_job(SID, ["code"], tmp_path, client=k, poll=0)
    assert k.calls[-1] == "delete"


def test_run_in_job_deadline(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SANDBOX_JOB_TIMEOUT", -100)
    with pytest.raises(jobs.JobFailed, match="in time"):
        jobs.run_in_job(SID, ["code"], tmp_path, client=FakeKube({}), poll=0)


def test_job_entrypoint_writes_result(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir(); (tmp_path / "out").mkdir()
    monkeypatch.setenv("SCAN_SCANNERS", "code,shell")
    monkeypatch.setattr(run_scan_job, "run_scanners", lambda names, src: ({"code": {"findings": []}}, {}, {"shell": "none"}, {"code": 0.1}))
    run_scan_job.main(tmp_path / "src", tmp_path / "out")
    assert jobs.load_output(tmp_path / "out" / "result.json")[2] == {"shell": "none"}


def test_process_uses_job_mode(tmp_path, monkeypatch):
    import io
    import zipfile
    buf = io.BytesIO()
    zipfile.ZipFile(buf, "w").writestr("a.py", "x=1")
    done = {}

    class DB:
        get_upload = staticmethod(lambda sid: buf.getvalue())
        set_running = staticmethod(lambda sid: None)
        get_scanners = staticmethod(lambda sid: ["code"])
        set_done = staticmethod(lambda sid, score, result: done.update(score=score, result=result))
        clear_upload = staticmethod(lambda sid: None)
        set_failed = staticmethod(lambda sid, e: done.update(error=e))
    monkeypatch.setattr(worker, "db", DB)
    monkeypatch.setattr(config, "SANDBOX_MODE", "job")
    monkeypatch.setattr(config, "SANDBOX_WORK_DIR", tmp_path)
    seen = {}
    def fake(sid, names, scan_dir):
        seen["src"] = (scan_dir / "src" / "a.py").exists()
        return {"code": {"findings": []}}, {}, {}, {"code": 1.0}
    monkeypatch.setattr(worker.jobs, "run_in_job", fake)
    worker.process(SID)
    assert seen["src"] and done["score"] == 100 and not (tmp_path / SID).exists()


class Api(BaseHTTPRequestHandler):
    log = []

    def _r(self):
        Api.log.append((self.command, self.path, self.headers["Authorization"]))
        code = 404 if self.command == "GET" else 200
        self.send_response(code); self.end_headers(); self.wfile.write(b"{}")
    do_GET = do_POST = do_DELETE = _r

    def log_message(self, *a):
        pass


def test_kube_client_requests():
    srv = HTTPServer(("127.0.0.1", 0), Api)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    k = jobs.KubeClient(f"http://127.0.0.1:{srv.server_port}", token="tok", ca="/nonexistent")
    k.create_job({"a": 1}); assert k.get_job("scan-x") is None; k.delete_job("scan-x")
    srv.shutdown()
    base = f"/apis/batch/v1/namespaces/{config.SANDBOX_NAMESPACE}/jobs"
    assert Api.log == [("POST", base, "Bearer tok"), ("GET", f"{base}/scan-x", "Bearer tok"),
                       ("DELETE", f"{base}/scan-x?propagationPolicy=Background", "Bearer tok")]


def test_sweep_removes_old_dirs(tmp_path, monkeypatch):
    import os
    monkeypatch.setattr(config, "SANDBOX_WORK_DIR", tmp_path)
    (tmp_path / "old").mkdir(); (tmp_path / "new").mkdir()
    os.utime(tmp_path / "old", (1, 1))
    assert jobs.sweep(3600) == 1 and (tmp_path / "new").exists() and not (tmp_path / "old").exists()
