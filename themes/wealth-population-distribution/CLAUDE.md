# themes/wealth-population-distribution
設計: `design/themes/wealth-population-distribution.md`。規約: root `CLAUDE.md`、`.claude/rules/themes.md`。
データソースの調査記録: `design/data-sources.md`（WID.world、OECD SDMX）。

## 構成
```
src/theme_wealth_population_distribution/
  wid.py                 WID.world 国別 zip の URL 組み立て、zip → CSV 抽出、CSV → 行 の純粋変換（決定的・テスト対象）
  wid_iso2_to_iso3.csv   WID alpha2 → ISO3 の固定表（pycountry から生成しコミット。手で直す場合は理由をコメント）
  oecd.py                OECD SDMX REST の URL 組み立て（dataflow＋key）、CSV → 行（STRUCTURE_ID・全次元コードを照合、fail-closed）、OECD_MEMBERS（38）
  pipeline.py            fetch / stage / mart（Port 経由。I/O はここだけ）。OECD は _fetch_oecd / _stage_oecd / _mart_institutions に分離
  wiring.py              PIPELINE（entry point）
  analysis/              report 用スクリプト（決定的、seed 固定）: a20261004_h1_ushape.py（H1）、a20261004_h1b_observed_only.py（H1b）、a20261004_h2_institutions.py（H2）
tests/                   fixtures/wid_data_sample.csv, wid_metadata_sample.csv（合成の数行）、fixtures/oecd_*_sample.csv（実レスポンスの JPN 数行）＋ Fake による状態テスト
```

## 状態
WID.world を採用し fetch/stage/mart 実装済み（ライセンスは **CC BY-NC-SA 4.0** 扱い、`design/data-sources.md` 参照）。
OECD SDMX（最高税率・社会支出・税収・相続税収）を H2 用に採用し fetch/stage/mart 実装済み（OECD Terms & Conditions 2024、出典表示で自由利用）。
H1 report: `reports/2026-10-04-h1-ushape.md`。H2 report（限定・関連のみ）: `reports/2026-10-04-h2-institutions.md`。
World Bank Gini、UN WPP 等は未接続。

## 実行
```bash
uv run socioscope run wealth-population-distribution fetch --only oecd   # OECD 4 リクエストだけ（WID 46 zip の再取得を避ける）
uv run socioscope run wealth-population-distribution stage --only oecd   # staged/oecd/* のみ更新（WID の staged は触らない）
uv run socioscope run wealth-population-distribution mart                # 両 mart を再生成（staged/wid/* が必要）
```

## テーブル
| name | 粒度 | 列 |
|---|---|---|
| `staged/wid/top_shares` | iso3×year×variable×percentile | iso3, year, variable (`sptinc992j` / `shweal992j`), percentile (`p0p50`,`p50p90`,`p90p100`,`p99p100`), value (0–1 のシェア), data_quality (0–5 / None), source |
| `staged/wid/population` | iso3×year | iso3, year, value (人), data_quality, source |
| `staged/wid/metadata` | iso3×variable | iso3, variable (`sptinc992j`/`shweal992j`/`npopul999i`), shortname, unit, source_text (WID の `source` 列: 文献・URL), method (WID の `method` 自由記述), avg_quality (float / None), source |
| `staged/wid/data_points` | iso3×variable×year（`top_shares` にある年） | iso3, year, variable, is_observed (bool / None=不明), construction (`observed`/`partial`/`imputed`/None), basis (`method_by_year` / `trend_before_YYYY` / `long_run_before_YYYY` / None), method_segment (年別記述の原文 / None), source |
| `marts/wealth_population_panel` | iso3×year | iso3, year, top1_income_share, top10_income_share, bottom50_income_share, top1_wealth_share, top10_wealth_share, population, source, top1_income_observed (bool/null), top1_wealth_observed (bool/null) |
| `staged/oecd/<indicator>`（`top_pit_rate`, `social_expenditure_gdp`, `tax_revenue_gdp`, `inheritance_tax_rev_gdp`） | iso3×year | iso3, year, value (%), unit (SDMX コード `PT_WG_EARN_G` / `PT_B1GQ`), obs_status, source (`oecd`) |
| `marts/wealth_institutions_panel` | iso3×year（OECD 38、1980–） | iso3, year, top1_income_share, top10_income_share, top1_wealth_share, top10_wealth_share, top1_income_quality, top1_wealth_quality (WID data_quality), top_pit_rate, social_expenditure_gdp, tax_revenue_gdp, inheritance_tax_rev_gdp, source (`wid_world+oecd`) |
| `staged/worldbank/gini`（予定） | iso3×year | iso3, country, year, value, indicator, source |

## 規約・決定
- **対象国**: `wid.COUNTRIES` の 46 か国（OECD 38 ＋ 非 OECD G20 8: AR BR CN IN ID RU SA ZA）。raw は国別 zip（計 ~196MB）。全量 zip は 882MB で予算超過のため使わない。国を増やすときは raw サイズ（1 国 1〜9MB）を見て `COUNTRIES` を編集し、fetch を再実行する。
- **raw**: `data/raw/wealth-population-distribution/wid_world/WID_fulldataset_<ISO2>.zip` をそのまま保存（gitignore、manifest に URL・sha256・ライセンス）。zip 展開は stage 側で `wid.extract_data_csv` / `wid.extract_metadata_csv`（bytes → bytes の純粋関数）で行う。
- **WID metadata の実フォーマット（2026-10-04 に 46 zip すべてで確認）**: `WID_metadata_<ISO2>.csv` は `;` 区切り 18 列 `country;variable;age;pop;countryname;shortname;simpledes;technicaldes;shorttype;longtype;shortpop;longpop;shortage;longage;unit;source;method;avg_quality`（zip 内 README は 17 列と書くが `avg_quality` が追加されている）。**`data_points` / `extrapolation` / `data_quality` の列は無い**。年別の観測／補間／外挿の情報は `method` の自由記述だけ: 欧州 DINA 所得系列 26 か国に「Summary of data construction by year (see source for details): 1980: extrapolated distribution, 1981-2005: survey + concept correction + tax data, …」、多くの系列に「Before 1980, series is constructed based on the trend observed in the fiscal income data available (see sources).」「Before 1913, pretax income shares estimated based on methodology in long-run paper (see sources).」。資産系列に年別記述は無い。`wid.parse_method` が文を年→記述に展開し、`wid.classify_segment` が `survey`/`tax data` を観測入力、`interpolated …`/`extrapolated …` を推計入力、`concept correction`/`imputed nonresponse`/`extrapolated nonresponse` を補正として observed/partial/imputed に分類する（未知の語は fail-closed）。header が変われば stage が止まる（`METADATA_HEADER`）。
- **変数コード**: bulk CSV の `variable` は `sptincj992`（型+概念+pop+age）。staged ではサイト表記 `sptinc992j`（型+概念+age+pop）に正規化する（`wid.canonical_code`）。
- **ISO2→ISO3**: `wid_iso2_to_iso3.csv` の固定表で変換。表にない・2 文字でないコードは**捨てる**（地域集計 `WO`/`QE`/`XF`/`QE-MER`、サブナショナル `US-CA`/`CN-RU`/`DE-*`、非 ISO `XI`/`ZZ`/`XE`）。旧国は ISO 3166-3（`SU`→`SUN`, `YU`→`YUG`, `DD`→`DDR`, `CS`/`XC`→`CSK`）、コソボ `KS`/`XK`→`XKX`（World Bank 流儀）。flag 付きで残す案は、mart の `iso3` キーの意味を崩すので採らなかった。
- **欠損**: `None` のまま。補完しない。
- **`data_quality`（0–5）の意味は WID 非公開**（`design/data-sources.md`）。本データの経験則（2026-10-04, H1b レポート）: **高いほど一次データに近い**（USA DINA 1962 年以降 = 5、SAU/JPN 資産の全年 = 0、DEU 資産は調査年 4・その間 0）。所得の observed 年は q3–5 のみだが、q3 以上でも imputed 年が多い。感度分析では「q ≤ 1（または 0）を落とす」向きで使う。旧記述「4〜5 は推計・外挿」は誤りだった（H1 レポートの該当変種は向きが逆、数値は据え置き・限界節に注記済み）。
- **OECD**: 対象は `oecd.OECD_MEMBERS` の 38 か国のみ（dataflow に含まれる集計・非加盟国は stage で捨てる）。raw は `data/raw/wealth-population-distribution/oecd/<indicator>.csv`（1 indicator 1 リクエスト、計 4）。`OBS_VALUE` 空は行ごと落とす。最高税率は SDMX に 2000 年以降しか無い（1981–1999 の Excel は robots.txt で Disallow のため使わない）。`--only <source>` は `Context.sources`（core）で実装、mart は無視する。
- 資産統計はソース・年代で定義が異なる。断絶の説明は `staged/wid/metadata` の `source_text`/`method` にある。
