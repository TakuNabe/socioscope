---
name: analyze
description: >-
  テーマの分析を実行し report（Markdown＋図＋再現スクリプト）を作成、methodology-reviewer の承認まで回す定型手順。
  「分析して」「レポートを書いて」「/analyze <theme-slug> [仮説 or 問い]」で起動。
---

# 分析を実行して report を出す: `/analyze <theme-slug> [H1 / 問い]`

1. **前提確認**: `design/themes/<slug>.md` に事前登録の仮説・指標があること。無ければ先に design を書いて人に確認（事後登録を避ける）。
2. **データ準備**: `uv run socioscope run <slug> stage && uv run socioscope run <slug> mart && uv run socioscope db build`。mart の行数・期間・欠損を把握。
3. **分析**: `analyst` エージェントを起動。対象仮説・推定したい量を渡し、`analysis/<yyyymmdd>_<slug>.py`（決定的）、`reports/figures/`、`reports/<yyyy-mm-dd>-<slug>.md`（テンプレート準拠、チェックリスト回答付き）を作らせる。
4. **方法論レビュー**: `methodology-reviewer` を起動。`CHANGES_REQUESTED` なら BLOCKING を analyst に戻す（上限 3 反復、`/review-loop` と同じ規律）。
5. **ゲート**: `/check`（スクリプトの lint/type/テスト）。
6. **提示**: report 要約（言えること／言えないこと）と図を人に提示。commit は `/ship`。**report の公開（merge）は人が判断**。
