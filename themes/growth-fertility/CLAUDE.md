# themes/growth-fertility
設計（問い・事前登録仮説・指標）: `design/themes/growth-fertility.md`。規約: root `CLAUDE.md`、`.claude/rules/themes.md`。

## 構成
```
src/theme_growth_fertility/
  worldbank.py   World Bank WDI API の URL 組み立てと JSON → 行 の純粋変換（決定的・テスト対象）
  pipeline.py    fetch / stage / mart（Port 経由。I/O はここだけ）
  wiring.py      PIPELINE（entry point）。stage 関数の登録のみ
  analysis/      report 用スクリプト（決定的、seed 固定）
queries/         DuckDB 用 SQL（? バインド）
reports/         <yyyy-mm-dd>-<slug>.md ＋ figures/
tests/           fixtures/（実レスポンスの縮約）＋ Fake による状態テスト
```

## テーブル
| name | 粒度 | 列 |
|---|---|---|
| `staged/worldbank/tfr` | iso3×year | iso3, country, year, value, indicator, source |
| `staged/worldbank/gdp_pcap_ppp` | 〃 | 〃 |
| `staged/worldbank/gdp_growth` | 〃 | 〃 |
| `marts/growth_fertility_panel` | iso3×year | iso3, country, year, tfr, gdp_pcap_ppp, gdp_growth |

## 規約
- World Bank の集計地域（EU, World 等）は `iso3` が 3 文字でも `region` 扱いになることがある。mart では `is_aggregate` を落とすのではなく、stage 段階で `country` レベルのみに絞る（`worldbank.rows_from_response` 内、`region.id == "NA"` を除外）。
- 欠損は `None` のまま。補完しない。
