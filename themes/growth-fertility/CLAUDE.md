# themes/growth-fertility
設計（問い・事前登録仮説・指標）: `design/themes/growth-fertility.md`。規約: root `CLAUDE.md`、`.claude/rules/themes.md`。

## 構成
```
src/theme_growth_fertility/
  worldbank.py   World Bank WDI API の URL 組み立てと JSON → 行 の純粋変換（決定的・テスト対象）
  estat.py       e-Stat 統計表（appId 不要）の URL 組み立てと ファイル → 行 の純粋変換（fail-closed）: 国民生活基礎調査 CSV（CP932）と 就業構造基本調査 第40表 xlsx（標準ライブラリで解析）
  dhs.py         DHS Program Indicator Data API（キー不要・引用義務）の URL 組み立てと JSON → 行 の純粋変換（TFR × 富裕五分位、ISO3 付け、fail-closed）
  oecd.py        OECD SOCX（SDMX REST、鍵不要）家族支出 TP51 の URL 組み立てと CSV → 行（STRUCTURE_ID・次元コード照合、38 加盟国に限定、fail-closed）。他テーマの oecd.py は import しない
  eurostat.py    Eurostat dissemination API（JSON-stat 2.0）の国別 Request、`jsonstat_rows`（疎 value の展開）、staged 行変換、mart 集計（有配偶率・出生順位別 TFR・学歴別 TFR）の純粋関数
  pipeline.py    fetch / stage / mart（Port 経由。I/O はここだけ。WB・e-Stat・DHS・OECD・Eurostat は独立に stage される。H5 は `# ---- H5` ブロックの `_fetch_h5/_stage_h5/_mart_h5`）
  kostat.py      国家データ処（韓国）신혼부부통계 報道資料 PDF（KOGL 第 1 類型）: RELEASES（基準年→静的 URL）、pypdf テキスト抽出、所得区間×子ども表の 3 レイアウト解析（fail-closed）
  pipeline.py    fetch / stage / mart（Port 経由。I/O はここだけ。WB・e-Stat・DHS は独立に stage される）
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
| `staged/worldbank/u5_mortality` | 〃 | 〃（`SH.DYN.MORT`、H4 段階指標） |
| `staged/worldbank/fem_sec_enrol` | 〃 | 〃（`SE.SEC.ENRR.FE`、H4） |
| `staged/worldbank/urban_share` | 〃 | 〃（`SP.URB.TOTL.IN.ZS`、H4） |
| `staged/worldbank/fem_lfp` | 〃 | 〃（`SL.TLF.CACT.FE.ZS`、H4。ILO 推計、1990 年以降） |
| `staged/worldbank/life_exp` | 〃 | 〃（`SP.DYN.LE00.IN`、H4） |
| `marts/growth_fertility_panel` | iso3×year | iso3, country, year, region, income_group, tfr, gdp_pcap_ppp, gdp_growth, population, u5_mortality, fem_sec_enrol, urban_share, fem_lfp, life_exp（217 経済 × 1960–2025 = 14,322 行） |
| `staged/dhs/tfr_by_wealth_quintile` | 調査×五分位 | iso3, country, dhs_country_code, survey_id, survey_year, survey_type(DHS/MIS/AIS), quintile(1..5), quintile_label, value, ci_low, ci_high, denominator_weighted, source(`dhs_api`)（ISO3 の付かない国コードの行は除外） |
| `marts/dhs_tfr_by_wealth_quintile` | 〃 | staged と同列。`survey_year, iso3, quintile` でソート（313 調査 × 5 = 1,565 行、2026-10-05 取得） |
| `staged/estat/kiso_income_dist_ts` | population×year×所得階級 | population(all/with_children), survey_year, year（所得年）, income_class, income_class_lower_yen, income_class_upper_yen, share_pct, source, stat_inf_id（1985–2024 × 25 階級 × 2 = 2,000 行） |
| `staged/estat/kiso_workers_marital_income` | 調査波×配偶者の有無×性×所得階級 | survey_year, year, marital(total/married/unmarried), sex(total/male/female), income_class…, workers_per_100k, source, stat_inf_id（5 波 × 9 × 18 = 810 行） |
| `staged/estat/kiso_hh_type_income` | 調査波×所得階級 | survey_year, year, income_class…, households_per_10k, with_children_per_10k, single_mother_per_10k, source, stat_inf_id（5 波 × 26 = 130 行） |
| `marts/jp_income_class_fertility` | long（metric 1 行） | survey, survey_year, year, income_class, income_class_lower_yen, income_class_upper_yen, sex, metric, value, denominator, source。metric = `married_share`（性別）, `children_household_share`, `household_share_pct`, `children_household_share_pct`（定義は `design/themes/growth-fertility.md`） |
| `staged/estat/shugyo_marital_age_income` | 性×配偶関係×年齢階級×所得階級 | survey_year, year（＝調査年 2022）, sex(total/male/female), marital(total/never_married), age_class, age_lower, age_upper（排他的上限）, income_class…, persons, source(`estat_shugyo`), stat_inf_id（3 × 2 × 16 × 17 = 1,632 行。従業上の地位＝総数・教育＝総数のみ） |
| `marts/jp_income_age_marital` | long（性×年齢×所得、metric 1 行） | survey, survey_year, year, sex, age_class, age_lower, age_upper, income_class, income_class_lower_yen, income_class_upper_yen, metric, value, denominator, source。metric = `ever_married_share` = (総数 − 未婚)/総数（816 行、`value` NULL 19 = 有業者 0 のセル）。年齢・所得の `total` 行も保持 |
| `staged/oecd/family_spending` | iso3×year×spending_type | iso3, year, spending_type(`_T`/`C`/`K`), value, unit(`PT_B1GQ`), source(`oecd_socx`)（SOCX TP51 公的家族支出 %GDP、OECD 38、1980–） |
| `marts/oecd_family_spending` | 〃 | staged と同列。`iso3, year, spending_type` でソート |
| `staged/eurostat/census_marital_education` | iso3×sex×age×isced11×marsta | iso3, year(2021), sex, age_class, age_lower, age_upper（排他的上限）, isced11, marsta(TOTAL/MAR_REP/UNK), value, source(`eurostat`) |
| `marts/eu_census_marital_by_education` | iso3×sex×age×学歴 3 群 | iso3, year, sex, age_class, age_lower, age_upper, isced_group(ED0-2/ED3-4/ED5-8), married(=Σ MAR_REP), total(=Σ TOTAL − Σ UNK), married_share, source |
| `staged/eurostat/births_by_order` | iso3×year×age×ord_brth | iso3, year, age_class(Y15…Y49, UNK), ord_brth(TOTAL/1/2/3/GE4/UNK), births, source |
| `staged/eurostat/population_female_age` | iso3×year×age | iso3, year, age_class(Y15…Y49), women, source |
| `marts/eu_tfr_by_birth_order` | iso3×year×order | iso3, year, order(1/2/3/GE4/TOTAL/UNK), tfr(=Σ_{15–49} births/women), births_age_unknown, source |
| `staged/eurostat/births_by_education` | iso3×year×age×isced11 | iso3, year, age_class（1 歳刻みと 5 歳階級の両方を保持）, isced11(TOTAL/ED0-2/ED3_4/ED5-8/NAP/UNK), births, source |
| `staged/eurostat/lfs_population_female_education` | iso3×year×age×isced11 | iso3, year, age_class(5 歳階級), isced11(ED0-2/ED3_4/ED5-8/TOTAL), women_thousand, source（LFS 標本、非公表セルは行なし） |
| `marts/eu_tfr_by_education` | iso3×year×学歴群 | iso3, year, isced_group(ED0-2/ED3_4/ED5-8/TOTAL), tfr(=5 × Σ_{7 階級} births/(women×1000)), women_total_thousand, source |
| `staged/kostat/newlywed_income_children` | 報道資料×基準年×所得区間 | release_year, ref_year, population(`first_marriage_within_5y`), income_class(total/lt_1000/1000_3000/3000_5000/5000_7000/7000_10000/ge_10000), income_lower_10k_krw, income_upper_10k_krw（万ウォン、上限なし NULL）, couples, with_children_share, children_1_share, children_2_share, children_3plus_share（割合 0–1）, mean_children, income_concept(earned_business/wage_only), source(`kostat_newlywed`)（10 資料 × 1–2 年 × 7 = 133 行。各資料は前年も再掲） |
| `marts/kr_newlywed_income_children` | long（基準年×所得概念×所得区間、metric 1 行） | ref_year, release_year, income_class, income_lower_10k_krw, income_upper_10k_krw, metric[with_children_share / mean_children / couples / children_1_share / children_2_share / children_3plus_share], value, income_concept, source。(ref_year, income_concept, income_class) ごとに最新 release を採用し `ref_year, income_concept, income_lower` でソート（11 ブロック × 7 × 6 = 462 行、2015–2024） |

## 分析スクリプト・レポート
| script | report | 内容 |
|---|---|---|
| `analysis/a20261004_h1_income_tfr.py` | `reports/2026-10-04-h1-income-tfr.md`（＋ `.stdout.txt`、`figures/h1_*.png`） | H1: ln GDP pc × TFR の記述統計・プール OLS・二元 FE（国クラスタ SE）・高所得域の J 字検定・頑健性 |
| `analysis/a20261004_h2_growth_shocks.py` | `reports/2026-10-04-h2-growth-shocks.md`（＋ `.stdout.txt`、`figures/h2_*.png`） | H2: 成長率 × TFR。(a) 同一サンプルの二元 FE で ln GDP pc と成長率ラグ 0–3 の標準化係数・within-R² を比較、(b) ΔTFR の分布ラグ（国 FE）と累積反応、(c) 景気後退（成長率 < −2 %、5 年間隔）のイベントスタディ（−3..+5、端点ビン、国＋年 FE）、(d) 事前リストの異質性・頑健性、2008–09/2020 の記述図。H1 の `OIL_STATES`/`SMALL_POP`/`Est`/`_style` を import。識別戦略なし（関連のみ） |
| `analysis/a20261004_h3_jp_income_class.py` | `reports/2026-10-04-h3-jp-income-class.md`（＋ `.stdout.txt`、`figures/h3_*.png`） | H3: 日本の所得階級 × 男性有配偶率・児童世帯割合の勾配（階級単位の加重 OLS・Spearman・波間交互作用）と、国間 ln GDP pc × TFR 勾配との符号比較（レベル間比較、記述のみ） |
| `analysis/a20261004_h3b_age_adjusted.py` | `reports/2026-10-04-h3b-age-adjusted.md`（＋ `.stdout.txt`、`figures/h3b_*.png`） | H3b（H3 の事前に定めた精緻化）: 就業構造基本調査 2022 第40表で男性既婚経験率の所得勾配を年齢調整（年齢階級内勾配・直接法標準化・年齢 FE 付き加重 OLS）し、未調整勾配・H3 の勾配と比較（減衰率）。H3 のヘルパ（`band_midpoint`, `wls`, `band_frame` 等）を import して再利用 |
| `analysis/a20261005_h4_stage_vs_gdp.py` | `reports/2026-10-05-h4-stage-vs-gdp.md`（＋ `.stdout.txt`、`figures/h4_*.png`） | H4: 国間の負の所得勾配は人口転換の段階による見かけか。(a) 同一サンプルで段階指標 5 本（u5_mortality, fem_sec_enrol, urban_share, fem_lfp, life_exp）を加えた国間 ln GDP 係数の減衰比、(b) 二元 FE＋段階指標の ln GDP 係数、(c) 5 歳未満死亡率の層内勾配 vs 全体、(d) DHS 富裕五分位 TFR の gap = Q5 − Q1 を調査年の ln GDP に回帰（pooled／国 FE／人口加重 WLS）、(e) 日本は図示のみ。H1 の `build_regression_frame`/`fit`/`OIL_STATES`/`SMALL_POP` を import。判定基準は事前固定。識別戦略なし |
| `analysis/a20261006_h5_europe_korea_policy.py` | `reports/2026-10-06-h5-europe-korea-policy.md`（＋ `.stdout.txt`、`figures/h5_*.png`） | H5: (a) OECD SOCX 家族支出（合計／現金／現物）× WDI TFR の二元 FE（同時・3 年ラグ）、ΔTFR(2010→2021) の横断回帰、係数 × Δ支出 の分解（北欧 4 か国）、(b) Eurostat 2021 センサスの性 × 年齢 × 学歴 3 群の有配偶率の学歴勾配（年齢 FE 付き加重 OLS、31 か国）＋ 韓国新婚夫婦の所得区間別有子率の ln 所得勾配（記述）、(c1) 出生順位別 TFR の 2010→最新 分解と第 1 子寄与率、(c2) 学歴別 TFR（LFS 分母）の変化。H1 の `fit`、H3 の `wls`/`Coef` を import。判定基準は事前固定。識別戦略なし |
| `analysis/s20261005_summary.py` | `reports/2026-10-05-summary-growth-fertility.md`（＋ `.stdout.txt`、`figures/summary/s01_*.png`〜`s18_*.png`） | 総括（note.com 向け、日本語・一般読者）: H1〜H5 の結論を同じ mart から**再計算**して 18 枚の図にする（新しい推定なし。H1/H2/H3/H3b/H4/H5 の推定関数を import。s14 = 段階指標をそろえた国間／国内係数、s15 = DHS 五分位プロファイルと gap 散布、s16 = 家族支出 × TFR（within 係数と 2010 水準 × ΔTFR）、s17 = 欧州センサスの学歴勾配、s18 = 出生順位分解と韓国新婚夫婦）。図の文字は日本語（フォントは Hiragino Sans → … → Yu Gothic を検出、無ければ DejaVu で警告。下記規約の例外）。PNG は `metadata={"Software": None}` でバイト再現。純粋ヘルパは `tests/test_summary.py` |

## 規約
- World Bank の集計地域（World, North America=`NAC`, 所得グループ等）は indicator エンドポイントで `iso3` が 3 文字のまま返ることがある。fetch で `/v2/country` メタデータ（`countries.json`）も取得し、stage 段階で `region.id == "NA"` の経済を除外する（`worldbank.country_set` → `rows_from_response(countries=...)`）。`countries.json` が無いと stage は何も書かない（fail-closed）。
- `region` / `income_group` は取得時点の WB 分類（時間不変）。分析で閾値に使うときは report にその旨を書く。
- 欠損は `None` のまま。補完しない。分析スクリプトも listwise のみ。
- e-Stat CSV は CP932・前置き行・多段ヘッダ・全角数字。`estat.py` は NFKC 正規化してヘッダ行を探し、想定外のラベル・表題・列構成なら `ValueError`（fail-closed）。`'-'` は 0、`'…'`（調査中止）・`'・'` は None。`year` は**所得年**（調査年 − 1）。
- e-Stat 表を追加するときは `estat.TABLES` に `Table(key, statInfId, kind, survey_year)` を足し、`tests/fixtures/estat_*.csv`（CP932、数行）でパーサをテストする。statInfId は e-Stat の「所得・貯蓄」巻一覧（`design/data-sources.md`）から取る。Excel しか公開されない表は `file_kind=0`（raw は `.xlsx`、`estat.xlsx_rows` で標準ライブラリ解析。fixture は実ファイルから行を間引いた小さな xlsx）。`Table.source`／`Table.url` を使い、`estat.SOURCE` を直接参照しない。
- 就業構造基本調査（`estat_shugyo`）の `year` は**調査年**（所得は調査前 1 年、2021-10〜2022-09）。配偶関係は「総数」「うち未婚」のみなので mart の metric は `ever_married_share`（既婚経験率）であり、`married_share`（配偶者あり率）と混同しない。所得ラベル「50〜99万円」の上限は 100 万円に正規化する。
- `marts/jp_income_age_marital` は `staged/estat/shugyo_marital_age_income` があるときだけ書かれる（kiso の mart とは独立）。出典表記: 「出典：政府統計の総合窓口(e-Stat)、就業構造基本調査（総務省）を加工」。
- `marts/jp_income_class_fertility` は WB mart と独立に書かれる（staged/estat が無ければ skip）。出典表記: 「出典：政府統計の総合窓口(e-Stat)、国民生活基礎調査（厚生労働省）を加工」。
- DHS（`dhs.py`）: raw は `dhs_tfr_wealth.json` と `dhs_countries.json` の 2 件。stage は両方揃うときだけ `staged/dhs/tfr_by_wealth_quintile` を書く（countries が無いと fail-closed）。ISO3 は `/rest/dhs/countries` の `ISO3_CountryCode` で付け、付かない国コード（`OS`＝Nigeria (Ondo State) 等）は行を落として skipped に残す。`CharacteristicCategory != "Wealth quintile"`・未知ラベル・他指標の行は落とす。`TotalPages != 1` / `RecordCount != len(Data)` は `ValueError`。富裕五分位は**資産ベースの国内相対順位**（所得額ではない）。出典表記（引用義務）: `dhs.LICENSE` の文言をレポートに載せる。mart は WB・e-Stat と独立。
- 国家データ処 新婚夫婦統計（`kostat.py`）: raw は基準年ごとの PDF `newlywed_<ref_year>.pdf`（`kostat.RELEASES` の静的 URL、KOGL 第 1 類型）。**PDF は pypdf でテキスト抽出し、表のレイアウト差（2015 行×実数 / 2016–2019 行×構成比・千쌍 / 2020–2024 列×年ブロック）は 3 系統のみ解析、それ以外・見出し不一致・合計不一致は `ValueError`（fail-closed）** → stage は該当年を「`newlywed_<year>.pdf: layout not recognised (<reason>)`」として skipped に残し他の年を続行する。2015 年基準は賃金勤労者のみ（`income_concept = wage_only`）で断絶、2016 年基準が 2015 年を 근로＋사업소득 で再掲（`earned_business`）。千쌍単位の資料は ×1000 で쌍に換算。mart は WB・e-Stat・DHS と独立。出典表記: 「국가데이터처, 신혼부부통계（<year>년 기준）, 보도자료, mods.go.kr（KOGL 제1유형）」。新しい基準年を足すときは掲示板で `list_no`/`seq` を確認して `RELEASES` に追加し、`tests/fixtures/kostat_newlywed_<year>.txt`（表ページの pypdf テキスト、`\f` 区切り）でテストする。
- 分析スクリプトは `reports/figures/` に図を保存し、標準出力を `reports/<date>-<slug>.stdout.txt` に残す（report の数値の出所）。図の文字は matplotlib 同梱フォントで描ける英語にする（日本語フォントに依存させない）。例外は一般読者向けの総括（`s20261005_summary.py`、`figures/summary/`）のみ: 日本語フォントを `matplotlib.font_manager` で検出し、無い環境では DejaVu にフォールバックして stderr に警告する（PNG の sha256 はフォント環境に依存する）。
- OECD SOCX（`oecd.py`、H5）: raw は `oecd_socx/socx_family_spending.csv` 1 件（`_T+C+K` を 1 リクエスト）。`STRUCTURE_ID` と固定次元（SOCX / PT_B1GQ / ES10 / TP51 / _Z）を全行で照合し、違えば `ValueError`。`OBS_VALUE` 空は落とし、`OECD_MEMBERS` 38 か国以外（`OECD` 集計、BGR/HRV/PER/ROU）は落とす。他テーマの `oecd.py` と URL 規約は同じだが import しない（ADR 0001）。出典表記: 「OECD (2026), Social Expenditure Database (SOCX), https://sdmx.oecd.org (accessed on 2026-10-06)」。
- Eurostat（`eurostat.py`、H5）: JSON-stat の `value` は**疎な dict**（文字列セル番号 → 値）で、無いセルは欠損。`jsonstat_rows` は `id` × `size` の直積で位置を復元し、`value` に無いセルは出さない（補完しない）。`error` キー・`class != "dataset"`・`id/size/value` 欠落・次元サイズ不一致は `ValueError`。geo → ISO3 は固定辞書 `GEO_TO_ISO3`（`EL`→GRC, `UK`→GBR）で、辞書に無い geo（NUTS 地域）は落とす。リクエストは dataset × 国で分割（raw `eurostat_<dataset>_<geo>.json`）し、stage は raw のある国だけを連結、無い国は skipped に残す。mart は分母（`demo_pjan` / `lfsa_pgaed`）がそろうときだけ書く。`demo_faeduc` の 5 歳階級が無い国は 1 歳刻み 5 本の合計を使う。LFS 分母が無く出生 > 0 の階級がある年・学歴群は落とす。出典表記: 「Source: Eurostat, <dataset>（accessed 2026-10-06）」。センサスの配偶関係は法律婚＋登録パートナーで同棲を含まない。
