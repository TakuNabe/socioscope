# themes/growth-fertility
設計（問い・事前登録仮説・指標）: `design/themes/growth-fertility.md`。規約: root `CLAUDE.md`、`.claude/rules/themes.md`。

## 構成
```
src/theme_growth_fertility/
  worldbank.py   World Bank WDI API の URL 組み立てと JSON → 行 の純粋変換（決定的・テスト対象）
  estat.py       e-Stat 統計表（appId 不要）の URL 組み立てと ファイル → 行 の純粋変換（fail-closed）: 国民生活基礎調査 CSV（CP932）と 就業構造基本調査 第40表 xlsx（標準ライブラリで解析）
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
| `staged/estat/shugyo_marital_age_income` | 性×配偶関係×年齢階級×所得階級 | survey_year, year（＝調査年 2022）, sex(total/male/female), marital(total/never_married), age_class, age_lower, age_upper（排他的上限）, income_class…, persons, source(`estat_shugyo`), stat_inf_id（3 × 2 × 16 × 17 = 1,632 行。従業上の地位＝総数・教育＝総数のみ） |
| `marts/jp_income_age_marital` | long（性×年齢×所得、metric 1 行） | survey, survey_year, year, sex, age_class, age_lower, age_upper, income_class, income_class_lower_yen, income_class_upper_yen, metric, value, denominator, source。metric = `ever_married_share` = (総数 − 未婚)/総数（816 行、`value` NULL 19 = 有業者 0 のセル）。年齢・所得の `total` 行も保持 |

## 分析スクリプト・レポート
| script | report | 内容 |
|---|---|---|
| `analysis/a20261004_h1_income_tfr.py` | `reports/2026-10-04-h1-income-tfr.md`（＋ `.stdout.txt`、`figures/h1_*.png`） | H1: ln GDP pc × TFR の記述統計・プール OLS・二元 FE（国クラスタ SE）・高所得域の J 字検定・頑健性 |
| `analysis/a20261004_h2_growth_shocks.py` | `reports/2026-10-04-h2-growth-shocks.md`（＋ `.stdout.txt`、`figures/h2_*.png`） | H2: 成長率 × TFR。(a) 同一サンプルの二元 FE で ln GDP pc と成長率ラグ 0–3 の標準化係数・within-R² を比較、(b) ΔTFR の分布ラグ（国 FE）と累積反応、(c) 景気後退（成長率 < −2 %、5 年間隔）のイベントスタディ（−3..+5、端点ビン、国＋年 FE）、(d) 事前リストの異質性・頑健性、2008–09/2020 の記述図。H1 の `OIL_STATES`/`SMALL_POP`/`Est`/`_style` を import。識別戦略なし（関連のみ） |
| `analysis/a20261004_h3_jp_income_class.py` | `reports/2026-10-04-h3-jp-income-class.md`（＋ `.stdout.txt`、`figures/h3_*.png`） | H3: 日本の所得階級 × 男性有配偶率・児童世帯割合の勾配（階級単位の加重 OLS・Spearman・波間交互作用）と、国間 ln GDP pc × TFR 勾配との符号比較（レベル間比較、記述のみ） |
| `analysis/a20261004_h3b_age_adjusted.py` | `reports/2026-10-04-h3b-age-adjusted.md`（＋ `.stdout.txt`、`figures/h3b_*.png`） | H3b（H3 の事前に定めた精緻化）: 就業構造基本調査 2022 第40表で男性既婚経験率の所得勾配を年齢調整（年齢階級内勾配・直接法標準化・年齢 FE 付き加重 OLS）し、未調整勾配・H3 の勾配と比較（減衰率）。H3 のヘルパ（`band_midpoint`, `wls`, `band_frame` 等）を import して再利用 |
| `analysis/s20261005_summary.py` | `reports/2026-10-05-summary-growth-fertility.md`（＋ `.stdout.txt`、`figures/summary/s01_*.png`〜`s13_*.png`） | 総括（note.com 向け、日本語・一般読者）: H1〜H3b の結論を同じ mart から**再計算**して 13 枚の図にする（新しい推定なし。H1/H2/H3/H3b の推定関数を import）。図の文字は日本語（フォントは Hiragino Sans → … → Yu Gothic を検出、無ければ DejaVu で警告。下記規約の例外）。PNG は `metadata={"Software": None}` でバイト再現。純粋ヘルパは `tests/test_summary.py` |

## 規約
- World Bank の集計地域（World, North America=`NAC`, 所得グループ等）は indicator エンドポイントで `iso3` が 3 文字のまま返ることがある。fetch で `/v2/country` メタデータ（`countries.json`）も取得し、stage 段階で `region.id == "NA"` の経済を除外する（`worldbank.country_set` → `rows_from_response(countries=...)`）。`countries.json` が無いと stage は何も書かない（fail-closed）。
- `region` / `income_group` は取得時点の WB 分類（時間不変）。分析で閾値に使うときは report にその旨を書く。
- 欠損は `None` のまま。補完しない。分析スクリプトも listwise のみ。
- e-Stat CSV は CP932・前置き行・多段ヘッダ・全角数字。`estat.py` は NFKC 正規化してヘッダ行を探し、想定外のラベル・表題・列構成なら `ValueError`（fail-closed）。`'-'` は 0、`'…'`（調査中止）・`'・'` は None。`year` は**所得年**（調査年 − 1）。
- e-Stat 表を追加するときは `estat.TABLES` に `Table(key, statInfId, kind, survey_year)` を足し、`tests/fixtures/estat_*.csv`（CP932、数行）でパーサをテストする。statInfId は e-Stat の「所得・貯蓄」巻一覧（`design/data-sources.md`）から取る。Excel しか公開されない表は `file_kind=0`（raw は `.xlsx`、`estat.xlsx_rows` で標準ライブラリ解析。fixture は実ファイルから行を間引いた小さな xlsx）。`Table.source`／`Table.url` を使い、`estat.SOURCE` を直接参照しない。
- 就業構造基本調査（`estat_shugyo`）の `year` は**調査年**（所得は調査前 1 年、2021-10〜2022-09）。配偶関係は「総数」「うち未婚」のみなので mart の metric は `ever_married_share`（既婚経験率）であり、`married_share`（配偶者あり率）と混同しない。所得ラベル「50〜99万円」の上限は 100 万円に正規化する。
- `marts/jp_income_age_marital` は `staged/estat/shugyo_marital_age_income` があるときだけ書かれる（kiso の mart とは独立）。出典表記: 「出典：政府統計の総合窓口(e-Stat)、就業構造基本調査（総務省）を加工」。
- `marts/jp_income_class_fertility` は WB mart と独立に書かれる（staged/estat が無ければ skip）。出典表記: 「出典：政府統計の総合窓口(e-Stat)、国民生活基礎調査（厚生労働省）を加工」。
- 分析スクリプトは `reports/figures/` に図を保存し、標準出力を `reports/<date>-<slug>.stdout.txt` に残す（report の数値の出所）。図の文字は matplotlib 同梱フォントで描ける英語にする（日本語フォントに依存させない）。例外は一般読者向けの総括（`s20261005_summary.py`、`figures/summary/`）のみ: 日本語フォントを `matplotlib.font_manager` で検出し、無い環境では DejaVu にフォールバックして stderr に警告する（PNG の sha256 はフォント環境に依存する）。
