# 開発・分析自動化ハーネス（成果物駆動・指揮者＋人間ゲート）

- **Status**: Accepted
- **Date**: 2026-10-04
- **関連**: root `CLAUDE.md`、`.claude/agents/*`、`.claude/skills/{spec-plan,build-plan,check,review-loop,ship,adr,analyze,new-theme,new-source}`、`docs/specs/_plan.template.yaml`

## Context
Claude Code で「設計 → spec → plan → 実装 → 品質ゲート → レビュー → PR」と「データ取得 → 分析 → レポート」を反復可能に回したい。参考: shochupedia リポジトリの ADR 0002（成果物駆動パイプライン）。本リポジトリは**分析**が主なので、コードレビューに加えて**方法論レビュー**のゲートを持つ。

## Decision
**成果物駆動パイプライン**を採用する。各ステージが人間可読な durable 成果物を残し、main スレッドが指揮者として繋ぐ。人間ゲートは **plan 承認**・**merge**・**report 公開前の方法論レビュー承認** の 3 点。

| ステージ | 成果物 | 手段 | ゲート |
|---|---|---|---|
| 要件・テーマ設計 | `design/**/*.md` | 人＋対話 | — |
| 決定 | `docs/adrs/NNNN-*.md` | `/adr` | 人 |
| 仕様・計画 | `docs/specs/<feature>.md` ＋ `.plan.yaml`（PR 単位 DAG） | `planner` / `/spec-plan` | **人が plan を承認** |
| 実装 | ブランチ＋PR | `pipeline-dev`（並列時は worktree 分離） | `/check` → `/review-loop`（`architecture-reviewer`） |
| データソース追加 | `design/data-sources.md` 更新 ＋ adapter | `source-scout` / `/new-source` | ライセンス確認（人） |
| 分析 | `themes/<t>/reports/<date>-<slug>.md` ＋ 図 ＋ 再現コード | `analyst` / `/analyze` | `methodology-reviewer`（VERDICT 契約） |
| 統合 | `main` | `/ship` → 人が merge | 人 |

### 共通契約
- レビュワー（`architecture-reviewer`, `methodology-reviewer`）は出力冒頭に `VERDICT: APPROVED | CHANGES_REQUESTED` と `FINDINGS:`（`[BLOCKING]`/`[NIT]`）を出す。`/review-loop` はこれを機械的に読む。
- plan manifest（`docs/specs/<feature>.plan.yaml`）は `scope`（触るパス）で DAG を引き、scope が重ならない item のみ `isolation: "worktree"` で並列実装する（merge-gated）。
- ハードルール（`.claude/settings.json` hooks）: `main` への commit/push 拒否、`data/raw` 等の破壊的削除の拒否、Python 編集時の ruff 自動整形。
- パス別ルール（`.claude/rules/*.md`）: `packages/core`・`themes`・`data`・`docs/adrs` ごとの規約を近接ロードする。

### 段階的ロールアウト
- Stage 1（今）: `/adr`・`/spec-plan`・`/check`・`/ship`・`/review-loop`・`/new-theme`・`/new-source`・`/analyze`。
- Stage 2: `/build-plan` 逐次実行を最初の feature で検証。
- Stage 3: worktree 並列化。

## Alternatives considered
- **全自動オートパイロット**: 判断（plan・merge・方法論）を飛ばして事故る。却下。
- **分析をノートブックだけで管理**: 再現性・レビュー不能。ノートブックは探索用（marimo の `.py` 形式）に限定し、report と mart 生成はスクリプト・SQL で行う。
- **コードレビューだけで方法論レビューを省く**: 統計的に誤った主張が通る。却下。

## Consequences
**良い点**: 透明・再開可能。分析の誤りをコードと同じ規律で止められる。
**コスト**: ADR/spec/report の維持コスト。レビュワーのプロンプト鮮度の維持。
