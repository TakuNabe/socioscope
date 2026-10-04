# 解析データは Parquet を正として git 管理し、DuckDB ファイルは再生成可能な派生物とする

- **Status**: Accepted
- **Date**: 2026-10-04
- **関連**: `design/overview.md`、`data/README.md`、[0001](0001-monorepo-uv-workspace-and-ports-adapters.md)

## Context
解析データは大きくない（国×年パネル、数万〜数十万行）。当初案は「DuckDB ファイルを artifact として git 管理」。

## Decision
1. **`data/staged/`・`data/marts/` の Parquet を正（source of truth）として git で管理する。**
2. **`socioscope.duckdb` はコミットしない。** `socioscope db build` が `data/**/*.parquet` の上に `staged.*` / `marts.*` の view を張って毎回生成する（数秒）。
3. **`data/raw/` はコミットしない**（サイズ・ライセンス再配布の懸念）。代わりに `data/raw/manifest.jsonl`（URL・sha256・取得日時・ライセンス・テーマ）をコミットし、再取得で復元できるようにする。再配布可能なライセンスで小さい raw は例外的にコミットしてよい（manifest に `committed: true`）。
4. **LLM 構造化の結果は `data/llm_cache/*.jsonl`（prompt hash・model・schema version 付き）としてコミットする**（[0003](0003-llm-structuring-closed-schema-and-cache.md)）。
5. 単一 Parquet が 50MB を超える見込みなら、分割（`year=` パーティション）か git LFS を検討し、ADR を追記する。

## Alternatives considered
- **DuckDB ファイルを git 管理**: 却下。バイナリで差分が取れず、書き込みごとにファイル全体に近い変更が出て履歴が肥大する。DuckDB のストレージ形式はバージョン間で互換性が保証されない時期があり、将来読めなくなるリスクがある。複数 PR の並行変更も衝突する。
- **DVC / lakeFS**: 現段階の規模には過剰。Parquet が LFS 閾値を超えたら再検討。
- **SQLite**: 列指向分析・Parquet 直読みができる DuckDB の方が解析用途に合う。DuckDB は「クエリエンジン」として採用し、保存形式には使わない。
- **CSV**: 型・サイズ・読み込み速度で Parquet に劣る。人が diff を見たい小さな手入力データ（辞書・国コード表など）は例外として CSV/YAML を許す。

## Consequences
**良い点**: 履歴が追える・PR で差分（行数・スキーマ）がレビューできる・DuckDB のバージョンに依存しない・pandas/polars/R からも直接読める。
**コスト**: Parquet はバイナリなので行レベル diff は見えない。PR 時は `socioscope db diff`（将来）やスキーマ・行数の要約で補う。
