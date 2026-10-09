"""Prepare an isolated Python 3.14 environment, then launch PAIA Engine."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import struct
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parent
ENV_DIR = ROOT / ".venv"
STATE_FILE = ENV_DIR / ".paia-setup.json"
MODULES = ("streamlit", "pandas", "numpy", "plotly", "aiohttp", "openpyxl", "xlrd")


def message(text: str) -> None:
    print(text, flush=True)


def environment_python() -> Path:
    return ENV_DIR / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def requirements_path() -> Path:
    locked = ROOT / "requirements-windows-py314.lock"
    if os.name == "nt" and platform.machine().lower() in {"amd64", "x86_64"} and locked.is_file():
        return locked
    return ROOT / "requirements.txt"


def setup_signature(requirements: Path) -> str:
    payload = {
        "python": list(sys.version_info[:3]),
        "base_python": str(Path(getattr(sys, "_base_executable", sys.executable)).resolve()),
        "platform": sys.platform,
        "architecture": platform.machine(),
        "requirements": requirements.name,
        "content": requirements.read_text(encoding="utf-8-sig"),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def invoke(command: list[str], *, capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(command, cwd=ROOT, check=True, capture_output=capture,
                          text=True, encoding="utf-8", errors="replace")


def environment_is_314(python: Path) -> bool:
    try:
        probe = invoke([str(python), "-c", "import sys; print('%d.%d' % sys.version_info[:2])"], capture=True)
        return probe.stdout.strip() == "3.14"
    except (OSError, subprocess.CalledProcessError):
        return False


def runtime_is_ready(python: Path, requirements: Path) -> bool:
    # Import the actual runtime modules and compare every pinned package in the Windows lock.
    probe = (
        "import importlib, importlib.metadata, json, sys; "
        "assert sys.version_info[:2] == (3, 14); "
        "[importlib.import_module(n) for n in json.loads(sys.argv[1])]; "
        "expected=json.loads(sys.argv[2]); "
        "assert all(importlib.metadata.version(n)==v for n,v in expected.items())"
    )
    expected = {}
    for line in requirements.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "==" in line and ";" not in line:
            name, version = line.split("==", 1)
            expected[name.strip()] = version.strip()
    try:
        invoke([str(python), "-c", probe, json.dumps(MODULES), json.dumps(expected)], capture=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def prepare_environment() -> Path:
    if sys.version_info[:2] != (3, 14):
        raise RuntimeError(f"Python 3.14で起動してください。現在はPython {sys.version.split()[0]}です。")
    if struct.calcsize("P") != 8:
        raise RuntimeError("64ビット版のPython 3.14を使用してください。")
    required = requirements_path()
    if not required.is_file():
        raise RuntimeError("必要なライブラリ一覧がありません。GitHubのZIPをすべて展開してください。")
    python = environment_python()
    if ENV_DIR.exists():
        if not python.is_file() or not environment_is_314(python):
            raise RuntimeError(".venvが別のPython版、または移動前の場所の環境です。アプリを終了し、.venvフォルダーを別名に変更してから再実行してください。元データはそのまま残してください。")
    else:
        message("初回の準備：このアプリ専用のPython環境を作成しています。")
        venv.EnvBuilder(with_pip=True).create(ENV_DIR)
    signature = setup_signature(required)
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    if state.get("signature") == signature and runtime_is_ready(python, required):
        message("準備済みのライブラリを使用します。")
        return python
    message("必要なライブラリを自動インストールしています。初回はインターネット接続が必要です。")
    message("ライブラリはこのフォルダー内の.venvだけに保存します。")
    invoke([str(python), "-m", "ensurepip", "--upgrade"])
    invoke([str(python), "-m", "pip", "install", "--require-virtualenv",
            "--disable-pip-version-check", "--upgrade", "pip"])
    invoke([str(python), "-m", "pip", "install", "--require-virtualenv",
            "--disable-pip-version-check", "--only-binary=:all:", "-r", str(required)])
    invoke([str(python), "-m", "pip", "check"])
    if not runtime_is_ready(python, required):
        raise RuntimeError("インストール後のライブラリ確認に失敗しました。上のエラーを確認してください。")
    pending = STATE_FILE.with_suffix(".tmp")
    pending.write_text(json.dumps({"signature": signature, "python": sys.version.split()[0],
                                   "requirements": required.name}, ensure_ascii=False, indent=2), encoding="utf-8")
    pending.replace(STATE_FILE)
    message("準備が完了しました。")
    return python


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    parser = argparse.ArgumentParser(description="PAIA Engineの自動セットアップと起動")
    parser.add_argument("--setup-only", action="store_true", help="ライブラリの準備だけを行う")
    parser.add_argument("--build", action="store_true", help="このPC向けのスタンドアローン版を作成する")
    parser.add_argument("--port", type=int, default=8501, help="操作画面のポート番号")
    parser.add_argument("--no-browser", action="store_true", help="ブラウザーを自動で開かない")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    if args.setup_only and args.build:
        parser.error("--setup-only and --build cannot be combined")
    try:
        python = prepare_environment()
        if args.setup_only:
            return 0
        if args.build:
            return subprocess.call([str(python), str(ROOT / "build_standalone.py")], cwd=ROOT)
        command = [str(python), str(ROOT / "launcher.py"), "--port", str(args.port)]
        if args.no_browser:
            command.append("--no-browser")
        return subprocess.call(command, cwd=ROOT)
    except KeyboardInterrupt:
        return 0
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        message(f"\n準備または起動に失敗しました：{error}")
        message("インターネット接続、Python 3.14、フォルダーの書き込み権限を確認し、もう一度実行してください。")
        message("組織のプロキシや証明書の制限がある場合は、管理者に相談してください。")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
