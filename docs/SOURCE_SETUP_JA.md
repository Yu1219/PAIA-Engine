# Python 3.14ソース版：セットアップの説明

この配布版はPythonのソースコードです。Python 3.14（64ビット版）を使って実行します。

## 自動で行うこと

1. `PAIA_Engine_Source.bat` がPython 3.14を探します。`py -3.14`、`python`、`python3.14`、一般的なユーザー別インストール先の順に確認します。
2. `bootstrap.py` がアプリのフォルダー内に `.venv` という専用環境を作ります。
3. その環境にpipと必要なライブラリをインストールします。システム全体のライブラリは変更しません。
4. ライブラリを読み込めることと、依存関係の整合性を確認してからアプリを起動します。
5. 次回は準備済みの環境を使います。ライブラリ一覧が変わったときや、ライブラリが不足しているときは再度準備します。

Windows x64では、同梱の `requirements-windows-py314.lock` に記録した検証済みのバージョンを使います。それ以外の環境では `requirements.txt` を使いますが、今回の動作検証対象はWindows x64・Python 3.14の通常版です。

自動インストールはビルド済みのPythonパッケージを利用します。必要なパッケージがその環境向けに公開されていない場合はエラーで停止し、途中の環境を準備完了として記録しません。

## よくある状況

| 状況 | 対処 |
|---|---|
| Python 3.14が見つからない | 64ビット版Python 3.14を確認します。特殊な場所にある場合は、そのpython.exeでbootstrap.pyを開きます |
| ライブラリのダウンロードが失敗する | ネット接続を確認し、起動ファイルをもう一度開きます。初回セットアップにはインターネット接続が必要です |
| 組織のネットワークでインストールできない | プロキシ、証明書、パッケージ配布元へのアクセスについて管理者に確認します |
| フォルダーへの書き込みができない | ZIPを自分のドキュメントなど、書き込み可能な場所にすべて展開します |
| フォルダー移動後に起動できない／別Python版の.venvがある | アプリを終了して.venvを別名に変更し、再実行します。元データやCSVは残してください |
| 8501番ポートが使用中 | 自分で開いた旧アプリを終了します。別番号で使う場合は `PAIA_Engine_Source.bat --port 8502` を実行します |

`.venv` はソースや測定データを置く場所ではありません。アプリを移動したりGitHubから改めてダウンロードしたりするときは、新しいフォルダーで専用環境を作り直します。

## 手動で使う場合

Python 3.14を指定して、次のように実行できます。専用環境の有効化やPowerShellの実行ポリシー変更は不要です。

```powershell
py -3.14 bootstrap.py
```

準備だけを行う場合：

```powershell
py -3.14 bootstrap.py --setup-only
```

開発用テスト：

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest
```

## 必要な主なライブラリ

| ライブラリ | 用途 |
|---|---|
| Streamlit | ブラウザーで操作する画面 |
| pandas・NumPy | 表形式データの処理 |
| Plotly | グラフ表示 |
| aiohttp | UniProt・InterProへの問い合わせ |
| openpyxl | .xlsxファイルの読み込み |
| xlrd | 古い.xlsファイルの読み込み |

これらが利用する追加ライブラリもpipが自動でインストールします。CSV・Excelファイルの読み込みにMicrosoft Excel自体は必要ありません。

## 公式情報

- [Python：venv](https://docs.python.org/3.14/library/venv.html)
- [Streamlit：対応するPythonの確認](https://docs.streamlit.io/knowledge-base/using-streamlit/sanity-checks)
- [Streamlit：Python 3.14対応のリリースノート](https://docs.streamlit.io/develop/quick-reference/release-notes/2025)
- [pandas：2.3.3のPython 3.14対応](https://pandas.pydata.org/docs/whatsnew/v2.3.3.html)
