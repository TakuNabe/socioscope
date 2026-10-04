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
| `staged/worldbank/countries` | iso3 | iso3, country, region, income_group, source（`/v2/country` メタデータ。集計地域は除外済み） |
| `staged/worldbank/tfr` | iso3×year | iso3, country, year, value, indicator, source |
| `staged/worldbank/gdp_pcap_ppp` | 〃 | 〃 |
| `staged/worldbank/gdp_growth` | 〃 | 〃 |
| `staged/worldbank/population` | 〃 | 〃（`SP.POP.TOTL`。サンプル絞り込み用） |
| `marts/growth_fertility_panel` | iso3×year | iso3, country, year, region, income_group, tfr, gdp_pcap_ppp, gdp_growth, population（217 経済 × 1960–2025 = 14,322 行） |

## 分析スクリプト・レポート
| script | report | 内容 |
|---|---|---|
| `analysis/a20261004_h1_income_tfr.py` | `reports/2026-10-04-h1-income-tfr.md`（＋ `.stdout.txt`、`figures/h1_*.png`） | H1: ln GDP pc × TFR の記述統計・プール OLS・二元 FE（国クラスタ SE）・高所得域の J 字検定・頑健性 |

## 規約
- World Bank の集計地域（World, North America=`NAC`, 所得グループ等）は indicator エンドポイントで `iso3` が 3 文字のまま返ることがある。fetch で `/v2/country` メタデータ（`countries.json`）も取得し、stage 段階で `region.id == "NA"` の経済を除外する（`worldbank.country_set` → `rows_from_response(countries=...)`）。`countries.json` が無いと stage は何も書かない（fail-closed）。
- `region` / `income_group` は取得時点の WB 分類（時間不変）。分析で閾値に使うときは report にその旨を書く。
- 欠損は `None` のまま。補完しない。分析スクリプトも listwise のみ。
- 分析スクリプトは `reports/figures/` に図を保存し、標準出力を `reports/<date>-<slug>.stdout.txt` に残す（report の数値の出所）。図の文字は matplotlib 同梱フォントで描ける英語にする（日本語フォントに依存させない）。
