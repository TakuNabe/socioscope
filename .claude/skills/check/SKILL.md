---
name: check
description: >-
  品質ゲート（ruff format --check / ruff check / mypy / pytest）を一括実行する。実装完了時・commit/PR 前に使う。
  「チェックして」「品質ゲート」「テスト通して」で起動。
---

# 品質ゲート
リポジトリルートで以下を順に実行（`make check` と同一）。失敗があれば出力とともに報告し、すべて green になるまで完了としない。**勝手に commit しない。**

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy packages/core/src themes/*/src
uv run pytest
```
- `uv` 未同期なら `uv sync --all-packages` を先に。
- format 差分は `uv run ruff format .` で直してよい（適用前に一言添える）。
- 失敗は「どのコマンド・どのファイル・なぜ」を要約。全 green なら簡潔に合格を報告。
