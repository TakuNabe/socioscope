---
paths:
  - "docs/adrs/**"
  - "design/**"
---
# 設計ドキュメントのルール
- ADR は `NNNN-<slug>.md`、`Status`（Proposed / Accepted / Superseded by NNNN）必須。1 ADR = 1 決定。`/adr` skill のテンプレートに従う。
- `design/themes/<slug>.md` の「仮説」「指標」は分析前に確定させる（事前登録）。分析後に変えるときは「事後追加」と明記して履歴を残す。
- 設計判断の変更はコードと同じ PR でドキュメントも更新する。
