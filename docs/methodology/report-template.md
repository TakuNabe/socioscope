# <タイトル>（YYYY-MM-DD, theme: <slug>）

## 要約（3〜5 行）
結論を先に。因果か関連かを明記。

## 問いと仮説
`design/themes/<slug>.md` の該当節を引用し、本レポートが答える範囲を限定する。

## データ
| 変数 | 出典 | 定義・単位 | 期間・国 | 備考（欠損・断絶） |
|---|---|---|---|---|
mart: `data/marts/<file>.parquet`（行数 N、生成コマンド）。

## 方法
記述 / パネル回帰 / 識別戦略。仮定を列挙。

## 結果
図（`reports/figures/`）と表。推定値は点推定＋区間。

## 頑健性
仕様を変えた結果の一覧（全部）。

## 限界・言えないこと

## 再現手順
```bash
uv run socioscope run <theme> fetch && uv run socioscope run <theme> stage && uv run socioscope run <theme> mart
uv run python themes/<theme>/src/.../analysis/<script>.py
```

## チェックリスト回答
`docs/methodology/causal-inference-checklist.md` の A〜E に 1 行ずつ。
