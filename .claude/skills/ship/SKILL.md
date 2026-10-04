---
name: ship
description: >-
  品質ゲートを通してから commit → push → PR 作成までの定型手順。ゲートが赤なら止まる（fail-closed）。
  main では作業せず必ずブランチを切る。「PR を作って」「ship して」で起動。
---

# 変更を出す（ゲート → commit → PR）
順序を守り、失敗したら**その場で止めて報告**する。

## 0. 事前確認
- `git status` / `git diff` で出す内容を把握。`.env`・`*.duckdb`・`data/raw/**`（manifest 以外）・無関係ファイルが混ざっていたら**中断**。
- `data/staged`・`data/marts` の Parquet が変わる場合は、行数・スキーマの変化を PR 本文に書けるよう `uv run socioscope db build && uv run socioscope db query "select count(*) from ..."` で把握する。

## 1. 品質ゲート
- `/check`。赤なら即中断。

## 2. ブランチ
- `main` なら `git switch -c <type>/<topic>`（plan 実行時は `plan/<feature>/<item-id>`）。main への commit/push は hook でも拒否される。

## 3. commit
- 関連変更のみ `git add`。Conventional Commits。末尾に
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  ```

## 4. push & PR
- `git push -u origin <branch>`、`gh pr create`。本文: 目的 / 変更点 / ゲート結果 / データ変化（行数・スキーマ） / 関連 design・ADR・spec。末尾に
  ```
  🤖 Generated with [Claude Code](https://claude.com/claude-code)
  ```
- PR URL を報告。**merge はしない**（人間ゲート）。
