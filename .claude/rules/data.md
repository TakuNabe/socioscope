---
paths:
  - "data/**"
---
# data/ のルール（ADR 0002, 0003）
- `data/raw/**` は手で編集・削除しない。再取得は `socioscope run <theme> fetch`。manifest（`data/raw/manifest.jsonl`）は追記のみ。
- `data/staged`・`data/marts` の Parquet はパイプラインの出力。手で書き換えない。変更は stage/mart のコードを直して再生成する。
- `data/llm_cache/*.jsonl` は追記のみ。消すと LLM を再呼び出しして結果が変わりうる（再現性が壊れる）。
- `*.duckdb` はコミットしない。
