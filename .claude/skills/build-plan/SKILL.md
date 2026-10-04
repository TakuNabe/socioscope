---
name: build-plan
description: >-
  承認済みの plan manifest（PR 単位の DAG）を指揮者として実行する。依存順に item を実装→ゲート→レビュー→PR まで運び、
  scope が重ならない独立 item は worktree 分離で並列実装する。「計画を実行して」「build-plan して」で起動。
---

# plan manifest を実行する — 指揮者（ADR 0004）
回す主体は main（あなた）。`docs/specs/<feature>.plan.yaml` を唯一の調整アーティファクトとする。
**前提**: manifest は人が承認済み。未承認なら実行しない。

## 1. 状態把握
- manifest を読み DAG を構築。item ↔ PR はブランチ名 `plan/<feature>/<item-id>` で対応。
- 依存 item の merge 済み判定は `gh pr list --state merged` / `git log` を正とする（`status` は人間可読ミラー）。

## 2. 次の item を選ぶ
- 実行可能 = 未完了かつ全 `depends_on` が merge 済み。
- 無ければ「item X の merge 待ち」と報告して停止、または全 merged なら完了報告。
- 複数あるとき、scope が互いに重ならないものだけ並列（既定上限 3）。重なるペアは同時に走らせない。

## 3A. 単一 item
1. main から `plan/<feature>/<item-id>` を切る。2. manifest を `in_progress` に。
3. item の `agent`（`pipeline-dev` / `source-scout` / `analyst`）で `acceptance` を満たす実装（TDD）。scope 外に出ない。
4. `/check`（赤なら停止）。5. `/review-loop`（APPROVED まで。analyst item は `methodology-reviewer` も通す）。
6. `/ship`。manifest を `pr_open` + URL に更新し同じ PR に含める。7. PR URL を報告し停止（merge は人）。

## 3B. 並列
- item ごとに `Agent` を `isolation: "worktree"`・`run_in_background: true` で起動。各 item は自己完結で `実装 → /check → /review-loop → /ship` を行い PR URL を返す。
- 全完了を待ち、PR 群と manifest 更新をまとめて報告。失敗 item は理由付きで停止扱い、成功分は活かす。
- `data/staged`・`data/marts` の同じ Parquet を書く item は scope 重複として並列化しない。

## 4. 再開
人が merge したら再度 `/build-plan`。

## 暴走防止
scope 逸脱・DAG 破綻（循環・衝突必至）・ゲート不収束は停止して人に上げる。1 item = 1 PR。
