"""Data-loss, portability and local API boundary checks for the new UI."""
import asyncio
import copy
import http.client
import io
import json
import threading
import time

import pandas as pd
import pytest

import paia_desktop as desktop
from annotation_workflow import demo_input, demo_results
from uniprot_fetcher import search_result


def wait_job(work):
    deadline = time.monotonic() + 10
    while work.state()["job"]["status"] in {"running", "cancelling"}:
        if time.monotonic() > deadline:
            pytest.fail("job did not finish")
        time.sleep(.01)
    return work.state()


def payload(work, frame=None, mode="offline"):
    return {"revision": work.revision, "input": desktop.table_payload(demo_input() if frame is None else frame),
            "id_column": "Protein ID", "settings": dict(desktop.DEFAULT_SETTINGS, mode=mode)}


@pytest.fixture
def completed():
    work = desktop.Workbench()
    work.start(payload(work))
    assert wait_job(work)["job"]["status"] == "done"
    return work


def test_offline_roundtrip_preserves_all_rows_and_evidence(completed):
    state = completed.state()
    assert state["stats"] == {"rows":8,"unique":6,"empty":1,"duplicates":1}
    assert sum(r["Mapping Status"] == "Matched" for r in completed.rows) == 5
    project = json.loads(desktop.json_bytes(completed.project()))
    assert "_entry" not in project["results"][0]
    assert project["results"][0]["_annotation_records"]
    new = desktop.Workbench()
    new.restore({"revision":0,"project":project})
    assert new.project()["results"] == project["results"]
    output = pd.read_csv(io.BytesIO(new.export_csv({"revision":new.revision})),keep_default_na=False,dtype=str)
    original = demo_input().astype(str)
    assert output[original.columns].equals(original)
    assert len(output) == 8
    assert output.loc[6,"Mapping Status"] == "Empty input"
    filtered = pd.read_csv(io.BytesIO(new.export_csv({"revision":new.revision,"indices":[0]})),dtype=str)
    assert filtered["Protein ID"].tolist() == ["P00533","P00533"]


@pytest.mark.parametrize("suffix",[".csv",".tsv",".xlsx"])
def test_import_preserves_ids_blank_rows_and_existing_columns(suffix):
    original = pd.DataFrame({"Protein ID":["00123","P00533","P00533","","NOT_A_PROTEIN"],
                             "Gene Name":["元の値","A","B","","0"],"Memo":["NA","日本語","001","",""]})
    stream=io.BytesIO()
    if suffix==".xlsx":
        original.to_excel(stream,index=False)
    else:
        stream.write(original.to_csv(index=False,sep="\t" if suffix==".tsv" else ",").encode("utf-8-sig"))
    frame = desktop.read_input(stream.getvalue(),"input"+suffix)
    assert frame.equals(original)
    work = desktop.Workbench()
    work.start(payload(work,frame))
    assert wait_job(work)["job"]["status"] == "done"
    output = pd.read_csv(io.BytesIO(work.export_csv({"revision":work.revision})),keep_default_na=False,dtype=str)
    assert output[original.columns].equals(original)
    assert "Gene Name_PAIA" in output


def test_csv_blank_lines_and_cp932_are_retained():
    frame = desktop.read_input("Protein ID,Memo\nP00533,日本語\n\n00123,NA\n".encode("cp932"),"input.csv")
    assert frame["Protein ID"].tolist() == ["P00533","","00123"]
    assert frame["Memo"].tolist() == ["日本語","","NA"]


@pytest.mark.parametrize("damage",["schema","id","results","table","settings","records","candidate"])
def test_damaged_project_rejected_without_touching_previous_work(completed,damage):
    before = completed.project()
    broken = copy.deepcopy(before)
    if damage == "schema": broken["schema"] = 999
    if damage == "id": broken["id_column"] = "missing"
    if damage == "results": broken["results"][0]["Query ID"] = "wrong"
    if damage == "table": broken["input"]["data"][0].append("unexpected")
    if damage == "settings": broken["settings"]["attrs"] = ["unknown"]
    if damage == "records": broken["results"][0]["_annotation_records"] = "wrong"
    if damage == "candidate": broken["results"][0]["_candidates"] = [42]
    with pytest.raises(desktop.UserError):
        completed.restore({"revision":completed.revision,"project":broken})
    assert completed.project() == before


def test_failed_live_request_keeps_previous_results_and_allows_retry(completed,monkeypatch):
    before = completed.project()
    async def fail(*args,**kwargs):
        raise OSError("simulated unavailable network")
    monkeypatch.setattr(desktop,"_fetch_batch_async",fail)
    completed.start(payload(completed,mode="live"))
    assert wait_job(completed)["job"]["status"] == "error"
    assert completed.project() == before
    completed.start(payload(completed))
    assert wait_job(completed)["job"]["status"] == "done"


def test_cancellation_and_concurrent_restore_preserve_original(completed,monkeypatch):
    before = completed.project()
    started = threading.Event()
    async def slow(*args,**kwargs):
        started.set()
        await asyncio.sleep(30)
    monkeypatch.setattr(desktop,"_fetch_batch_async",slow)
    completed.start(payload(completed,mode="live"))
    assert started.wait(2)
    assert completed.project() == before
    with pytest.raises(desktop.UserError):
        completed.restore({"revision":completed.revision,"project":before})
    completed.cancel.set()
    assert wait_job(completed)["job"]["status"] == "cancelled"
    assert completed.project() == before
    completed.start(payload(completed))
    assert wait_job(completed)["job"]["status"] == "done"


def test_stale_tabs_cannot_overwrite_or_export_changed_results(completed):
    with pytest.raises(desktop.UserError):
        completed.start(dict(payload(completed),revision=0))
    with pytest.raises(desktop.UserError):
        completed.export_csv({"revision":0})


def test_ambiguous_mapping_requires_explicit_candidate_and_keeps_query(snapshot,monkeypatch):
    work = desktop.Workbench()
    attrs = desktop.DEFAULT_SETTINGS["attrs"]
    ambiguous = search_result({"results":[snapshot["entries"]["P00533"],snapshot["entries"]["P04637"]]},"generic",attrs)
    work.frame = pd.DataFrame({"Protein ID":["generic"]})
    work.id_column="Protein ID"
    work.rows = [desktop.compact_row(ambiguous)]
    with pytest.raises(desktop.UserError):
        work.resolve({"revision":0,"index":0,"accession":"P00441"})
    work.resolve({"revision":0,"index":0,"accession":"P00533"})
    assert wait_job(work)["job"]["status"] == "done"
    assert work.rows[0]["Query ID"] == "generic"
    assert work.rows[0]["Accession"] == "P00533"
    assert work.rows[0]["Mapping Method"] == "User-confirmed candidate"


@pytest.fixture
def server():
    with desktop.LocalServer() as server:
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        yield server
        server.shutdown()
        thread.join(2)


def call(server,path,body=None,headers=None,method=None):
    connection=http.client.HTTPConnection("127.0.0.1",server.server_port,timeout=5)
    connection.request(method or ("POST" if body is not None else "GET"),path,body,headers or {})
    response=connection.getresponse()
    result=response.status,dict(response.headers),response.read()
    connection.close()
    return result


def test_local_http_assets_api_and_export(server):
    headers={"X-PAIA-Token":server.token}
    assert call(server,"/")[0] == 200
    assert call(server,"/app.js")[0] == 200
    assert call(server,"/api/config",headers=headers)[0] == 200
    status,_,body=call(server,"/api/state",headers=headers)
    assert status==200 and json.loads(body)["results"]["data"] == []
    status,_,_=call(server,"/api/run",desktop.json_bytes(payload(server.workbench)),headers)
    assert status==200
    assert wait_job(server.workbench)["job"]["status"]=="done"
    status,meta,body=call(server,"/api/export/csv",desktop.json_bytes({"revision":1}),headers)
    assert status==200 and body.startswith(b"\xef\xbb\xbf") and "attachment" in meta["Content-Disposition"]
    assert call(server,"/api/detail/-1",headers=headers)[0]==404


@pytest.mark.parametrize("headers",[{}, {"X-PAIA-Token":"wrong"},{"Host":"evil.example"},{"Origin":"https://evil.example"},{"Origin":"null"}])
def test_api_rejects_untrusted_requests(server,headers):
    request_headers={"X-PAIA-Token":server.token,**headers} if headers else {}
    if headers == {"Host":"evil.example"}: request_headers["Host"]="evil.example"
    assert call(server,"/api/state",headers=request_headers)[0]==403


def test_malformed_requests_are_recoverable(server):
    headers={"X-PAIA-Token":server.token}
    for body in (b"broken",b"[]",b'{"revision":NaN}',b'{}'):
        assert call(server,"/api/run",body,headers)[0]==400
    assert call(server,"/api/state",headers=headers)[0]==200
