"""Install isolated build tools and produce an inspectable standalone folder."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent
LOG = ROOT / "logs/build.log"

def say(value):
    print(value, flush=True)
    with LOG.open("a", encoding="utf-8") as stream:
        stream.write(str(value) + "\n")

def run(command):
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    with subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace") as process:
        for line in process.stdout:
            print(line, end="", flush=True)
            with LOG.open("a", encoding="utf-8") as stream:
                stream.write(line)
        if process.wait():
            raise subprocess.CalledProcessError(process.returncode, command)

def main():
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text("PAIA Engine standalone build\n", encoding="utf-8")
    try:
        if sys.version_info[:2] != (3, 14) or sys.prefix == sys.base_prefix:
            raise RuntimeError("02_Build_Standalone.batを使って、専用のPython 3.14環境で作成してください。")
        if os.name != "nt" or platform.machine().lower() not in {"amd64", "x86_64"}:
            raise RuntimeError("このビルド手順の対象はWindows x64です。PCのOSとCPUを確認してください。")
        required = ROOT / "requirements-build.lock"
        if not required.is_file():
            required = ROOT / "requirements-build.txt"
        say("ビルド用ライブラリを専用環境に準備しています。初回はネット接続が必要です。")
        run([sys.executable, "-m", "pip", "install", "--require-virtualenv", "--disable-pip-version-check",
             "--only-binary=:all:", "-r", str(required)])
        run([sys.executable, "-m", "pip", "check"])
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output = ROOT / "output/standalone" / stamp
        output.mkdir(parents=True, exist_ok=False)
        run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
             "--distpath", str(output), "--workpath", str(output / "build"), str(ROOT / "paia_windows.spec")])
        app = output / "PAIA_Engine"
        if not (app / "PAIA_Engine.exe").is_file():
            raise RuntimeError("ビルド後のexeが見つかりません。logs/build.logを確認してください。")
        (app / "起動方法.txt").write_text(
            "PAIA_Engine.exeをダブルクリックしてください。Pythonの別途インストールは不要です。\n"
            "このフォルダー全体を保管してください。_internalも必要です。\n"
            "画面が開かない場合は、起動した黒いウィンドウを残し、http://localhost:8501を開いてください。\n"
            "結果を保存してから、ブラウザーのタブと起動用ウィンドウを閉じて終了します。\n"
            "Test dataset (offline)は通信不要です。公開データの新規検索にはネット接続が必要です。\n"
            "作成したPCでの起動・操作確認を行ってから配布してください。\n", encoding="utf-8-sig")
        frozen = subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True, encoding="utf-8")
        (output / "build_environment.txt").write_text(frozen, encoding="utf-8")
        package = output / "PAIA_Engine_Standalone.zip"
        with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in app.rglob("*"):
                if path.is_file():
                    archive.write(path, path.relative_to(output))
        with zipfile.ZipFile(package) as archive:
            if archive.testzip() is not None:
                raise RuntimeError("作成したZIPの整合性確認に失敗しました。")
        digest = hashlib.sha256(package.read_bytes()).hexdigest()
        (output / "SHA256SUMS.txt").write_text(digest + "  " + package.name + "\n", encoding="utf-8")
        report = {"python": sys.version, "platform": platform.platform(), "architecture": platform.machine(),
                  "app_directory": str(app), "zip": str(package), "sha256": digest,
                  "build_succeeded": True, "runtime_tested": False}
        (output / "build_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (ROOT / "output/standalone/latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        say("\nビルドが完了しました。次に、作成したexeの起動と操作を確認してください。")
        say("exe：" + str(app / "PAIA_Engine.exe"))
        say("ZIP：" + str(package))
        say("ビルド成功は、別PCでの動作確認完了を意味しません。")
        if not os.environ.get("PAIA_NONINTERACTIVE"):
            os.startfile(output)
        return 0
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        say("\nビルドに失敗しました：" + str(error))
        say("logs/build.logを確認してください。途中の出力を配布しないでください。")
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
