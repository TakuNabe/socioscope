.PHONY: sync check lint fmt type test db notebook

sync:            ## 依存を同期（全 workspace member）。macOS の hidden フラグ対策込み（README トラブルシュート）
	uv sync --all-packages
	-chflags -R nohidden .venv 2>/dev/null

fmt:
	uv run ruff format .

lint:
	uv run ruff format --check .
	uv run ruff check .

type:
	uv run mypy packages/core/src themes/*/src

test:
	uv run pytest

check: lint type test   ## 品質ゲート一括（/check skill と同一）

db:              ## data/**/*.parquet から socioscope.duckdb を再生成
	uv run socioscope db build

notebook:        ## marimo で探索ノートブックを開く
	uv run --group notebooks marimo edit notebooks
