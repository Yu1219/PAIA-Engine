import asyncio
import aiohttp
from uniprot_fetcher import _fetch_one, _fetch_batch_async, _build_query, search_result


class Response:
    def __init__(self, status=200, payload=None, headers=None):
        self.status = status
        self.payload = payload or {"results": []}
        self.headers = headers or {}
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        pass
    async def json(self):
        return self.payload


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return next(self.responses)


def test_no_match_never_counts_as_a_success():
    result = search_result({"results": []}, "MISSING", ["Protein Name"])
    assert result["Accession"] is None
    assert result["Mapping Status"] == "Not found"


def test_ambiguous_identifier_is_unresolved_including_truncated_candidates(snapshot):
    entries = list(snapshot["entries"].values())[:2]
    result = search_result({"results": entries}, "generic name", ["Protein Name"], total="80")
    assert result["Mapping Status"] == "Needs review"
    assert result["Accession"] is None
    assert result["Candidate Count"] == 80
    assert result["_candidates"] == entries


def test_species_restriction_is_not_removed_on_no_match(monkeypatch):
    monkeypatch.setattr("uniprot_fetcher.INTER_REQUEST_DELAY", 0)
    session = Session([Response()])
    result = asyncio.run(_fetch_one(session, asyncio.Semaphore(1), "TP53", ["Protein Name"], organism_id="10090"))
    assert result["Mapping Status"] == "Not found"
    assert len(session.calls) == 1
    assert "organism_id:10090" in session.calls[0][1]["params"]["query"]


def test_domains_failure_keeps_successful_uniprot_mapping(snapshot, monkeypatch):
    monkeypatch.setattr("uniprot_fetcher.INTER_REQUEST_DELAY", 0)
    session = Session([Response(payload={"results": [snapshot["entries"]["P00533"]]}, headers={"X-Total-Results": "1"}), Response(status=503)])
    result = asyncio.run(_fetch_one(session, asyncio.Semaphore(1), "P00533", ["Protein Domains", "Protein Families"]))
    assert result["Mapping Status"] == "Matched"
    assert result["Accession"] == "P00533"
    assert result["InterPro Status"].startswith("Fetch error")
    assert "Protein kinase" in result["Protein Domains"]


def test_retries_429_and_reports_persistent_failure(monkeypatch):
    monkeypatch.setattr("uniprot_fetcher.INTER_REQUEST_DELAY", 0)
    monkeypatch.setattr("uniprot_fetcher.BACKOFF_FACTOR", 0)
    session = Session([Response(status=429), Response(status=503), Response(status=503)])
    progress = []
    result = asyncio.run(_fetch_one(session, asyncio.Semaphore(1), "P00533", [], progress_callback=lambda: progress.append(1)))
    assert result["Mapping Status"] == "Fetch error"
    assert result["Accession"] is None
    assert progress == [1]
    assert len(session.calls) == 3


def test_batch_deduplicates_ids_before_network_calls(monkeypatch):
    seen = []
    async def fake_fetch(session, semaphore, pid, attrs, *args, **kwargs):
        seen.append(pid)
        return {"Query ID": pid}
    monkeypatch.setattr("uniprot_fetcher._fetch_one", fake_fetch)
    results = asyncio.run(_fetch_batch_async(["A", " A ", "", "B", "B"], []))
    assert seen == ["A", "B"]
    assert len(results) == 2


def test_species_and_identifier_query_types():
    assert "organism_id:9606" in _build_query("ENSG00000146648", "9606")
    assert "xref:refseq-NP_005219.2" in _build_query("NP_005219.2", "9606")
    assert _build_query("P00533", "10090") == "accession:P00533"
    assert 'protein_name:"Tumor protein p53"' in _build_query("Tumor protein p53", "9606", "Protein Name")


def test_isoform_id_requires_review_instead_of_canonical_reinterpretation():
    session = Session([])
    result = asyncio.run(_fetch_one(session, asyncio.Semaphore(1), "P00533-2", ["Protein Name"]))
    assert result["Mapping Status"] == "Needs isoform review"
    assert result["Accession"] is None
    assert not session.calls
