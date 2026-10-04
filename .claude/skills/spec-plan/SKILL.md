---
name: spec-plan
description: >-
  要望と設計ドキュメントから spec と plan manifest（PR 単位の DAG）を起こす。planner エージェントに生成させ、人の承認を仰ぐところまで。
  「spec と計画を作って」「PR 単位に分解して」で起動。
---

# spec ＋ plan manifest を起こす（ADR 0004）
**plan 承認は最重要の人間ゲート**。ここでは生成と提示まで。実装（`/build-plan`）へ自動で進まない。

1. **対象の確定**: どのテーマ・どの design doc（`design/themes/<slug>.md` 等）か。曖昧なら人に確認。
2. **生成**: `planner` エージェントを起動し `docs/specs/<feature>.md` と `docs/specs/<feature>.plan.yaml`（`_plan.template.yaml` 準拠）を作らせる。
3. **設計影響**: planner が ADR 更新／新規が要ると判断したら、先に `/adr`。
4. **提示**: spec 要約・item 数・DAG・並列可能 item・想定 PR 数を提示し、**承認を仰ぐ**。
5. 承認後、manifest だけを `/ship` で docs PR にしてよい。実装は `/build-plan`。

コードは書かない・commit しない。スコープは `design/overview.md` の非スコープを守る。
