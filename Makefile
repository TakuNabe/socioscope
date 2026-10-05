.PHONY: sync doctor check lint fmt type test db notebook

# venv はドット名でない `venv/` に置く（ADR 0005）。
# ~/Desktop・~/Documents は iCloud Drive 同期の対象で、ドット始まりの項目とその配下に
# UF_HIDDEN が付与される → Python 3.13 の site.py が hidden な .pth を無視し、workspace
# member（editable）が import できなくなる。相対パスは workspace root 基準なので worktree ごとに独立。
export UV_PROJECT_ENVIRONMENT ?= venv

sync:            ## 依存を同期（全 workspace member）。`.venv` は `venv` への symlink にして素の `uv run` も同じ環境を使う
	uv sync --all-packages
	@if [ -e .venv ] && [ ! -L .venv ]; then echo "legacy .venv/ を削除して venv/ への symlink に置き換えます"; rm -rf .venv; fi
	@[ -L .venv ] || ln -s "$(UV_PROJECT_ENVIRONMENT)" .venv
	@# `.claude/worktrees/*` のようにドット名ディレクトリ配下の checkout では venv も iCloud に hidden 化されるため、保険として外す（ADR 0005 追記）
	@chflags -R nohidden "$(UV_PROJECT_ENVIRONMENT)" 2>/dev/null || true

doctor:          ## 環境診断: workspace member が import できるか／hidden フラグの有無
	@echo "UV_PROJECT_ENVIRONMENT=$(UV_PROJECT_ENVIRONMENT)"
	@if uv run --no-sync python -c "import socioscope_core, theme_growth_fertility, theme_wealth_population_distribution" 2>/dev/null; then \
	  echo "ok: workspace member は import できます"; \
	else \
	  echo "NG: workspace member が import できません"; \
	  if uv run --no-sync python -v -c pass 2>&1 | grep -q 'Skipping hidden .pth file'; then \
	    echo "  原因: venv 内の .pth に macOS hidden フラグ（iCloud 同期がドット名の項目に付与）。"; \
	  fi; \
	  echo "  対処: make sync（venv/ に再同期し .venv を symlink 化）。それでも直らなければ rm -rf venv .venv && make sync"; \
	  exit 1; \
	fi
	@if [ -e .venv ] && [ ! -L .venv ]; then echo "warn: 実体の .venv/ があります。make sync で venv/ への symlink に置き換えてください"; fi
	@hidden=$$(find "$(UV_PROJECT_ENVIRONMENT)" -flags +hidden 2>/dev/null | wc -l | tr -d ' '); \
	  if [ "$${hidden:-0}" != "0" ]; then echo "warn: $(UV_PROJECT_ENVIRONMENT) 配下に hidden フラグ付きが $$hidden 件（ADR 0005 を参照）"; fi

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
