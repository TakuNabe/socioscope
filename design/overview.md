# socioscope — 全体設計

## 目的
公開情報（国際機関統計・政府統計・学術データベース・公開レポート）を再現可能な形で収集・構造化し、
複数の社会学的テーマについて**記述統計 → 相関 → 因果推論**の段階で分析する。
成果は「データ（Parquet）＋再現コード＋レポート（Markdown）」の 3 点セットで git に残す。

## 原則
1. **再現性**: どの数値も `raw`（manifest 付き）から決定的に再生成できる。
2. **来歴（provenance）**: すべての行が出典（URL・取得日・ライセンス）に辿れる。LLM が構造化した値は、そのプロンプト／モデル／スキーマ版まで辿れる。
3. **誠実な推論**: 因果を主張するなら識別戦略を明示する（`docs/methodology/causal-inference-checklist.md`）。
4. **テーマの独立性**: テーマ同士は直接依存しない。共有は `packages/core` と `data/staged` の共通テーブル（国コード・年など）経由のみ。
5. **小さく始める**: 最初は国×年のパネル（数千〜数十万行）。データは Parquet で git 管理できる規模に保つ。

## データフロー（各テーマ共通）
```
fetch  : 公開ソース → data/raw/<theme>/<source>/...  ＋ data/raw/manifest.jsonl（来歴）
stage  : raw → data/staged/<domain>/*.parquet （正規化・共通キー: iso3, year, …）
mart   : staged → data/marts/<theme>_*.parquet （分析用の結合済みテーブル）
analyze: marts → themes/<theme>/reports/*.md （ノートブック or スクリプト、図は reports/figures/）
```
`socioscope.duckdb` は `data/**/*.parquet` の上に view を張った派生物で、常に再生成できる。

## テーマ一覧
- `design/themes/wealth-population-distribution.md`
- `design/themes/growth-fertility.md`

## 非スコープ（当面）
- 個人レベルのマイクロデータ（匿名化済みでも扱わない。集計統計のみ）
- Web UI / API サーバ（レポートは Markdown と図で十分）
- リアルタイム更新（年次〜四半期の手動／定期バッチ）
