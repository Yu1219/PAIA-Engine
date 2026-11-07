# 配布担当者向け：GitHub掲載前の確認

確認日：2026年10月8日

## 今回用意したもの

- `README.md`：GitHub掲載用の日本語取扱説明書。
- `output/pdf/PAIA_Engine_Manual_JA.pdf`：印刷・ダウンロード用の説明書。
- `output/releases/PAIA_Engine_Windows.zip`：更新版の実行ファイル、内部ファイル、説明書、サンプルCSVをまとめた配布用ZIP。
- `output/releases/SHA256SUMS.txt`：配布ZIPのSHA-256。
- `docs/images/`：今回の更新版を撮影した操作画面。

## 既存ZIPと更新版の違い

ルートにあった `PAIA_Engine.zip` は旧版です。その中のapp.pyは現在の更新版と異なり、オフラインテストに必要なannotation_workflow.pyやtest_dataを含んでいません。今回の説明書の配布には、新しく作成した `PAIA_Engine_Windows.zip` を使用してください。既存ZIPは変更していません。

更新版は `dist-high-priority/PAIA_Engine/` を使用しています。内部のapp.pyとannotation_workflow.pyは、作成時のソースとSHA-256が一致しています。

## 今回完了した検証

- PDFはA4・12ページ。全ページを画像にして表示を確認し、日本語文字の欠落や表のはみ出しがないことを確認しました。
- オフライン例は入力8行、空欄を除く6種類のID、Matched 5種類、Not found 1種類。全件出力で元の8行と値を保持しました。
- 膜局在Cell membraneと分類ReceptorでP00533に絞られ、絞り込み出力は元の重複を含む2行でした。
- 配布ZIPの全エントリーのCRC検証が成功しました。PDFと更新版の内部ソースの内容も照合しました。
- 配布ZIPを新しいフォルダーに展開したexeのSHA-256が配布元exeと一致しました。
- 展開したexeを起動し、正常応答と、実際のブラウザーによるオフライン処理・詳細表示・ダウンロードボタンの表示を確認しました。確認用のアプリは終了しました。

新しいPCへの移動、GitHubからの実ダウンロード、組織ごとの接続制限下での動作は未確認です。

## 公開前に行うこと

1. PAIA Engineを配布するGitHubリポジトリのURLと、公開／非公開の方針を決める。
2. README、PDF、画像を配置する。READMEのPDF・画像への相対リンクを保つ。
3. リリースを作り、Assetsに `PAIA_Engine_Windows.zip`、PDF、`SHA256SUMS.txt` を添付する。
4. READMEとPDFに実際のリリースページへのリンクを追加する。版名はリリースの実際のタグと一致させる。
5. 公開後のZIPをダウンロードして、サイズとSHA-256を照合する。
6. 展開したexeを起動し、オフラインテスト、8行の全件CSV、膜局在＋受容体でEGFRに絞る操作を確認する。
7. 公開配布なら、ログインしていないブラウザーでもリリースとZIPへアクセスできるか確認する。非公開配布なら、初心者向け説明に必要な閲覧権限を明記する。

この作業ではGitHubリポジトリやリリースの作成・アップロードは行っていません。配布先のURLはまだ特定できていません。
