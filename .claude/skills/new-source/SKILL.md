---
name: new-source
description: >-
  新しい公開データソースを調査し、ライセンス確認・design/data-sources.md 更新・fetch/stage 実装までを行う定型手順。
  source-scout エージェントに委ねる。「〜のデータを取り込みたい」「/new-source <ソース名> <テーマ>」で起動。
---

# データソースの追加: `/new-source <ソース名> <theme-slug> [指標...]`

1. `source-scout` エージェントを起動し、調査（API・ライセンス・利用規約・robots.txt・定義・断絶）→ `design/data-sources.md` 更新 → 保存先・スキーマ設計 → fixture ベース TDD で fetch/stage 実装、を行わせる。
2. **ライセンス確認は人間ゲート**: scout の報告（ライセンス・再配布可否・取得コスト）を人に提示し、承認後に実装へ進む（既に明らかなオープンライセンス（CC BY 等）は報告のみでよい）。
3. 実装後 `/check`。可能なら `uv run socioscope run <theme> fetch` を 1 回だけ実行して manifest 追記を確認（レート制限に配慮）。
4. 報告: ソース・ライセンス・staged テーブル・既知の問題。commit は `/ship`。

禁止: 利用規約未確認の取得、キーのハードコード、raw の無断コミット。
