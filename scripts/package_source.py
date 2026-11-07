"""Export only the source distribution's explicitly selected files."""
from pathlib import Path
import hashlib
import json
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "output/source/PAIA-Engine"
TOP = ["app.py", "annotation_details.py", "annotation_workflow.py", "gui_helpers.py",
       "uniprot_fetcher.py", "visualizations.py", "launcher.py", "bootstrap.py",
       "style.css", "requirements.txt", "requirements-dev.txt", "requirements-windows-py314.lock",
       "PAIA_Engine_Source.bat", "00_Check_PC.bat", "01_Setup_Libraries.bat",
       "02_Build_Standalone.bat", "03_Run_With_Log.bat", "build_standalone.py",
       "paia_windows.spec", "requirements-build.txt", "requirements-build.lock",
       "PAIA_Manual_JA.html", "README.md", ".gitignore", "pytest.ini"]
DIRS = ["test_data", "tests"]
DOCS = ["docs/USER_GUIDE_JA.md", "docs/SOURCE_SETUP_JA.md", "docs/SOURCE_VALIDATION_JA.md",
        "docs/images/input.png", "docs/images/results.png",
        "docs/manual/PAIA_Engine_Detailed_Manual_JA.pdf",
        "docs/manual/PAIA_Engine_Detailed_Manual_JA.html", "docs/manual/manual_content.json"]


def export_source():
    DEST.mkdir(parents=True, exist_ok=True)
    selected = [ROOT / p for p in TOP + DOCS]
    selected += [p for p in (ROOT / 'docs/manual/images').iterdir()
                 if p.is_file() and p.suffix in {'.png','.jpg'}
                 and p.name not in {'results.jpg','manual-preview.jpg'}]
    for directory in DIRS:
        selected += [p for p in (ROOT / directory).rglob("*")
                     if p.is_file() and "__pycache__" not in p.parts and p.suffix not in {".pyc", ".pyo"}]
    records = []
    for source in selected:
        if not source.is_file():
            raise FileNotFoundError(source)
        relative = source.relative_to(ROOT)
        destination = DEST / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        records.append({"path": relative.as_posix(), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()})
    output = ROOT / "output/releases/PAIA_Engine_Source_Python314.zip"
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for record in records:
            archive.write(DEST / record["path"], "PAIA-Engine/" + record["path"])
    (output.parent / "SOURCE_SHA256SUMS.txt").write_text(
        hashlib.sha256(output.read_bytes()).hexdigest() + "  " + output.name + "\n", encoding="utf-8")
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
    (output.parent / "source_manifest.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(json.dumps({"source_directory": str(DEST), "zip": str(output), "files": len(records), "bytes": output.stat().st_size}))


if __name__ == "__main__":
    export_source()
