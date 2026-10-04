# packages/core — socioscope_core

共有ライブラリ。Ports & Adapters ＋ 古典派 TDD。root `CLAUDE.md` と `.claude/rules/core.md` が前提。

## ディレクトリと依存方向（内向きのみ）
```
src/socioscope_core/
  core/        ★外部依存なし（ports のみ import）
    provenance.py   RawRecord（URL・sha256・fetched_at・license・theme）、Manifest 行の生成/解析
    pipeline.py     Stage（fetch/stage/mart）、Pipeline（テーマが登録する stage 関数の束）、Context（Port の束）
    llm_cache.py    LLM 構造化キャッシュのキー（sha256(model|schema_version|prompt)）と行スキーマ
  ports/       Protocol
    fetcher.py      SourceFetcher: fetch(url) -> bytes
    structurer.py   Structurer: structure(prompt, schema) -> BaseModel
    store.py        TableStore: write_table(name, rows) / read_table(name) / list_tables()
                    RawStore: put(theme, source, name, payload) -> RawRecord（manifest 追記込み）
  adapters/    Port 実装（外部依存はここだけ）
    http_fetcher.py       HttpxFetcher（User-Agent、タイムアウト、リトライ）
    filesystem_raw.py     FilesystemRawStore（data/raw/<theme>/<source>/<name> + manifest.jsonl 追記）
    parquet_store.py      ParquetTableStore（data/<layer>/... .parquet。polars 経由）
    duckdb_catalog.py     build_catalog(db_path, data_dir): staged.* / marts.* の view を張る
    claude_structurer.py  ClaudeStructurer（anthropic messages.parse + data/llm_cache/*.jsonl）
  config.py    Settings（env: ANTHROPIC_API_KEY, SOCIOSCOPE_LLM_MODEL, SOCIOSCOPE_DATA_DIR）
  cli.py       typer: themes / run <theme> <stage> / db build / db query。結線はここだけ
tests/
  （Fake は src/socioscope_core/testing/fakes.py に置く: テーマのテストからも import できるようにするため）
  core/        core のテスト（Fake、高速）
  adapters/    adapter のテスト（tmp_path 上の実ファイル・実 DuckDB。ネットワーク・実 API は叩かない）
```

## テーマの登録
テーマは `pyproject.toml` の entry point `socioscope.themes` に `Pipeline` オブジェクトを公開する。
`cli.py` は `importlib.metadata.entry_points(group="socioscope.themes")` で発見し、`Context`（実 adapter の束）を渡して stage を実行する。

## ツールチェーン
ルートで `uv sync --all-packages` / `make check`。個別: `uv run pytest packages/core/tests -q`。
