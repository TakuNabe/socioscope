---
name: new-theme
description: >-
  新しい分析テーマ（themes/<slug>）を追加する定型手順。design doc → workspace member 作成 → entry point 登録 → 空の pipeline とテスト。
  「テーマを追加」「/new-theme <slug>」で起動。
---

# 新テーマの追加: `/new-theme <slug> [日本語タイトル]`

1. **設計を先に**: `design/themes/<slug>.md` を作る（問い・**事前登録**仮説・指標・データ候補・分析段階・落とし穴）。既存の `growth-fertility.md` を雛形に。人に内容を確認してもらう。
2. **パッケージ**: `themes/growth-fertility/` を雛形に `themes/<slug>/` を作成。
   - `pyproject.toml`: `name = "theme-<slug>"`, `[project.entry-points."socioscope.themes"] <slug> = "theme_<snake>.wiring:PIPELINE"`
   - `src/theme_<snake>/{__init__,pipeline,wiring}.py`、`queries/`, `notebooks/`, `reports/figures/`, `tests/`
   - `CLAUDE.md`（テーマ固有の規約・テーブル一覧）、`README.md`
3. **ルート登録**: ルート `pyproject.toml` の `[dependency-groups].dev` と `[tool.uv.sources]` に `theme-<slug>` を追加、`[tool.mypy].mypy_path` に `themes/<slug>/src` を追加。`uv sync --all-packages`。
4. **最初のテスト**: `uv run socioscope themes` に新 slug が出ること、`stage`/`mart` が空入力で空の Parquet を書くことの状態テストを Red → Green。
5. `/check` green を確認し、`design/` と `README.md` のテーマ表を更新。commit は `/ship`。
