---
paths:
  - "packages/core/**"
---
# packages/core のルール
- 依存方向は内向きのみ: `core/` → `ports/` のみ import 可。`adapters/`・`cli.py`・外部ライブラリ（httpx, anthropic, duckdb, pyarrow, polars）を `core/` から import しない。
- 新しい外部依存は、まず `ports/` に Protocol を定義し、`socioscope_core/testing/fakes.py` に Fake を書き、core のテストを Fake で green にしてから adapter を実装する。
- adapter は境界で Pydantic 検証し、資格情報を属性・repr・例外・ログに載せない。
- `mypy --strict` を通す。`Any` を返す外部 API は adapter 内で型を閉じる。
- 品質ゲート: `make check`（ruff format --check / ruff check / mypy / pytest）。
