# モノレポは uv workspace とし、共有 core は Ports & Adapters で構成する

- **Status**: Accepted
- **Date**: 2026-10-04
- **関連**: root `CLAUDE.md`、`design/overview.md`、[0002](0002-parquet-as-source-of-truth-duckdb-as-derived.md)

## Context
複数の分析テーマを 1 リポジトリで管理したい。テーマごとに依存（統計ライブラリ等）が異なりうるが、取得・来歴・LLM 構造化・保存の仕組みは共通。テーマ間の相互依存は避けたい。

## Decision
- ルートを **uv workspace** とし、`packages/core`（`socioscope-core`）と `themes/*`（`theme-<slug>`）を member にする。lock はルートに 1 つ。
- テーマは `socioscope.themes` **entry point** で自身の `Pipeline` を登録し、CLI（`socioscope run <theme> <stage>`）が発見する。テーマ同士は import しない。
- core は Ports & Adapters: `ports/`（Protocol: `SourceFetcher`, `Structurer`, `TableStore`）、`adapters/`（httpx, anthropic, Parquet/DuckDB）、`core/`（来歴・パイプライン定義。外部依存なし）。結線は `cli.py` とテーマの `wiring.py` のみ。
- テスト: core とテーマのパイプライン関数は In-Memory Fake（`FakeFetcher`, `InMemoryTableStore`, `FakeStructurer`）で状態ベースにテストする。

## Alternatives considered
- **テーマごとに別リポジトリ**: 共有コードの更新伝播と横断分析が面倒。却下。
- **単一パッケージに全テーマを同居**: 依存の衝突とテーマ境界の崩壊。却下。
- **Airflow/Dagster 等のオーケストレータ**: 現段階のデータ量・頻度に対して過剰。CLI ＋ Makefile で十分。必要になったら adapter として足せる。

## Consequences
**良い点**: テーマ追加が `/new-theme` で定型化できる。core の変更が全テーマで一度にテストできる。
**コスト**: workspace の pyproject 設定と entry point の作法を覚える必要がある。mypy/ruff 設定はルートに集約して重複を避ける。
