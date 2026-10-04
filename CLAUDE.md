# socioscope — プロジェクト憲法（root）

グローバルおよび日本国内の**公開情報**を収集・構造化し、社会学的な分析と因果推論を行うモノレポ。
複数の分析テーマ（例: 人口分布×資産分布の変遷、経済成長×出生率）を同じリポジトリで管理する。

このファイルはモノレポ全体の**不変条件**を定義する。詳細は近い方の `CLAUDE.md`（`packages/core/CLAUDE.md`、`themes/<theme>/CLAUDE.md`）と、`.claude/rules/` のパス別ルールを正とする。

## 設計の出発点（必読）
着手前に、対象領域の設計ドキュメントを読む。ここが唯一の要件ソース。
- 全体像・目的・原則: `design/overview.md`
- データソース方針・利用規約: `design/data-sources.md`
- テーマ別の問い・仮説・指標: `design/themes/<theme>.md`
- アーキテクチャ決定記録: `docs/adrs/`（0001 モノレポ構成 / 0002 データ保存 / 0003 LLM 構造化 / 0004 自動化ハーネス）
- 分析の方法論・チェックリスト: `docs/methodology/`
- 実装計画: `docs/specs/<feature>.md` ＋ `docs/specs/<feature>.plan.yaml`

設計判断を変えるときは、コードだけでなく該当ドキュメント（必要なら新規 ADR）も更新する。

## モノレポ構成（uv workspace）
```
packages/core/   共有ライブラリ socioscope_core（Ports & Adapters）: 取得・来歴・LLM構造化・Parquet/DuckDB・CLI
themes/<slug>/   分析テーマ（独立パッケージ）: pipeline（fetch→stage→mart）・queries/・notebooks/・reports/
data/            raw（gitignore、manifest で再取得可）/ staged / marts（Parquet, git 管理）/ llm_cache（JSONL, git 管理）
design/          要件・テーマ設計（一次ソース）
docs/            adrs（決定記録）/ specs（spec・plan manifest）/ methodology（分析規約）
```

## 全モジュール共通の不変条件
1. **アーキテクチャ**: `socioscope_core.core` と各テーマの `pipeline`/`analysis` は外部（HTTP・LLM・ファイルシステム・DuckDB）に直接依存しない。依存は `socioscope_core.ports` の Protocol 経由。結線は CLI／テーマの `wiring` のみ（ADR 0001）。
2. **開発手法**: 古典派（Detroit）TDD。Red→Green→Refactor。モックより In-Memory Fake ＋状態検証。テストを伴わない実装コードを足さない。
3. **データ規約（ADR 0002）**:
   - `data/raw/` の取得物は **manifest（URL・sha256・取得日時・ライセンス）** を必ず残す。manifest にない raw は存在しないものとして扱う。
   - `staged/`・`marts/` は **Parquet** を正とし、`*.duckdb` は再生成可能な派生物（コミットしない）。
   - 変換は**決定的**（同じ raw → 同じ Parquet）。乱数・現在時刻に依存させない。
4. **LLM 規約（ADR 0003）**: LLM 出力は閉じたスキーマ（Pydantic）で受け、`data/llm_cache/` に prompt hash・model・schema version 付きでキャッシュする。LLM は**構造化・分類の補助**に限定し、数値の推定・補完には使わない。
5. **分析の誠実さ（`docs/methodology/causal-inference-checklist.md`）**: 相関と因果を区別して書く。識別戦略・仮定・頑健性チェック・限界を report に明記する。都合の良い結果だけを残さない（事前に決めた指標を報告する）。
6. **セキュリティ**: API キーはコード・ログ・リポジトリに置かない（環境変数）。外部レスポンスは境界（adapter）で Pydantic 検証。SQL は DuckDB のパラメータバインドを使い、文字列連結しない。データソースの利用規約・robots.txt・ライセンスを守り、`design/data-sources.md` に記録する。個人を特定できるデータは扱わない（集計統計のみ）。

## 作業の基本フロー
- 着手前に設計ドキュメントと近い方の `CLAUDE.md` を読む。
- 変更後は `/check`（`make check` 相当）を通す。
- commit / push はユーザーの指示があるときのみ。`main` に直接作業しない（ブランチを切る。hook でも拒否される）。

## エージェント／スキルの使い分け
| 用途 | 手段 |
|---|---|
| 要望 → spec ＋ plan manifest（PR 単位 DAG） | `planner` エージェント / `/spec-plan` |
| 承認済み plan の実行（実装→ゲート→レビュー→PR） | `/build-plan` |
| core・パイプラインの実装（TDD） | `pipeline-dev` エージェント |
| 新データソースの調査・ライセンス確認・adapter 追加 | `source-scout` エージェント / `/new-source` |
| 新テーマの追加 | `/new-theme <slug>` |
| 分析の実行・レポート作成 | `analyst` エージェント / `/analyze <theme>` |
| 境界・データ規約・セキュリティのレビュー | `architecture-reviewer` エージェント |
| 統計・因果推論の妥当性レビュー | `methodology-reviewer` エージェント |
| レビュー↔修正の自動反復 | `/review-loop` |
| 品質ゲート | `/check` |
| ADR の作成・更新 | `/adr` |
| commit → push → PR | `/ship` |
