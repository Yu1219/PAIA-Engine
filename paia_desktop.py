"""PAIA Workbench: local-only UI, revisioned jobs and portable project files.

No hosting account, web framework, CDN or LLM is required to use this app.
The Streamlit entry point remains available as app.py / launcher.py.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import csv
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import logging
import math
from pathlib import Path
import secrets
import sys
import threading
import webbrowser
from urllib.parse import parse_qs, urlsplit
import zipfile

import pandas as pd

from annotation_details import BOOLEAN_ATTRIBUTES
from annotation_workflow import (PRESETS, demo_input, demo_results, input_stats,
                                 merge_annotations, normalize_id, public_frame)
from uniprot_fetcher import ATTRIBUTE_CATEGORIES, ID_TYPES, NUMERIC_ATTRIBUTES, _fetch_batch_async

VERSION = "2.0.1"
ROOT = Path(__file__).resolve().parent
MAX_BYTES = 24 * 1024 * 1024
MAX_PROJECT_BYTES = 128 * 1024 * 1024
MAX_ROWS = 10000
ALL_ATTRS = [attr for attrs in ATTRIBUTE_CATEGORIES.values() for attr in attrs]
DEFAULT_SETTINGS = {"mode": "offline", "organism_id": "9606", "id_type": "Auto-detect",
                    "attrs": list(PRESETS["Basic / 基本情報"])}


class UserError(ValueError):
    """A recoverable, user-facing validation error."""


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


def validate_json_tree(value, depth=0):
    if depth > 40:
        raise UserError("JSONの入れ子が深すぎます。")
    if isinstance(value, float) and not math.isfinite(value):
        raise UserError("JSONの数値が範囲外です。")
    if type(value) is int and abs(value) > 9007199254740991:
        raise UserError("大きな整数は精度を保つため文字列で指定してください。")
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise UserError("JSONの項目名が正しくありません。")
            validate_json_tree(child, depth+1)
    elif isinstance(value, list):
        for child in value:
            validate_json_tree(child, depth+1)
    elif value is not None and type(value) not in (str, int, float, bool):
        raise UserError("JSONに対応しない値が含まれています。")


def table_payload(frame):
    # Pandas normalizes numpy scalars and missing values to JSON primitives.
    return json.loads(frame.to_json(orient="split", index=False, force_ascii=False, date_format="iso"))


def validate_table(value):
    validate_json_tree(value)
    if not isinstance(value, dict) or set(value) != {"columns", "data"}:
        raise UserError("入力表の形式が正しくありません。")
    columns, data = value["columns"], value["data"]
    if (not isinstance(columns, list) or not columns or len(columns) > 250 or
            any(not isinstance(c, str) or not c.strip() or len(c) > 300 for c in columns) or
            len(set(columns)) != len(columns)):
        raise UserError("列名は空欄・重複なしの文字列にしてください（最大250列）。")
    if not isinstance(data, list) or not 1 <= len(data) <= MAX_ROWS:
        raise UserError(f"入力は1〜{MAX_ROWS:,}行にしてください。")
    for row in data:
        if not isinstance(row, list) or len(row) != len(columns):
            raise UserError("入力表の列数が一致しません。")
        if any(v is not None and type(v) not in (str, bool, int, float) for v in row):
            raise UserError("入力表には文字列または数値を指定してください。")
    return pd.DataFrame(data, columns=columns)


def validate_settings(value):
    if not isinstance(value, dict):
        raise UserError("検索設定が正しくありません。")
    settings = {k: value.get(k, v) for k, v in DEFAULT_SETTINGS.items()}
    if settings["mode"] not in {"offline", "live"} or settings["id_type"] not in ID_TYPES:
        raise UserError("データモードまたはID形式が正しくありません。")
    species = settings["organism_id"]
    if not isinstance(species, str) or (species and (not species.isascii() or not species.isdigit() or len(species) > 12)):
        raise UserError("生物種にはNCBI Taxonomy IDの数字を指定してください。")
    attrs = settings["attrs"]
    if not isinstance(attrs, list) or not attrs or any(not isinstance(a, str) or a not in ALL_ATTRS for a in attrs):
        raise UserError("取得項目を1つ以上選んでください。")
    settings["attrs"] = list(dict.fromkeys(attrs))
    return settings


def read_input(data, filename):
    suffix = Path(filename).suffix.lower()
    try:
        if suffix in {".xlsx", ".xls"}:
            if suffix == ".xlsx":
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    if sum(info.file_size for info in archive.infolist()) > 128 * 1024 * 1024:
                        raise UserError("展開後のExcelファイルが大きすぎます。")
            frame = pd.read_excel(io.BytesIO(data), dtype=str, keep_default_na=False)
        elif suffix in {".csv", ".tsv", ".txt"}:
            try:
                text = data.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = data.decode("cp932")
            separator = "\t" if suffix in {".tsv", ".txt"} else ","
            reader = csv.reader(io.StringIO(text), delimiter=separator, strict=True)
            headers = next(reader, [])
            if not headers or len(headers) > 250 or len(set(headers)) != len(headers) or any(not h.strip() for h in headers):
                raise UserError("先頭行には空欄・重複なしの列名を指定してください（最大250列）。")
            for number, cells in enumerate(reader, start=1):
                if number > MAX_ROWS:
                    raise UserError(f"入力は{MAX_ROWS:,}行以内にしてください。")
                if len(cells) > len(headers):
                    raise UserError(f"データ{number}行目の列数が見出しを超えています。区切り文字を確認してください。")
            frame = pd.read_csv(io.StringIO(text), sep=separator,
                                dtype=str, keep_default_na=False, skip_blank_lines=False)
        else:
            raise UserError("CSV、TSV、XLSX、XLSを選んでください。")
        frame.columns = frame.columns.map(str)
        frame = frame.fillna("")
        return validate_table(table_payload(frame))
    except UserError:
        raise
    except Exception as exc:
        raise UserError("ファイルを読み込めません。文字コード・区切り文字・ファイル形式を確認してください。") from exc


def validate_project(value):
    """Validate completely before replacing any in-memory work; never unpickle."""
    validate_json_tree(value)
    if not isinstance(value, dict) or value.get("format") != "paia-project" or type(value.get("schema")) is not int or value.get("schema") != 1:
        raise UserError("対応していないプロジェクト形式です。v2のJSONを選んでください。")
    frame = validate_table(value.get("input"))
    column = value.get("id_column")
    if not isinstance(column, str) or column not in frame:
        raise UserError("プロジェクトのID列が見つかりません。")
    settings = validate_settings(value.get("settings"))
    rows = value.get("results")
    expected = list(dict.fromkeys(normalize_id(v) for v in frame[column] if normalize_id(v)))
    if not isinstance(rows, list) or len(rows) != len(expected):
        raise UserError("プロジェクトの入力と結果の件数が一致しません。")
    if any(not isinstance(r, dict) or not isinstance(r.get("Query ID"), str) or
           not isinstance(r.get("Mapping Status"), str) for r in rows):
        raise UserError("プロジェクトの検索結果が正しくありません。")
    if [r["Query ID"] for r in rows] != expected:
        raise UserError("プロジェクトの入力IDと検索結果が一致しません。")
    for row in rows:
        # Public cells are scalar; the browser consumes name/location fields as text.
        if any(v is not None and type(v) not in (str, bool, int, float) for k, v in row.items() if not k.startswith("_")):
            raise UserError("注釈の値は文字列・数値・真偽値にしてください。")
        numeric = set(NUMERIC_ATTRIBUTES) | {"Taxonomy ID", "Entry Version", "Candidate Count"}
        boolean = set(BOOLEAN_ATTRIBUTES) | {"Reviewed"}
        for key, cell in row.items():
            if key.startswith("_") or cell is None:
                continue
            expected_type = (int, float) if key in numeric else (bool,) if key in boolean else (str,)
            if type(cell) not in expected_type:
                raise UserError(f"注釈「{key}」の値の形式が正しくありません。")
        records = row.get("_annotation_records", [])
        if (not isinstance(records, list) or any(not isinstance(r, dict) for r in records)
                or not isinstance(row.get("_candidates", []), list)):
            raise UserError("根拠または候補情報の形式が正しくありません。")
        if any(not isinstance(c, dict) or not isinstance(c.get("primaryAccession"), str) for c in row.get("_candidates", [])):
            raise UserError("対応候補の形式が正しくありません。")
        for candidate in row.get("_candidates", []):
            description = candidate.get("proteinDescription", {})
            organism = candidate.get("organism", {})
            if (not isinstance(description, dict) or not isinstance(organism, dict) or
                    not isinstance(description.get("recommendedName", {}), dict)):
                raise UserError("候補の説明の形式が正しくありません。")
    created_at = value.get("created_at")
    if created_at is not None:
        if not isinstance(created_at, str):
            raise UserError("プロジェクトの取得日時が正しくありません。")
        try:
            datetime.fromisoformat(created_at)
        except ValueError as exc:
            raise UserError("プロジェクトの取得日時が正しくありません。") from exc
    return frame, column, settings, [compact_row(r) for r in rows]


def compact_row(row):
    """Keep evidence records; avoid carrying entire UniProt entries between PCs."""
    result = {k: v for k, v in row.items() if k != "_entry"}
    if "_candidates" in result:
        result["_candidates"] = [{k: c[k] for k in ("primaryAccession", "proteinDescription", "organism", "genes") if k in c}
                                  for c in result["_candidates"]]
    return result


class Workbench:
    def __init__(self):
        self.lock = threading.RLock()
        self.revision = 0
        self.frame = None
        self.id_column = None
        self.settings = copy.deepcopy(DEFAULT_SETTINGS)
        self.rows = []
        self.created_at = None
        self.job = {"status": "idle", "completed": 0, "total": 0, "message": ""}
        self.cancel = threading.Event()

    def check_revision(self, payload):
        if payload.get("revision") != self.revision:
            raise UserError("別の画面で作業が更新されました。最新の結果を確認して再実行してください。")
        if self.job["status"] in {"running", "cancelling"}:
            raise UserError("処理中です。完了または中止を待ってください。")

    def state(self):
        with self.lock:
            return {"version": VERSION, "revision": self.revision, "job": dict(self.job),
                    "settings": copy.deepcopy(self.settings), "id_column": self.id_column,
                    "input": table_payload(self.frame) if self.frame is not None else None,
                    "stats": input_stats(self.frame[self.id_column]) if self.frame is not None else None,
                    "results": table_payload(public_frame(self.rows)), "created_at": self.created_at}

    def project(self):
        with self.lock:
            if self.frame is None:
                raise UserError("先にアノテーションを実行してください。")
            return {"format": "paia-project", "schema": 1, "app_version": VERSION,
                    "created_at": self.created_at, "input": table_payload(self.frame),
                    "id_column": self.id_column, "settings": copy.deepcopy(self.settings),
                    "results": copy.deepcopy(self.rows)}

    def export_project(self, payload):
        with self.lock:
            if payload.get("revision") != self.revision:
                raise UserError("結果が更新されました。最新の結果を確認して保存してください。")
            return self.project()

    def restore(self, payload):
        frame, column, settings, rows = validate_project(payload.get("project"))
        with self.lock:
            self.check_revision(payload)
            self.frame, self.id_column, self.settings, self.rows = frame, column, settings, rows
            self.created_at = payload["project"].get("created_at")
            self.revision += 1
            self.job = {"status": "idle", "completed": 0, "total": 0, "message": "プロジェクトを復元しました。"}

    def start(self, payload):
        frame = validate_table(payload.get("input"))
        column = payload.get("id_column")
        if not isinstance(column, str) or column not in frame:
            raise UserError("タンパク質IDの列を選んでください。")
        settings = validate_settings(payload.get("settings"))
        ids = list(dict.fromkeys(normalize_id(v) for v in frame[column] if normalize_id(v)))
        if not ids:
            raise UserError("IDが空欄です。タンパク質IDを入力してください。")
        with self.lock:
            self.check_revision(payload)
            self.cancel = threading.Event()
            self.job = {"status": "running", "completed": 0, "total": len(ids), "message": "取得しています…"}
            threading.Thread(target=self._run, args=(frame, column, settings, ids, None), daemon=True).start()

    def resolve(self, payload):
        with self.lock:
            self.check_revision(payload)
            index, accession = payload.get("index"), payload.get("accession")
            if type(index) is not int or not 0 <= index < len(self.rows):
                raise UserError("対象の行が見つかりません。")
            old = self.rows[index]
            if (payload.get("query_id") != old["Query ID"] or old.get("Mapping Status") != "Needs review"
                    or accession not in [c["primaryAccession"] for c in old.get("_candidates", [])]):
                raise UserError("表示された候補から選択してください。")
            settings = dict(self.settings, id_type="UniProt ID")
            self.cancel = threading.Event()
            self.job = {"status": "running", "completed": 0, "total": 1, "message": "選択した候補を確認しています…"}
            threading.Thread(target=self._run, args=(self.frame.copy(), self.id_column, settings, [accession], index), daemon=True).start()

    async def _live(self, ids, settings, progress):
        task = asyncio.create_task(_fetch_batch_async(ids, settings["attrs"], progress,
                                                      organism_id=settings["organism_id"] or None,
                                                      id_type=settings["id_type"]))
        try:
            while not task.done():
                if self.cancel.is_set():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    return None
                await asyncio.wait({task}, timeout=0.1)
            return await task
        finally:
            if not task.done():
                task.cancel()

    def _run(self, frame, column, settings, ids, resolve_index):
        def progress():
            with self.lock:
                self.job["completed"] += 1
        try:
            rows = (demo_results(ids, settings["attrs"], settings["organism_id"], settings["id_type"])
                    if settings["mode"] == "offline" else asyncio.run(self._live(ids, settings, progress)))
            with self.lock:
                if self.cancel.is_set() or rows is None:
                    self.job.update(status="cancelled", message="中止しました。前の結果を保持しています。")
                    return
                if resolve_index is not None:
                    chosen = rows[0]
                    if chosen.get("Mapping Status") != "Matched":
                        raise UserError("候補を取得できませんでした。未確定の結果を保持しています。")
                    old = self.rows[resolve_index]
                    chosen.update({"Query ID": old["Query ID"], "Candidate Count": old.get("Candidate Count"),
                                   "Mapping Method": "User-confirmed candidate"})
                    self.rows = [compact_row(chosen) if i == resolve_index else row for i, row in enumerate(self.rows)]
                else:
                    if all(r.get("Mapping Status") == "Fetch error" for r in rows):
                        raise UserError("データベースに接続できませんでした。ネット接続を確認して再試行してください。前の結果は保持しています。")
                    self.frame, self.id_column, self.settings, self.rows = frame, column, settings, [compact_row(r) for r in rows]
                self.created_at = datetime.now(timezone.utc).isoformat()
                self.revision += 1
                self.job.update(status="done", completed=len(ids), message="アノテーションが完了しました。")
        except Exception as exc:
            logging.exception("Annotation job failed")
            with self.lock:
                self.job.update(status="error", message=str(exc) if isinstance(exc, UserError) else "処理に失敗しました。入力・接続を確認して再試行してください。前の結果は保持しています。")

    def export_csv(self, payload):
        with self.lock:
            if self.frame is None:
                raise UserError("保存する結果がありません。")
            if payload.get("revision") != self.revision:
                raise UserError("結果が更新されました。最新の結果を確認して保存してください。")
            frame = self.frame
            indices = payload.get("indices")
            if indices is not None:
                if not isinstance(indices, list) or any(type(i) is not int or not 0 <= i < len(self.rows) for i in indices):
                    raise UserError("保存対象の指定が正しくありません。")
                wanted = {self.rows[i]["Query ID"] for i in indices}
                frame = frame[frame[self.id_column].map(normalize_id).isin(wanted)]
            return merge_annotations(frame, self.id_column, self.rows).to_csv(index=False).encode("utf-8-sig")


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, port=0):
        self.workbench = Workbench()
        self.token = secrets.token_urlsafe(32)
        super().__init__(("127.0.0.1", port), Handler)
        self.origin = f"http://127.0.0.1:{self.server_port}"


class Handler(BaseHTTPRequestHandler):
    server_version = "PAIA"
    def log_message(self, *_):
        pass

    def reply(self, status, body, content_type="application/json; charset=utf-8", filename=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)

    def allowed(self, api=False):
        if self.headers.get("Host") != urlsplit(self.server.origin).netloc:
            self.reply(403, json_bytes({"error": "このPCから起動した画面を使用してください。"}))
            return False
        origin = self.headers.get("Origin")
        if origin and origin != self.server.origin:
            self.reply(403, json_bytes({"error": "別サイトからの操作は許可されていません。"}))
            return False
        if api and not secrets.compare_digest(self.headers.get("X-PAIA-Token", ""), self.server.token):
            self.reply(403, json_bytes({"error": "画面を再読み込みしてください。"}))
            return False
        return True

    def do_GET(self):
        path = urlsplit(self.path).path
        if not self.allowed(path.startswith("/api/")):
            return
        if path == "/api/state":
            self.reply(200, json_bytes(self.server.workbench.state()))
        elif path == "/api/config":
            self.reply(200, json_bytes({"version": VERSION, "presets": PRESETS, "categories": ATTRIBUTE_CATEGORIES,
                                        "id_types": ID_TYPES, "boolean_attrs": sorted(BOOLEAN_ATTRIBUTES),
                                        "numeric_attrs": sorted(NUMERIC_ATTRIBUTES), "max_rows": MAX_ROWS}))
        elif path == "/api/demo":
            self.reply(200, json_bytes(table_payload(demo_input())))
        elif path.startswith("/api/detail/"):
            try:
                index = int(path.rsplit("/", 1)[1])
                with self.server.workbench.lock:
                    if not 0 <= index < len(self.server.workbench.rows):
                        raise IndexError
                    query = parse_qs(urlsplit(self.path).query)
                    if query.get("revision") != [str(self.server.workbench.revision)]:
                        self.reply(409, json_bytes({"error": "結果が更新されました。画面を再読み込みして詳細を開いてください。"}))
                        return
                    self.reply(200, json_bytes(self.server.workbench.rows[index]))
            except (ValueError, IndexError):
                self.reply(404, json_bytes({"error": "対象の結果が見つかりません。"}))
        elif path in {"/", "/app.js", "/app.css"}:
            name = "index.html" if path == "/" else path[1:]
            data = (ROOT / "desktop_ui" / name).read_bytes()
            if path == "/":
                data = data.replace(b"__PAIA_TOKEN__", self.server.token.encode("ascii"))
            mime = {"/": "text/html", "/app.js": "text/javascript", "/app.css": "text/css"}[path]
            self.reply(200, data, mime + "; charset=utf-8")
        else:
            self.reply(404, json_bytes({"error": "見つかりません。"}))

    def do_POST(self):
        if not self.allowed(True):
            return
        try:
            path = urlsplit(self.path).path
            length = int(self.headers.get("Content-Length", "0"))
            limit = MAX_PROJECT_BYTES if path == "/api/restore" else MAX_BYTES
            if not 0 < length <= limit:
                raise UserError(f"ファイルが空、または{limit // (1024 * 1024)}MBを超えています。")
            self.connection.settimeout(15)
            body = self.rfile.read(length)
            if len(body) != length:
                raise UserError("読み込みが中断されました。もう一度選んでください。")
            work = self.server.workbench
            if path == "/api/import":
                frame = read_input(body, self.headers.get("X-PAIA-Filename", "input.csv"))
                self.reply(200, json_bytes(table_payload(frame)))
                return
            payload = json.loads(body, parse_constant=lambda _: (_ for _ in ()).throw(UserError("数値の形式が正しくありません。")))
            validate_json_tree(payload)
            if not isinstance(payload, dict):
                raise UserError("リクエストの形式が正しくありません。")
            if path == "/api/run":
                work.start(payload)
            elif path == "/api/resolve":
                work.resolve(payload)
            elif path == "/api/cancel":
                with work.lock:
                    if work.job["status"] == "running":
                        work.cancel.set()
                        work.job.update(status="cancelling", message="中止しています…")
            elif path == "/api/restore":
                work.restore(payload)
            elif path == "/api/export/project":
                data = json_bytes(work.export_project(payload))
                if len(data) > MAX_PROJECT_BYTES - 1024:
                    raise UserError("プロジェクトが128MBを超えます。全行CSVを保存し、入力を分割して解析してください。")
                self.reply(200, data, filename="PAIA-project.json")
                return
            elif path == "/api/export/csv":
                self.reply(200, work.export_csv(payload), "text/csv; charset=utf-8", "PAIA-annotations.csv")
                return
            elif path == "/api/shutdown":
                with work.lock:
                    work.check_revision(payload)
                self.reply(200, json_bytes({"ok": True}))
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            else:
                self.reply(404, json_bytes({"error": "見つかりません。"}))
                return
            self.reply(200, json_bytes(work.state()))
        except (ValueError, TypeError, KeyError, RecursionError) as exc:
            self.reply(400, json_bytes({"error": str(exc) if isinstance(exc, UserError) else "ファイルまたは入力形式が正しくありません。"}))
        except (OSError, TimeoutError):
            self.reply(408, json_bytes({"error": "読み込みに時間がかかっています。再試行してください。"}))


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    parser = argparse.ArgumentParser(description="PAIA Workbench — 日本語ポータブル版")
    parser.add_argument("--port", type=int, default=0, help="0なら空きポートを自動選択")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("port must be between 0 and 65535")
    try:
        with LocalServer(args.port) as server:
            print(f"PAIA Workbench {VERSION}\n{server.origin}\n終了前にプロジェクトを保存してください。", flush=True)
            if not args.no_browser:
                webbrowser.open(server.origin)
            try:
                server.serve_forever(poll_interval=0.2)
            except KeyboardInterrupt:
                pass
            finally:
                server.workbench.cancel.set()
        return 0
    except OSError as exc:
        print(f"起動できませんでした。別のポートで再試行してください：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
