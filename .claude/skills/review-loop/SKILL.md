---
name: review-loop
description: >-
  差分に対して「レビュー → 修正」を自動で回す。architecture-reviewer（コード）と、report が含まれるなら methodology-reviewer（分析）が
  APPROVED を出すまで、BLOCKING 指摘を実装役に渡して直す。反復上限つき。「レビューして直して」「レビューループ」で起動。
---

# レビュー↔修正ループ
回す主体は main（あなた）。**commit / PR はしない**（`/ship` の役割）。

## 前提
- 変更があること（`git status`）。無ければ報告して終了。
- レビュワーの選択: コード変更があれば `architecture-reviewer`。`themes/*/reports/**` か `analysis/**` に変更があれば **加えて** `methodology-reviewer`。
- 修正役: コード → `pipeline-dev`、report/analysis → `analyst`。

## 手順
1. 上限は既定 3 反復（ユーザー指定優先）。
2. 該当レビュワーを起動し、冒頭の `VERDICT:` / `FINDINGS:` を読む。複数レビュワーなら全員 APPROVED で成功。
3. `CHANGES_REQUESTED` なら **BLOCKING のみ**を修正役に渡して直させる（NIT は混ぜない）。修正後 `/check` を通す。
4. 繰り返し。上限で収束しなければ中断し、残 BLOCKING を列挙して人に上げる。

## 終了報告
反復回数・最終 VERDICT・直した BLOCKING・残 NIT。収束しなかった場合はなぜ自動修正で解けなかったか。

## 暴走防止
同じ指摘が 2 反復連続で解けない／差分が振動する／scope を越えそうなら、上限前でも中断。
