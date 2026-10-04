---
name: adr
description: >-
  ADR（docs/adrs/NNNN-<slug>.md）を新規作成、または既存 ADR を supersede する定型手順。設計判断を変える・固めるときに使う。
  「ADR を書いて」「この決定を記録」で起動。
---

# ADR の作成・更新
**このスキルは commit しない**（PR 化は `/ship`）。

1. `ls docs/adrs/` で最大番号を確認し 4 桁ゼロ埋めで +1。
2. slug は kebab-case。ファイル名 `NNNN-<slug>.md`。
3. 下記テンプレートで書く。**Alternatives considered と Consequences を必ず埋める。**
4. supersede する場合: 旧 ADR の Status を `Superseded by NNNN` に書き換え（内容は残す）、新 ADR の「関連」で旧番号を参照。
5. この決定で `design/`・`CLAUDE.md`・`.claude/rules/` の前提が変わるなら同じ変更に含める。
6. 差分を要約して報告。

```markdown
# <決定の一文タイトル>

- **Status**: Proposed | Accepted | Superseded by NNNN
- **Date**: YYYY-MM-DD
- **関連**: <ADR / design doc / skill / agent>

## Context
## Decision
## Alternatives considered
- **<案A>**: 不採用の理由
## Consequences
**良い点** / **コスト・リスク**
```
1 ADR = 1 決定。
