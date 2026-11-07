"""Exercise the actual relocated executable without a development Python on PATH.

This is an HTTP integration check, not a substitute for browser or other-PC tests.
"""
import csv
import hashlib
import io
import json
import os
import platform
from pathlib import Path
import queue
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


class Instance:
    def __init__(self, executable, cwd):
        env = os.environ.copy()
        for key in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV"):
            env.pop(key, None)
        env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32") if os.name=="nt" else ""
        self.process = subprocess.Popen([str(executable), "--no-browser", "--port", "0"],
                                        cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, encoding="utf-8", errors="replace")
        lines = queue.Queue()
        self.log = []
        def read():
            for line in self.process.stdout:
                self.log.append(line)
                lines.put(line)
        threading.Thread(target=read,daemon=True).start()
        deadline = time.monotonic()+30
        self.origin = None
        while time.monotonic() < deadline and self.process.poll() is None:
            try:
                line=lines.get(timeout=.2)
            except queue.Empty:
                continue
            match=re.search(r"http://127\.0\.0\.1:\d+",line)
            if match:
                self.origin=match[0]
                break
        if not self.origin:
            self.process.terminate()
            raise RuntimeError("Executable failed to start: "+"".join(self.log))
        body=urllib.request.urlopen(self.origin,timeout=10).read().decode("utf-8")
        self.token=re.search(r'name="paia-token" content="([^"]+)"',body)[1]

    def request(self,path,value=None,raw=None,headers=None):
        req_headers={"X-PAIA-Token":self.token,**(headers or {})}
        if raw is not None:
            data=raw
        elif value is not None:
            data=json.dumps(value,ensure_ascii=False).encode("utf-8")
            req_headers["Content-Type"]="application/json"
        else:
            data=None
        request=urllib.request.Request(self.origin+path,data=data,headers=req_headers)
        with urllib.request.urlopen(request,timeout=20) as response:
            return response.read()

    def json(self,path,value=None):
        return json.loads(self.request(path,value))

    def wait(self):
        deadline=time.monotonic()+120
        while time.monotonic()<deadline:
            state=self.json("/api/state")
            if state["job"]["status"] not in {"running","cancelling"}:
                return state
            time.sleep(.1)
        raise RuntimeError("Job timeout")

    def stop(self):
        if self.process.poll() is None:
            revision=self.json("/api/state")["revision"]
            self.json("/api/shutdown",{"revision":revision})
            self.process.wait(timeout=15)
        assert self.process.returncode==0, "Executable did not exit cleanly"


def main():
    build=json.loads((ROOT/"output/workbench/latest.json").read_text(encoding="utf-8"))
    package=Path(build["zip"])
    assert hashlib.sha256(package.read_bytes()).hexdigest()==build["sha256"]
    location=ROOT/"tmp/配布版 移動テスト"/(package.parent.name+"-"+str(time.time_ns()))
    location.mkdir(parents=True,exist_ok=False)
    with zipfile.ZipFile(package) as archive:
        archive.extractall(location)
        if os.name!="nt":
            for info in archive.infolist():
                mode=(info.external_attr>>16)&0o777
                if mode and not info.is_dir():
                    (location/info.filename).chmod(mode)
    for record in json.loads((location/"file_manifest.json").read_text(encoding="utf-8")):
        assert hashlib.sha256((location/record["path"]).read_bytes()).hexdigest()==record["sha256"]
    exe=location/"PAIA_Workbench"/("PAIA_Workbench.exe" if os.name=="nt" else "PAIA_Workbench")
    first=Instance(exe,location)
    second=None
    try:
        config=first.json("/api/config")
        demo=first.json("/api/demo")
        attrs=[a for group in config["categories"].values() for a in group]
        assert len(attrs)==44
        first.json("/api/run",{"revision":0,"input":demo,"id_column":"Protein ID",
                               "settings":{"mode":"offline","organism_id":"9606","id_type":"Auto-detect","attrs":attrs}})
        state=first.wait()
        assert state["job"]["status"]=="done",state["job"]
        assert state["stats"]=={"rows":8,"empty":1,"unique":6,"duplicates":1}
        table=[dict(zip(state["results"]["columns"],row)) for row in state["results"]["data"]]
        assert sum(r["Mapping Status"]=="Matched" for r in table)==5
        csv_body=first.request("/api/export/csv",{"revision":state["revision"]})
        exported=list(csv.DictReader(io.StringIO(csv_body.decode("utf-8-sig"))))
        assert len(exported)==8 and exported[5]["Protein ID"]=="P00533" and exported[6]["Mapping Status"]=="Empty input"
        evidence=first.json("/api/detail/0?revision="+str(state["revision"]))
        assert len(evidence["_annotation_records"])>0
        project=first.json("/api/export/project",{"revision":state["revision"]})
        (package.parent/"sample-roundtrip.json").write_text(json.dumps(project,ensure_ascii=False),encoding="utf-8")
        (package.parent/"sample-all-rows.csv").write_bytes(csv_body)
        # A second executable instance has an independently assigned free port.
        second=Instance(exe,location)
        assert second.origin!=first.origin
        restored=second.json("/api/restore",{"revision":0,"project":project})
        assert restored["results"]==state["results"]
        assert second.request("/api/export/csv",{"revision":restored["revision"]})==csv_body
        damaged=dict(project,schema=999)
        try:
            second.json("/api/restore",{"revision":restored["revision"],"project":damaged})
            raise AssertionError("Damaged project accepted")
        except urllib.error.HTTPError as error:
            assert error.code==400
        assert second.json("/api/export/project",{"revision":restored["revision"]})==project
        # Parse workbook engines inside the frozen executable, not the developer's interpreter.
        for suffix in ("csv","tsv","xlsx"):
            path=ROOT/"tmp"/("portable-input."+suffix)
            if suffix=="xlsx":
                import pandas as pd
                pd.DataFrame({"Protein ID":["00123","P00533","P00533",""],"Memo":["NA","日本語","重複",""]}).to_excel(path,index=False)
                expected_count=3  # Excel omits a completely empty trailing row.
            else:
                sep="\t" if suffix=="tsv" else ","
                path.write_bytes((f"Protein ID{sep}Memo\n00123{sep}NA\nP00533{sep}日本語\nP00533{sep}重複\n{sep}空欄\n").encode("utf-8-sig"))
                expected_count=4
            data=json.loads(second.request("/api/import",raw=path.read_bytes(),headers={"X-PAIA-Filename":"input."+suffix}))
            assert data["data"][0][0]=="00123" and len(data["data"])==expected_count
        second.stop()
        second=None
        first.stop()
        # Restart confirms clean shutdown and project recovery without installed Python.
        first=Instance(exe,location)
        assert first.json("/api/state")["results"]["data"]==[]
        restored=first.json("/api/restore",{"revision":0,"project":project})
        assert restored["stats"]["rows"]==8
        report={"status":"PASS","commit":build["commit"],"package_sha256":build["sha256"],
                "relocated_directory":str(location),"python_available_on_path":False,"attributes":44,
                "input_rows":8,"unique_ids":6,"matched_ids":5,"evidence_records_first_id":len(evidence["_annotation_records"]),
                "csv_rows":len(exported),"project_roundtrip":"PASS","corrupt_project_preserves_results":"PASS",
                "parallel_ephemeral_ports":"PASS","frozen_csv_tsv_xlsx_import":"PASS","restart_and_restore":"PASS",
                "runtime_platform":platform.platform(),"other_pc":"NOT_RUN",
                "other_platforms":"Do not infer; require separate jobs","browser_file_picker":"NOT_RUN"}
        (package.parent/"runtime_validation.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps(report))
    finally:
        if second: second.stop()
        first.stop()


if __name__=="__main__":
    main()
