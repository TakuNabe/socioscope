---
paths:
  - "themes/**"
---
# themes/<slug> のルール
- テーマは `socioscope_core` のみに依存し、他テーマを import しない（ADR 0001）。
- `pipeline.py` の stage 関数（fetch/stage/mart）は Port 経由で I/O し、純粋な変換は別関数に切って単体テストする。変換は決定的（乱数・現在時刻に依存しない）。
- 出力 Parquet の列名は snake_case、共通キーは `iso3`（ISO 3166-1 alpha-3）と `year`（int）。ソースを示す `source` 列を持たせる。
- `queries/*.sql` は DuckDB 方言。パラメータは `?` バインドで渡し、f-string で SQL を組まない。
- `notebooks/` は marimo（`.py`）で探索専用。レポートの数値は `analysis/` のスクリプトか SQL から生成する。
- `reports/` は `docs/methodology/report-template.md` に従い、末尾にチェックリスト回答を置く。
