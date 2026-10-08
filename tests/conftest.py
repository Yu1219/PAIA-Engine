import json
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture
def snapshot():
    return json.loads((ROOT / "test_data/uniprot_entries.json").read_text(encoding="utf-8"))


@pytest.fixture
def interpro():
    return json.loads((ROOT / "test_data/interpro_entries.json").read_text(encoding="utf-8"))
