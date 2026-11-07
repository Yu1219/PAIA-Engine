"""Build a versioned, relocatable distribution on Windows, macOS or Linux."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import zipfile

from paia_desktop import VERSION

ROOT = Path(__file__).resolve().parent


def build():
    system = {"Windows":"windows", "Darwin":"macos", "Linux":"linux"}.get(platform.system())
    machine = platform.machine().lower()
    arch = "x64" if machine in {"amd64","x86_64"} else machine
    if not system:
        raise RuntimeError("Unsupported build OS")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    output = ROOT / "output/workbench" / f"v{VERSION}-{system}-{arch}-{stamp}"
    output.mkdir(parents=True, exist_ok=False)
    log = output / "build.log"
    with log.open("w",encoding="utf-8") as stream:
        subprocess.run([sys.executable,"-m","PyInstaller","--noconfirm","--clean",
                        "--distpath",str(output),"--workpath",str(output/"build"),
                        str(ROOT/"paia_workbench.spec")],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True)
    app = output / "PAIA_Workbench"
    executable = app / ("PAIA_Workbench.exe" if system=="windows" else "PAIA_Workbench")
    if not executable.is_file():
        raise RuntimeError("Build completed without the expected executable")
    shutil.copyfile(ROOT/"docs/WORKBENCH_GUIDE_JA.md",app/"使い方.md")
    (app/"はじめに.txt").write_text(
        f"PAIA Workbench {VERSION} — {system} {arch}\n\n"
        "ZIPをすべて展開し、PAIA_Workbenchを起動してください。Pythonの別途インストールは不要です。\n"
        "_internalを含むフォルダー全体を保管してください。管理者権限は不要です。\n"
        "ブラウザーで日本語の操作画面が開きます。画面が開かないときは起動用ウィンドウのURLを開きます。\n"
        "サンプルと保存済み結果の閲覧は通信不要。新しい公開DB検索にはネット接続が必要です。\n"
        "作業は終了時に自動保存されません。終了前にプロジェクトJSONを保存してください。\n"
        "この配布版は記載のOS/CPU用です。macOS・Linux・Windows ARMには個別のビルドが必要です。\n"
        "別PCでの動作確認は、添付の検証記録の確認範囲を参照してください。\n",encoding="utf-8-sig")
    files=[]
    for path in sorted(app.rglob("*")):
        if path.is_file():
            files.append({"path":path.relative_to(output).as_posix(),"bytes":path.stat().st_size,
                          "sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
    manifest=output/"file_manifest.json"
    manifest.write_text(json.dumps(files,ensure_ascii=False,indent=2),encoding="utf-8")
    package=output/f"PAIA-Workbench-{VERSION}-{system}-{arch}.zip"
    with zipfile.ZipFile(package,"w",compression=zipfile.ZIP_DEFLATED) as archive:
        for record in files:
            archive.write(output/record["path"],record["path"])
        archive.write(manifest, "file_manifest.json")
    with zipfile.ZipFile(package) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("Archive verification failed")
    commit=subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()
    dirty=bool(subprocess.check_output(["git","status","--porcelain"],cwd=ROOT,text=True).strip())
    digest=hashlib.sha256(package.read_bytes()).hexdigest()
    report={"version":VERSION,"commit":commit,"working_tree_dirty":dirty,"platform":platform.platform(),
            "python":sys.version,"zip":str(package),"executable":str(executable),"sha256":digest,
            "files":len(files),"built_at":datetime.now(timezone.utc).isoformat(),"runtime_tested":False}
    (output/"build_report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    (output/"SHA256SUMS.txt").write_text(digest+"  "+package.name+"\n",encoding="utf-8")
    (ROOT/"output/workbench/latest.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=="__main__":
    build()
