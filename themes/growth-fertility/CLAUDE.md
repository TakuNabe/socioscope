# themes/growth-fertility
設計（問い・事前登録仮説・指標）: `design/themes/growth-fertility.md`。規約: root `CLAUDE.md`、`.claude/rules/themes.md`。

## 構成
```
src/theme_growth_fertility/
  worldbank.py   World Bank WDI API の URL 組み立てと JSON → 行 の純粋変換（決定的・テスト対象）
  estat.py       e-Stat 国民生活基礎調査 統計表 CSV（CP932, appId 不要）の URL 組み立てと CSV → 行 の純粋変換（fail-closed）
  pipeline.py    fetch / stage / mart（Port 経由。I/O はここだけ。WB と e-Stat は独立に stage される）
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
| `staged/estat/kiso_income_dist_ts` | population×year×所得階級 | population(all/with_children), survey_year, year（所得年）, income_class, income_class_lower_yen, income_class_upper_yen, share_pct, source, stat_inf_id（1985–2024 × 25 階級 × 2 = 2,000 行） |
| `staged/estat/kiso_workers_marital_income` | 調査波×配偶者の有無×性×所得階級 | survey_year, year, marital(total/married/unmarried), sex(total/male/female), income_class…, workers_per_100k, source, stat_inf_id（5 波 × 9 × 18 = 810 行） |
| `staged/estat/kiso_hh_type_income` | 調査波×所得階級 | survey_year, year, income_class…, households_per_10k, with_children_per_10k, single_mother_per_10k, source, stat_inf_id（5 波 × 26 = 130 行） |
| `marts/jp_income_class_fertility` | long（metric 1 行） | survey, survey_year, year, income_class, income_class_lower_yen, income_class_upper_yen, sex, metric, value, denominator, source。metric = `married_share`（性別）, `children_household_share`, `household_share_pct`, `children_household_share_pct`（定義は `design/themes/growth-fertility.md`） |

## 分析スクリプト・レポート
| script | report | 内容 |
|---|---|---|
| `analysis/a20261004_h1_income_tfr.py` | `reports/2026-10-04-h1-income-tfr.md`（＋ `.stdout.txt`、`figures/h1_*.png`） | H1: ln GDP pc × TFR の記述統計・プール OLS・二元 FE（国クラスタ SE）・高所得域の J 字検定・頑健性 |

## 規約
- World Bank の集計地域（World, North America=`NAC`, 所得グループ等）は indicator エンドポイントで `iso3` が 3 文字のまま返ることがある。fetch で `/v2/country` メタデータ（`countries.json`）も取得し、stage 段階で `region.id == "NA"` の経済を除外する（`worldbank.country_set` → `rows_from_response(countries=...)`）。`countries.json` が無いと stage は何も書かない（fail-closed）。
- `region` / `income_group` は取得時点の WB 分類（時間不変）。分析で閾値に使うときは report にその旨を書く。
- 欠損は `None` のまま。補完しない。分析スクリプトも listwise のみ。
- e-Stat CSV は CP932・前置き行・多段ヘッダ・全角数字。`estat.py` は NFKC 正規化してヘッダ行を探し、想定外のラベル・表題・列構成なら `ValueError`（fail-closed）。`'-'` は 0、`'…'`（調査中止）・`'・'` は None。`year` は**所得年**（調査年 − 1）。
- e-Stat 表を追加するときは `estat.TABLES` に `Table(key, statInfId, kind, survey_year)` を足し、`tests/fixtures/estat_*.csv`（CP932、数行）でパーサをテストする。statInfId は e-Stat の「所得・貯蓄」巻一覧（`design/data-sources.md`）から取る。
- `marts/jp_income_class_fertility` は WB mart と独立に書かれる（staged/estat が無ければ skip）。出典表記: 「出典：政府統計の総合窓口(e-Stat)、国民生活基礎調査（厚生労働省）を加工」。
- 分析スクリプトは `reports/figures/` に図を保存し、標準出力を `reports/<date>-<slug>.stdout.txt` に残す（report の数値の出所）。図の文字は matplotlib 同梱フォントで描ける英語にする（日本語フォントに依存させない）。
