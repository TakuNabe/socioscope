# data/

| ディレクトリ | git | 内容 |
|---|---|---|
| `raw/` | **管理しない**（manifest のみ） | 取得したままの生データ。`manifest.jsonl` に URL・sha256・取得日時・ライセンスを記録。`socioscope run <theme> fetch` で再取得。 |
| `staged/<domain>/` | 管理する | 正規化済み Parquet。共通キー: `iso3`, `year`。1 ソース 1 ファイルを基本に。 |
| `marts/` | 管理する | テーマ別の分析用テーブル（`<theme>_<name>.parquet`）。 |
| `llm_cache/` | 管理する | LLM 構造化の結果（JSONL, ADR 0003）。 |
| `socioscope.duckdb` | 管理しない | `socioscope db build` で `staged.*`/`marts.*` view を再生成。 |

詳細: `docs/adrs/0002-parquet-as-source-of-truth-duckdb-as-derived.md`
