# LLM による構造化は閉じた Pydantic スキーマで受け、来歴付きでキャッシュする

- **Status**: Accepted
- **Date**: 2026-10-04
- **関連**: root `CLAUDE.md` 不変条件 4、`packages/core/src/socioscope_core/adapters/claude_structurer.py`、[0002](0002-parquet-as-source-of-truth-duckdb-as-derived.md)

## Context
公開レポート（PDF/HTML の本文・表）など構造化 API のない情報を LLM で表に起こしたい。LLM の出力は非決定的で、コストもかかり、幻覚のリスクがある。

## Decision
- 構造化は `Structurer` Port（`structure(text, schema: type[BaseModel]) -> BaseModel`）経由。実装は Claude API の `messages.parse`（structured outputs）を使う `ClaudeStructurer`。既定モデルは `claude-opus-5-5`（環境変数 `SOCIOSCOPE_LLM_MODEL` で変更可）。bulk 抽出で安くしたい場合は `claude-sonnet-5-5` / `claude-haiku-4-5` に切り替え、report にモデルを記載する。
- **閉じたスキーマ**: 自由記述フィールドを持たせない。数値は原文の値をそのまま写す（推定・補完・単位換算は LLM にさせず、コードで行う）。各レコードに `source_quote`（原文の該当箇所）を持たせ、人が検証できるようにする。
- **キャッシュ＝来歴**: `data/llm_cache/<schema>.jsonl` に `{key: sha256(model+schema_version+prompt), model, schema_version, created_at, input_sha256, output}` を追記し、同じ key は再呼び出ししない。キャッシュは git 管理し、再実行で LLM を呼ばなくても Parquet が再生成できるようにする（決定性の担保）。
- テストは `FakeStructurer`（固定出力）で行い、実 API を叩くテストは書かない（契約テストは手動）。
- API キー未設定時、LLM を要するステージは**明示的に skip して報告**する（fail-closed、黙って空にしない）。

## Alternatives considered
- **自由形式の JSON を正規表現で拾う**: 検証不能。却下。
- **LLM に数値の補完・換算をさせる**: 幻覚リスク。却下（コードで決定的に行う）。
- **キャッシュをコミットしない**: 再実行で結果が変わり再現性が壊れる。却下。

## Consequences
**良い点**: 再現性・監査可能性・コスト抑制。モデル変更時の差分が `schema_version`/`model` で追える。
**コスト**: キャッシュの肥大（テキスト）。閾値を超えたら Parquet 化する。
