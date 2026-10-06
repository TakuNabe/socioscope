# データソース方針

## ルール
- **本プロジェクトは非商用の研究目的に限る。** コードは MIT だが、派生データは出典ライセンスを継承する（例: WID.world は CC BY-NC-SA 4.0）。商用利用を検討する場合は NC 条件のソースを除外するか権利者に確認する。
- **公式 API / オープンデータ優先**。スクレイピングは利用規約・robots.txt を確認し、許される場合のみ。
- 採用したソースは下表に **ライセンス・取得方法・更新頻度** を記録する（`source-scout` エージェント / `/new-source`）。
- 取得物は必ず manifest（`data/raw/manifest.jsonl`）に URL・sha256・取得日時・ライセンスを残す。
- LLM で構造化する対象は「公開レポート本文・表の文章化された数値」など構造化 API のないものに限る。数値の一次ソースは可能な限り構造化 API から取る。

## 候補ソース（採用時に状態を更新）
| ソース | 内容 | 取得 | ライセンス（確認要） | 状態 |
|---|---|---|---|---|
| World Bank WDI API | GDP 成長率、出生率、人口、Gini 等（国×年） | REST JSON（`api.worldbank.org/v2`） | CC BY 4.0 | **採用**（growth-fertility） |
| World Inequality Database (WID.world) | 所得・資産の上位シェア、人口、長期系列 | 国別 zip（`bulk_download/WID_fulldataset_<ISO2>.zip`） | **CC BY-NC-SA 4.0**（サイト表記。CC BY 4.0 は未確認） | **採用**（wealth-population-distribution） |
| UN World Population Prospects | 人口・年齢構成・出生率 | CSV / API | CC BY 3.0 IGO | 候補 |
| OECD Data Explorer（SDMX REST） | 最高限界所得税率（Tax Database Table I.7）、公的社会支出 %GDP（SOCX）、税収 %GDP・相続税収 %GDP（Revenue Statistics）；家族支出 TP51（growth-fertility H5） | SDMX REST CSV（`sdmx.oecd.org/public/rest/data/...?format=csvfilewithlabels`、鍵不要） | **OECD Terms & Conditions（2024-07-01 改定）: 出典表示で商用含め自由利用。OECD 発行物は CC BY 4.0**（確認 2026-10-04） | **採用**（wealth-population-distribution H2 / growth-fertility H5） |
| Eurostat dissemination API（JSON-stat 2.0） | 2021 センサス 配偶関係×年齢×性×ISCED（`cens_21me_r2`）、母の年齢×出生順位の出生数（`demo_fordagec`）、女性人口（`demo_pjan`）、母の年齢×ISCED の出生数（`demo_faeduc`）、LFS 女性人口×ISCED（`lfsa_pgaed`） | REST JSON（`ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/<dataset>?format=JSON&lang=EN&<dim>=<code>`、キー不要、国別リクエスト） | **Eurostat copyright notice: 出典表示で商用含め再利用可**（第三国データは別条件、本件は EU/EFTA のみ。確認 2026-10-06） | **採用**（growth-fertility H5） |
| OECD Data Explorer（IDD 等） | 所得分配（IDD）、出生率 | SDMX API | 同上 | 候補 |
| Maddison Project / Penn World Table | 長期 GDP 系列 | Excel/CSV | 要確認 | 候補（戦後長期） |
| Our World in Data | 整形済み系列（出典明記） | CSV / grapher API | CC BY | 候補（検証用） |
| e-Stat（政府統計の総合窓口） | 国民生活基礎調査 所得票（所得階級×配偶者の有無・児童のいる世帯） | 統計表ファイル直接ダウンロード（`stat-search/file-download?statInfId=…&fileKind=1`、appId 不要） | **政府標準利用規約（第2.0版）＝CC BY 4.0 互換**（確認 2026-10-04） | **採用**（growth-fertility H3） |
| e-Stat — 就業構造基本調査（総務省） | 令和4年 全国編 第40表: 男女×配偶関係×年齢×所得（有業者） | 統計表ファイル直接ダウンロード（`…&fileKind=0`、**Excel のみ**、appId 不要。標準ライブラリで解析） | 同上（確認 2026-10-04） | **採用**（growth-fertility H3b 年齢調整） |
| DHS Program Indicator Data API | 調査前 3 年の TFR（15–49 歳）× 富裕五分位（`FE_FRTR_W_TFR` × Wealth quintile）、約 90 か国 1990–2025 の DHS/MIS/AIS 調査；国コード表（ISO3） | REST JSON（`api.dhsprogram.com/rest/dhs/data`, `/countries`、API キー不要） | **引用義務**（Terms: 「The DHS Program Indicator Data API, The Demographic and Health Surveys (DHS) Program. ICF. Originally funded by USAID. Available from api.dhsprogram.com. [Accessed 10-05-2026]」。確認 2026-10-05） | **採用**（growth-fertility H4） |
| 国家データ処（韓国）新婚夫婦統計 報道資料 PDF | 初婚新婚夫婦（婚姻 5 年以内）の所得区間（6 区間＋全体）× 子ども有無・人数・平均子ども数、2015–2024 年基準 | 報道資料掲示板の静的 PDF（`mods.go.kr/boardDownload.es?bid=11815&list_no=…&seq=…`、キー不要。pypdf でテキスト抽出し表をパース） | **公共ヌリ（KOGL）第 1 類型＝出典表示のみ・商用・改変可**（確認 2026-10-06） | **採用**（growth-fertility H5） |
| Testa (2012) *Family sizes in Europe* 付表（VID/ÖAW EDRP 2、データ＝Eurobarometer 75.4, 2011）＋ BiB (2025) *Intended, ideal and actual fertility in 11 European countries* Table 1（GGS-II 2020–23） | 理想・意図・実際の子ども数の国別平均と分布（EB: EU-27 × 性 × 年齢 15–24/25–39/40–54/55+/計、2011。GGS: 11 か国 × 女性 18–29/30–39/40–49/計、2020–23） | 静的 PDF（`oeaw.ac.at/.../edrp_2012_02.pdf`、`bib.bund.de/Publikation/2025/pdf/...`、キー不要。pypdf でテキスト抽出し付表をパース） | Testa 2012: **ライセンス未明示 → 出典明記で事実の転記のみ、PDF は再配布しない**（EB 75.4 自体は欧州委員会 CC BY 4.0）。BiB 2025: **CC BY-SA 4.0**（本文表記、確認 2026-10-06） | **採用**（growth-fertility H6） |
| Standard Eurobarometer（data.europa.eu）Volume A | 「今後 12 か月の期待（生活全般・家計・国の経済・国の雇用）」の国別 Better/Worse/Same/DK 割合、STD91（2019 春）〜STD105（2026 春）15 波 | hub API の JSON-LD（`data.europa.eu/api/hub/repo/datasets/<id>.jsonld`）から Volume A の静的 URL（`webgate.ec.europa.eu/ebsm/api/public/odp/download?key=…`、キー不要）を解決して xlsx/xls を取得 | **欧州委員会 再利用方針（Decision 2011/833/EU）＝CC BY 4.0 相当**（JSON-LD も `licence/CC_BY_4_0`。`commission.europa.eu/legal-notice_en`、確認 2026-10-06） | **採用**（growth-fertility H6） |
| 国立社会保障・人口問題研究所 | 出生動向基本調査、将来推計人口 | CSV/Excel | 要確認 | 候補（日本） |
| 国税庁 統計年報 / 民間給与実態統計 | 所得分布 | Excel | 政府標準利用規約 | 候補（日本） |
| 野村総研 富裕層レポート等 | 資産階層別世帯数（推計） | PDF（公開レポート） | 引用のみ | 候補（LLM 構造化対象） |

## 採用ソースの記録

### World Inequality Database (WID.world)
- URL / API:
  - 国別 zip: `https://wid.world/bulk_download/WID_fulldataset_<ISO2>.zip`（中身: `WID_data_<ISO2>.csv`, `WID_metadata_<ISO2>.csv`, `WID_countries.csv`, `README.md`）。日本 5.1MB、米国 7.2MB、フランス 9.0MB 程度。
  - 国別 CSV（非圧縮）: `https://wid.world/bulk_download/WID_data_<ISO2>.csv`（日本 35MB。圧縮 zip の方を使う）。
  - 全量 zip: `https://wid.world/bulk_download/wid_all_data.zip`（**882MB**、848 ファイル、展開 6.9GB。raw 予算 ~200MB を超えるため不採用）。
  - JSON API（`rfap9nitz6.execute-api.eu-west-1.amazonaws.com/prod/`）は R/Stata パッケージとサイト JS が使うが `x-api-key` 必須で公開ドキュメントなし。鍵をコードに埋めることになるため**使わない**。
  - robots.txt（2026-10-04）: `User-agent: * / Disallow:`（全許可）。
- 対象指標・粒度（国×年×百分位）:
  - `sptinc992j` 税引前国民所得シェア（成人・equal-split）: p0p50 / p50p90 / p90p100 / p99p100
  - `shweal992j` 個人純資産シェア（成人・equal-split）: 同上
  - `npopul999i` 総人口（全年齢・個人）: p0p100
  - 資本/所得比率 `wwealn999i` は bulk CSV に存在しなかった（日本で確認）ため今回は見送り。
  - bulk CSV のフォーマット: `;` 区切り、列 `country;variable;percentile;year;value;age;pop;data_quality`。`variable` 列は `sptincj992`（型+概念+人口単位+年齢）の順で、サイト表記 `sptinc992j` とは並びが異なる。stage で `sptinc992j` に正規化する。`data_quality`（0〜5、空あり）は staged に残す。
  - metadata CSV のフォーマット（**2026-10-04 に 46 か国の zip すべてで確認**）: `WID_metadata_<ISO2>.csv` は `;` 区切り 18 列 `country;variable;age;pop;countryname;shortname;simpledes;technicaldes;shorttype;longtype;shortpop;longpop;shortage;longage;unit;source;method;avg_quality`（zip 内 README は「seventeen variables」と書くが実ファイルには `avg_quality` が追加されている）。1 行 = 国×変数×age×pop（日本 2,073 行）。**`data_points` / `extrapolation` / `data_quality` / `quality_notes` といった列は存在しない**。年別の補間・外挿の情報は `method` の自由記述のみ（欧州 DINA 所得系列 26 か国: 「Summary of data construction by year (see source for details): 1980: extrapolated distribution, 1981-2005: survey + concept correction + tax data, 2006-2014: survey + tax data, 2015-2020: extrapolated distribution using survey data, …」。資産系列・米日等の所得系列: 「Before 1980, series is constructed based on the trend observed in the fiscal income data available (see sources).」「Before 1913, pretax income shares estimated based on methodology in long-run paper (see sources).」のみ）。`source` 列は `[URL][URL_LINK]…[/URL_LINK][URL_TEXT]…[/URL_TEXT][/URL]` 形式の文献リンク。stage は `staged/wid/metadata`（`source` を `source_text` に改名、`source` 列は来歴 `wid_world`）と `staged/wid/data_points`（年別 observed/partial/imputed/不明）に起こす。
  - `data_quality` / `avg_quality` の定義（調査 2026-10-04）: `wid.world/methodology/`、`wid.world/codes-dictionary/`、`wid.world/data-quality-score-world-map/`、zip 内 README のいずれにも定義なし。見つかった公式記述は R パッケージ `wid` 0.0.3 manual（CRAN, 2026-07-28）のみ: `data_quality` = "Observation-level data quality score. Since 2026, this score varies by country, series, and year."、`avg_quality` = "Country-series data quality score. It is a weighted average of data_quality over years, with greater weight on more recent observations."、`quality_filter` = "A single number is interpreted as a minimum data_quality"（高いほど良い向きを示唆）。旧 wid-r-tool の doc には "quality: Data quality (when applicable). The quality field is a score from 0 to 5 indicating the quality of the data." と "imputation: Type of estimate (when applicable). The imputation field is a short qualitative description of the type of estimate provided, which is strongly related to data quality."（`imputation` 列は bulk には無い）。API には `no_extrapolation`（"should interpolated/extrapolated years be included or not?"）引数があるが bulk zip には相当する列が無い。各レベル 0–5 の意味は非公開。World Inequality Lab Technical Note 2020/12（Inequality Transparency Index）はソースの品質を 5 点満点で採点するが（"We evaluate the quality of each data source out of 5 points… When considering data for which only tabulations are available, we give a maximum grade of 2.5. When microdata is considered, the maximum grade is 5."）、それが `data_quality` と同一かは確認できない。
- ライセンス・利用規約（確認日 2026-10-04）:
  - サイト各ページの `rel="license"` リンクは **CC BY-NC-SA 4.0**（`creativecommons.org/licenses/by-nc-sa/4.0/`）。ツールチップ文「Creative Commons Attribution 4.0」は HTML コメントアウトされており無効。`wid.world/terms-of-use/` は 404。zip 内 README にライセンス記載なし。World Inequality Report も CC BY-NC-SA 4.0。
  - 判定: **CC BY-NC-SA 4.0 として扱う**（出典表示・非営利・継承）。本リポジトリは非営利の研究用途で問題なし。WID 由来の staged/marts Parquet を再配布するときは出典（World Inequality Database, wid.world）と同ライセンスを明記する。raw はコミットしない（既定どおり）。CC BY 4.0 の明示が必要なら WID へ問い合わせ（人間ゲート）。
- 取得方法（adapter 名、レート制限）: `theme_wealth_population_distribution.wid`（純粋変換）＋ `pipeline.fetch`（`HttpxFetcher`）。OECD 38 ＋ 非 OECD G20 8 の 46 か国を 1 回ずつ逐次取得（合計 ~196MB）。公開レート制限なし。再取得は年 1 回程度（WID の年次更新時）。
- 既知の欠損・断絶・定義変更: 戦前は少数国のみ（日本の所得シェアは 1820/1850 以降に飛び飛び、資産シェアは 1820 から 56 年分）。`data_quality` は本データとの照合では**高いほど一次データに近い**（USA DINA 1962 年以降 = 5、SAU・JPN 資産の全年 = 0、DEU 資産は調査年 4・その間の補間年 0。metadata で observed と明示された所得の年は q3–5 のみ。ただし q3 以上にも imputed 年が多い）。旧記述「4〜5 は推計・外挿を含む」は誤り（2026-10-04 訂正、H1b レポート参照）。資産統計の定義は国で異なる（`staged/wid/metadata` の `source_text`/`method` 参照）。資産系列には年別の観測／推計の記述が無い（1980 年以前の trend 構築のみ）。ISO2→ISO3 は `wid_iso2_to_iso3.csv`（pycountry 由来・旧国コードは ISO 3166-3、コソボ KS→XKX）で決定的に変換し、地域集計（WO, QE, XF…）・サブナショナル（US-CA, CN-RU…）・非 ISO コード（XI, ZZ…）は捨てる。

### e-Stat（政府統計の総合窓口）— 国民生活基礎調査（厚生労働省）
- URL / API:
  - 統計表ファイル: `https://www.e-stat.go.jp/stat-search/file-download?statInfId=<12桁>&fileKind=1`（CSV, **CP932**。`fileKind=0`(Excel) は対象表では 404）。**アプリケーション ID 不要**。`statInfId` は公開表ごとに固定。
  - e-Stat API 3.0（`api.e-stat.go.jp/rest/3.0/...`）は全エンドポイントで appId 必須のため**使わない**（本リポジトリはアカウント登録しない）。将来必要になれば `ESTAT_APP_ID` 環境変数経由で fail-closed に実装する。
  - 表の所在: 国民生活基礎調査 → 各年 → 「所得・貯蓄」巻（一覧は `stat-search/files?...&tclass1=<巻>&cycle=7&cycle_facet=tclass1`）。
  - robots.txt（2026-10-04）: Drupal 既定（`/admin/`, `/search/`, `/user/*` 等のみ Disallow）。`/stat-search/file-download` は許可。
- 対象表・粒度（`theme_growth_fertility.estat.TABLES`）:
  | key | statInfId | 表 | 単位 |
  |---|---|---|---|
  | `hh_income_dist_ts` | 000040473361 | 令和7年 第002表 世帯数の相対度数分布，年次・所得金額階級別（1985–2024 所得年） | % |
  | `children_hh_income_dist_ts` | 000040473376 | 令和7年 第017表 児童のいる世帯数の相対度数分布，年次・所得金額階級別 | % |
  | `workers_marital_income_<2013,2016,2019,2022,2025>` | 000026222087 / 000031734158 / 000031957928 / 000040076501 / 000040473461 | 第102表 有業人員（15歳以上），勤めか自営かの別・**配偶者の有無・性・所得金額階級別**（大規模調査年） | 人員10万対 |
  | `hh_type_income_<同5波>` | 000026222010 / 000031734081 / 000031957851 / 000040076424 / 000040473384 | 第025表 世帯数，世帯類型－**児童のいる世帯**・所得金額階級別 | 世帯数1万対 |
- ライセンス・利用規約（確認日 2026-10-04, `https://www.e-stat.go.jp/terms-of-use`）: **政府標準利用規約（第2.0版）**。「クリエイティブ・コモンズ・ライセンスの表示 4.0 国際と互換性があり」と明記。出典表記必須（`出典：政府統計の総合窓口(e-Stat)`、加工した場合はその旨を記載）。商用利用可。API 利用には別規約があるが本実装は API を使わない。raw はコミットしない（既定どおり）。staged/marts を再配布するときは「出典：政府統計の総合窓口(e-Stat)、国民生活基礎調査（厚生労働省）を加工」を明記。
- 取得方法（adapter 名、レート制限）: `theme_growth_fertility.estat`（URL 組み立て・CSV→行の純粋変換）＋ `pipeline.fetch`（`HttpxFetcher`）。12 ファイル（計 ~80KB）を逐次取得。公開レート制限なし。再取得は年 1 回（7 月の公表後）。新しい大規模調査年（次は 2028）を足すときは `TABLES` に statInfId を追加する。
- 既知の欠損・断絶・定義変更:
  - **所得年と調査年**: 所得票は前年 1 年間の所得を聞く。年次推移表の列、および staged の `year` は**所得年**（`survey_year = year + 1`）。令和2年調査は中止（2019 所得が `…` → None）。平成6年は兵庫県、平成22年は岩手・宮城・福島、平成23年は福島、平成27年は熊本を除く。平成21年は定額給付金等の補完を含む。
  - **所得階級**: 世帯所得（万円）。年次推移表と第025表は 50 万円刻み（1000 万円以上は 100・300・500 万円刻み、2000 万円以上で打ち切り）。第102表は**有業者個人の所得**で 500 万円以上は 100 万円刻み、1000 万円以上で打ち切り、「所得なし」階級あり。`income_class_upper_yen` は上限なし階級で NULL。
  - **有配偶率の定義**: 第102表は「15 歳以上の有業人員」の配偶者の有無であり、無業者（専業主婦・学生・無職）を含まない。配偶者不詳は分母から外す（`denominator = 配偶者あり + 配偶者なし`）。年齢調整なし（所得は年齢と相関するため、年齢構成の差を含む粗い指標）。値は人員 10 万対の重みであり実数ではない。
  - **児童のいる世帯**: 18 歳未満の未婚の者がいる世帯。世帯所得階級別の「児童のいる世帯／全世帯」は子ども「数」ではなく有無の割合。母子世帯（2013 表では「母子世帯」列、他年は「高齢者世帯以外」の内訳）は別列で staged に保持。
  - 第025表のヘッダは年により複数行に分かれる（2013 年は「（再掲）児童のいる世帯」が 1 セル）。stage はヘッダ行を列ごとに連結して「児童のいる世帯」「母子世帯」「総数」を一意に特定し、見つからなければ fail-closed。

### e-Stat（政府統計の総合窓口）— 就業構造基本調査（総務省）令和4年 全国編 第40表（H3b 年齢調整用）
- URL / API:
  - 統計表ファイル: `https://www.e-stat.go.jp/stat-search/file-download?statInfId=000040077301&fileKind=0`（**Excel .xlsx 2.2MB**、1 シート、tidy 形式: 階層レベル／地域区分／男女／配偶関係／年齢／従業上の地位・雇用形態・起業の有無／所得 の列＋教育別の値列）。`fileKind=1`（CSV）は **404**。**アプリケーション ID 不要**。xlsx は `zipfile` ＋ `xml.etree`（標準ライブラリ）で読み、依存は追加しない。
  - 表の所在: 就業構造基本調査 → 令和4年（tstat=000001163626）→ 全国編（tclass1=000001163627）→ 人口・就業に関する統計表（tclass2=000001163628、271 表）。調査年月 2022 年 10 月、公開 2023-07-21。
  - e-Stat API 3.0（appId 必須）は引き続き使わない。この表はファイルで取得できたため `ESTAT_APP_ID` 経路は未実装。
- 調査結果（2026-10-04）: 国民生活基礎調査 令和7年「所得・貯蓄」234 表に 年齢×配偶者の有無×所得 のクロスは無い（配偶者の有無を持つのは第102表・第215表のみ）。就業構造基本調査 2022 年 全国編では第40表のみが 配偶関係×年齢×所得（有業者）を持つ。**2017 年（平成29年）・2012 年（平成24年）全国編に同等表は無い**（2017 年は非正規職員のみの第67表）。したがって 1 波のみ。
- 対象表・粒度（`theme_growth_fertility.estat.TABLES`、`TableKind.SHUGYO_MARITAL_AGE_INCOME`）:
  | key | statInfId | 表 | 単位 |
  |---|---|---|---|
  | `shugyo_marital_age_income_2022` | 000040077301 | 令和4年 第40表 男女、配偶関係、年齢、従業上の地位・雇用形態・起業の有無、所得（主な仕事からの年間収入・収益）、教育別人口（有業者）－全国 | 人（推定人数） |
- ライセンス・利用規約: e-Stat と同じ **政府標準利用規約（第2.0版）**（確認 2026-10-04）。出典表記「出典：政府統計の総合窓口(e-Stat)、就業構造基本調査（総務省）を加工」。raw はコミットしない。
- 取得方法（adapter 名、レート制限）: `theme_growth_fertility.estat`（`xlsx_rows` → `parse_shugyo_marital_age_income`）＋ `pipeline.fetch`（`HttpxFetcher`）。1 ファイル。raw は `data/raw/growth-fertility/estat_shugyo/`、staged は `staged/estat/shugyo_marital_age_income`（従業上の地位＝総数、教育＝総数の列のみ: 3 性 × 2 配偶関係 × 16 年齢 × 17 所得 = 1,632 行）、mart は `marts/jp_income_age_marital`（816 行）。
- 既知の欠損・断絶・定義変更:
  - **配偶関係は「総数」「うち未婚」のみ**。有配偶／死別・離別は公表されないため、mart の metric は `ever_married_share` = (総数 − 未婚) ÷ 総数（既婚経験率）。国民生活基礎調査の「配偶者あり」率とは定義が異なる。
  - **所得**は主な仕事からの年間収入・収益（調査前 1 年＝2021 年 10 月〜2022 年 9 月、名目）。staged/mart の `year` は**調査年 2022**（国民生活基礎調査の「所得年＝調査年−1」とは規則が異なる）。階級ラベル「50〜99万円」は 50 以上 100 未満として `income_class_upper_yen` = 100 万円に正規化（`parse_income_class_shugyo`）。「所得なし」階級は無く、所得不詳は総数にのみ含まれる（男性 2.4%、女性 4.3%）。
  - 年齢は 5 歳階級 15–19 〜 85 歳以上（`age_upper` は排他的上限、85 歳以上は NULL）。有業者 0 のセルは `'-'` → 0 → 比率 NULL（補完しない）。
  - 値は標本から復元した推定人数で、標準誤差は非公表。

### OECD Data Explorer（SDMX REST API）— 税制・社会支出（wealth-population-distribution H2）
- URL / API:
  - データ: `https://sdmx.oecd.org/public/rest/data/<agency>,<dataflow>,<version>/<key>?format=csvfilewithlabels`。**API キー不要**。`<key>` は dataflow の次元順に `.` 区切り（REF_AREA は空＝全国）。構造: `.../dataflow/<agency>/<dataflow>/<version>?references=all`、期間: `.../availableconstraint/<agency>,<dataflow>,<version>/all`。
  - 採用 dataflow（2026-10-04 に構造とデータ断片を取得して確認。ID は dataflow 一覧 `rest/dataflow/all` 1,549 件から特定）:
    | staged 名 | dataflow | key（REF_AREA を除く） | 期間 | 内容 |
    |---|---|---|---|---|
    | `top_pit_rate` | `OECD.CTP.TPS,DSD_TAX_PIT@DF_PIT_TOP_EARN_THRESH,1.0` | `.A._Z.TS_PIT.PT_WG_EARN_G.S13._Z._Z._Z._Z._Z._Z` | **2000–2025** | 最高限界個人所得税率（中央＋地方の合算、Tax Database Table I.7 の `TS_PIT`）、% |
    | `social_expenditure_gdp` | `OECD.ELS.SPD,DSD_SOCX_AGG@DF_SOCX_AGG,1.0` | `.A.SOCX.PT_B1GQ.ES10._T._T._Z` | 1980–2024 | 公的社会支出（現金＋現物、全プログラム）、%GDP |
    | `tax_revenue_gdp` | `OECD.CTP.TPS,DSD_REV_COMP_OECD@DF_RSOECD,2.0` | `.TAX_REV.S13._T._T.PT_B1GQ.A` | 1965–2024 | 一般政府 総税収、%GDP |
    | `inheritance_tax_rev_gdp` | 同上 | `.TAX_REV.S13.T_4300._T.PT_B1GQ.A` | 1965–2024 | 相続・遺産・贈与税収（4300）、%GDP。相続税「有無」の dataflow は SDMX に無いため税収ベースの代理 |
  - 当初候補の `DSD_TAX_WAGES_PIT@DF_TAX_PIT` / `DSD_TABLE_I7` / `DSD_SOCX_AGG@DF_SOCX_AGG`（これのみ一致）/ `DSD_REV@DF_REVOECD` は、`DF_SOCX_AGG` を除き存在しなかった。Revenue Statistics の国別 dataflow（`DSD_REV_OECD@DF_REV<ISO3>`）ではなく比較表 `DF_RSOECD` を使う（1 リクエストで全国）。
  - Table I.7 の 1981–1999 の歴史系列は oecd.org 上の Excel（`/content/dam/oecd/...`）にあるが、**robots.txt で `/content/dam/oecd/` が Disallow** のため取得しない。最高税率は 2000 年以降のみ。
  - robots.txt（2026-10-04）: `www.oecd.org` は `/content/dam/oecd/` と `/adobe/dynamicmedia/deliver/` のみ Disallow。`sdmx.oecd.org/robots.txt` は 404（制限なし）。
- 対象指標・粒度: 国（OECD 加盟 38 か国の ISO3）× 年。dataflow には集計（`OECD`, `OECD_REP`, `FEDOECD`, `UNIOECD`）や非加盟国（`BGR`, `HRV`, `PER`, `ROU`）も含まれるが、stage で `oecd.OECD_MEMBERS` の 38 か国に限定する。
- ライセンス・利用規約（確認日 2026-10-04、`https://www.oecd.org/en/about/terms-conditions.html`、「Last updated on 1 July 2024」）: **Data 節**「you can extract from, download, copy, adapt, print, distribute, share and embed Data for any purpose, even for commercial use」。条件は出典表示（`OECD (year), (dataset name), (data source) DOI or URL (accessed on (date))` 形式）と、再配布時に同じ出典表示義務を継承させること。「CC BY 4.0」の明示は **2024-07-01 以降に公表された OECD 著作物（Written Content）**に対するもので、データ節自体は上記の独自条件（実質 CC BY 相当）。第三者所有データが含まれ得る旨の注意あり（採用 3 dataflow は OECD 自身の統計）。API 節: 「as-is」、レート・量の制限を OECD が任意に課せる、最新版 API を使うこと。raw はコミットしない（既定どおり）。staged/marts の再配布時の出典表記: 「OECD (2026), OECD Tax Database / Social Expenditure Database (SOCX) / Revenue Statistics, https://sdmx.oecd.org (accessed on 2026-10-04)」。
- 取得方法（adapter 名、レート制限）: `theme_wealth_population_distribution.oecd`（URL 組み立て・CSV→行の純粋変換、Pydantic で STRUCTURE_ID と全次元コードを照合し fail-closed）＋ `pipeline._fetch_oecd` / `_stage_oecd`（`HttpxFetcher`）。**4 リクエスト（計 ~2.3MB）**。`socioscope run wealth-population-distribution fetch --only oecd` で WID の再取得を避けられる。公開レート制限なし（規約上 OECD が任意に制限可）。再取得は年 1 回程度。
- 既知の欠損・断絶・定義変更:
  - `top_pit_rate` は 2000 年以降のみ（上記）。H2 の 1980 起点の長期差分には使えない。
  - `social_expenditure_gdp` は 1980 年時点で 23 か国。遅れて始まる国: MEX 1985, CHL 1986, CZE/ISL/KOR/POL 1990, LVA 1994, ISR/SVK/SVN 1995, LTU 1996, EST/HUN 1999, COL 2010, CRI 2011。2023 以降は暫定で欠損あり。
  - `tax_revenue_gdp` / `inheritance_tax_rev_gdp` は 1980 年時点で 26 か国。遅れて始まる国: CHL/COL/CRI 1990, HUN/POL 1991, CZE 1993, EST/ISR/LTU/LVA/SVK/SVN 1995。
  - `OBS_VALUE` 空（`OBS_STATUS` M/L 等）は行ごと落とす（補完しない）。staged に `obs_status` 列を残す。
  - 最高税率は賃金所得に対する法定税率で、資本所得・配当の税率ではない。社会支出・税収は GDP 比で、GDP 改定の影響を受ける。

### DHS Program Indicator Data API（growth-fertility H4: 国内の富裕五分位別 TFR）
- URL / API:
  - データ: `https://api.dhsprogram.com/rest/dhs/data?indicatorIds=FE_FRTR_W_TFR&breakdown=all&characteristicCategory=Wealth%20quintile&perpage=5000&f=json`（1 ページ、2026-10-05 時点 1,565 レコード = 313 調査 × 5 五分位）。レスポンスは JSON オブジェクト `{TotalPages, RecordCount, RecordsReturned, Page, Data[]}`。`Data` の主フィールド: `Value`(数値), `DHS_CountryCode`, `CountryName`, `SurveyYear`(int), `SurveyId`(例 `AF2015DHS`), `IndicatorId`, `CharacteristicCategory`, `CharacteristicLabel`(Lowest/Second/Middle/Fourth/Highest), `SurveyType`(DHS/MIS/AIS), `CILow`/`CIHigh`/`DenominatorWeighted`(**文字列**、この指標では空)。
  - 国コード: `https://api.dhsprogram.com/rest/dhs/countries?f=json&perpage=300`（92 件。`DHS_CountryCode` → `ISO3_CountryCode`。`OS`＝Nigeria (Ondo State) は ISO3 空）。
  - API キー不要。`TotalPages != 1` や `RecordCount != len(Data)` は `ValueError`（fail-closed）。
- 対象指標・粒度: 調査（国 × 調査年 × 調査種別）× 富裕五分位 1..5。富裕五分位は**資産指数による国内の相対順位**で所得額ではない。TFR は調査前 3 年の 15–49 歳女性ベース。
- ライセンス・利用規約（確認日 2026-10-05、`https://api.dhsprogram.com/#/terms.cfm`）: 利用は自由だが**引用必須**: 「The DHS Program Indicator Data API, The Demographic and Health Surveys (DHS) Program. ICF. Originally funded by the United States Agency for International Development (USAID). Available from api.dhsprogram.com. [Accessed 10-05-2026]」。`theme_growth_fertility.dhs.LICENSE` に記載し manifest に残す。raw はコミットしない。
- 取得方法（adapter 名、レート制限）: `theme_growth_fertility.dhs`（URL 組み立て・`iso3_map`・`rows_from_response`・`unmapped_codes` の純粋変換、Pydantic `extra="ignore"`）＋ `pipeline.fetch` / `pipeline._stage_dhs`（`HttpxFetcher`）。**2 リクエスト**。raw は `data/raw/growth-fertility/dhs_api/{dhs_tfr_wealth,dhs_countries}.json`、staged は `staged/dhs/tfr_by_wealth_quintile`（countries raw が無ければ fail-closed）、mart は `marts/dhs_tfr_by_wealth_quintile`（staged をそのまま `survey_year, iso3, quintile` でソート）。公開レート制限なし。
- 既知の欠損・断絶・定義変更:
  - ISO3 の付かない DHS 国コード（サブナショナル調査 `OS` 等）の行は落とし、stage の skipped に残す。
  - `CILow`/`CIHigh`/`DenominatorWeighted` はこの指標では全件空（None）。列は保持する。
  - 対象国は低・中所得国に偏る（高所得国の国内勾配は観測できない）。同一国の複数調査は調査種別（DHS/MIS/AIS）が混在する。

### Eurostat dissemination API（JSON-stat 2.0）— 欧州の学歴別 有配偶率・出生順位別／学歴別 TFR（growth-fertility H5）
- URL / API: `https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/<dataset>?format=JSON&lang=EN&geo=<geo>&<dim>=<code>…`（同一次元の複数値は引数を繰り返す。`sinceTimePeriod=<year>` で開始年）。**API キー不要**。レスポンスは JSON-stat 2.0（`class: "dataset"`, `id`（次元順）, `size`, `dimension.<d>.category.index`（code→位置）, `value` は**疎な dict（文字列セル番号→値）**、`status` に欠損フラグ）。エラーは `{"error": …}` の JSON。`theme_growth_fertility.eurostat.jsonstat_rows` が各セルを次元コード dict に展開し、`value` に無いセルは出さない（補完しない）。`error` / `class != dataset` / `id`・`size`・`value` 欠落 / 次元サイズ不一致は `ValueError`（fail-closed）。
- 採用 dataset（2026-10-06 に実レスポンスで次元コードを確認）。すべて国別に 1 リクエスト（raw `eurostat_<dataset>_<geo>.json`）:
  | dataset | 次元（`id` 順） | 絞り込み | 対象国 | 年 |
  |---|---|---|---|---|
  | `cens_21me_r2` | freq.isced11.marsta.age.sex.unit.geo.time | sex=M,F; age=Y25-29…Y55-59（7 階級）; marsta=TOTAL,MAR_REP,UNK; isced11 全部（TOTAL, ED0…ED8, NAP, UNK） | EU27＋EFTA（IS NO CH LI）の 31 か国。geo は 2 文字の国コードのみ採用（NUTS 行は落とす） | 2021 |
  | `demo_fordagec` | freq.unit.age.ord_brth.geo.time | age=Y15…Y49（1 歳刻み 35 本）＋UNK; ord_brth 全部（TOTAL,1,2,3,GE4,UNK） | FI SE NO DK IS DE FR IT ES NL HU CZ PL | 2005– |
  | `demo_pjan` | freq.unit.age.sex.geo.time | sex=F; age=Y15…Y49 | 同上 | 2005– |
  | `demo_faeduc` | freq.unit.age.isced11.geo.time | age=1 歳刻み Y15…Y49 ＋ 5 歳階級 Y15-19…Y45-49 ＋ UNK（国により片方しか無い。FI は 1 歳刻みのみ）; isced11 全部（TOTAL, ED0-2, ED3_4, ED5-8, NAP, UNK） | FI SE NO DK IS NL BE AT | 2007– |
  | `lfsa_pgaed` | freq.unit.sex.age.isced11.geo.time | sex=F; age=Y15-19…Y45-49; isced11=ED0-2,ED3_4,ED5-8,TOTAL（単位 THS_PER＝千人） | 同上 | 2007– |
- geo → ISO3 は固定辞書 `eurostat.GEO_TO_ISO3`（EU27＋EFTA＋UK。`EL`→GRC、`UK`→GBR）。pycountry は使わない。
- ライセンス・利用規約（確認日 2026-10-06、`https://ec.europa.eu/eurostat/web/main/help/copyright-notice`）: Eurostat のデータは出典を明記すれば商用を含め自由に再利用・改変・配布できる（Commission Decision 2011/833/EU）。第三国（非 EU/EFTA）データは権利者の条件が別だが、本件は EU/EFTA のみ。出典表記: 「Source: Eurostat, <dataset>（accessed 2026-10-06）」。raw はコミットしない。
- 取得方法: `theme_growth_fertility.eurostat`（`Request` の URL 組み立て、`jsonstat_rows`、`census_rows` 等の純粋変換、`build_census_mart` / `build_tfr_by_order` / `build_tfr_by_education` の純粋集計）＋ `pipeline._fetch_h5` / `_stage_h5` / `_mart_h5`（`HttpxFetcher`）。**73 リクエスト**（31 ＋ 13×2 ＋ 8×2、各 10KB〜数百 KB）。公開レート制限なし（Eurostat は 1 リクエストあたりセル数上限あり → 国別分割）。再取得は年 1 回程度。
- 既知の欠損・断絶・定義変更:
  - センサスの配偶関係は法律婚＋登録パートナー（`MAR_REP`）のみで同棲を含まない（北欧の有配偶率を過小評価）。学歴 UNK/NAP は群に入れない。`total` は TOTAL − 配偶関係 UNK。
  - `demo_fordagec` の出生順位 UNK は TFR の順位別分解に含めず別行（`order="UNK"`）で保持。母の年齢 UNK の出生は TFR から落とし `births_age_unknown` に件数を残す。
  - `demo_faeduc` は国により 1 歳刻みと 5 歳階級の公開が異なる。mart では 5 歳階級セルが無ければ 1 歳刻み 5 本の合計を使う（5 本そろわなければ落とす）。
  - `lfsa_pgaed` は標本（LFS）由来で小さいセルは非公表（`value` 欠落、`status: u/b`）。分母が無く出生 > 0 の階級がある年・学歴群は落とす（補完しない）。出生 0 の階級は分母が無くても寄与 0。
  - 出生の 2024 年値は国により未公表。学歴別出生（`demo_faeduc`）は提供国が限られる（北欧以外は試行取得し、データがあれば残す）。
### 国家データ処（韓国）— 신혼부부통계（新婚夫婦統計）報道資料 PDF（growth-fertility H5: 韓国の所得区間別 有子率）
- URL / API:
  - 掲示板: `https://mods.go.kr/board.es?mid=a10301010000&bid=11815`（報道資料。検索語「신혼부부」で各年の「<year>년 (기준) 신혼부부통계 결과」投稿を特定。2026-10-06 時点の `list_no`/`seq`（pdf 添付）は `theme_growth_fertility.kostat.RELEASES` に固定）:
    | 基準年 | URL |
    |---|---|
    | 2015 | `https://mods.go.kr/boardDownload.es?bid=11815&list_no=358364&seq=5` |
    | 2016 | `…list_no=365445&seq=15` |
    | 2017 | `…list_no=371980&seq=2` |
    | 2018 | `…list_no=379256&seq=10` |
    | 2019 | `…list_no=386554&seq=2` |
    | 2020 | `…list_no=415466&seq=2` |
    | 2021 | `…list_no=422173&seq=1` |
    | 2022 | `…list_no=428407&seq=3` |
    | 2023 | `…list_no=434122&seq=3` |
    | 2024 | `…list_no=442387&seq=3` |
  - KOSIS OpenAPI はキー必須のため使わない。PDF は静的 URL、キー不要、各 1.5–3.7 MB。robots.txt（`https://mods.go.kr/robots.txt`、2026-10-06）: `User-agent: *` は `/ksows/wisenut/` のみ Disallow、Googlebot 向けに `/board.es?mid=b20306000000&bid=601` を Disallow。`boardDownload.es` と当該掲示板は許可。
- 対象指標・粒度: 基準年 × 所得区間（전체 / 1천만원 미만 / 1천만~3천만 / 3천만~5천만 / 5천만~7천만 / 7천만~1억 / 1억원 이상。万ウォン単位の下限・上限に変換、上限なしは NULL）。値: 부부 수（쌍）, 자녀있음 %, 1명 %, 2명 %, 3명 이상 %, 평균 자녀 수。**母集団**: 基準年 11 月 1 日時点で婚姻 5 年以内・婚姻継続中・両者国内居住の**初婚**夫婦（`population = first_marriage_within_5y`）。**所得概念**: 夫婦合算の年間 근로＋사업소득（`income_concept = earned_business`）。**2015 年基準の断絶**: 2015 年基準報道資料は健康保険職場加入者の**賃金勤労者**夫婦（852,618 쌍）のみを所得区間別に集計 → `income_concept = wage_only`。2016 年基準資料が 2015 年を 근로＋사업소득 ベース（1,179,000 쌍）で再掲しているため、2015 年は両概念の行が存在する。各資料は前年も再掲するので、mart では (ref_year, income_concept) ごとに**最新の資料**を採用する。
- ライセンス・利用規約（確認日 2026-10-06、`https://mods.go.kr/menu.es?mid=a10706000000` 저작권정책）: 報道資料は **공공누리（KOGL）제1유형（출처표시）**（`https://www.kogl.or.kr/info/license.do`）。出典表示のみで商用・改変可。出典表記: 「국가데이터처, 신혼부부통계（<year>년 기준）, 보도자료, mods.go.kr」。`kostat.LICENSE` に記載し manifest に残す。raw（PDF）はコミットしない。
- 取得方法（adapter 名、レート制限）: `theme_growth_fertility.kostat`（`RELEASES`、`pdf_text`（pypdf）、`find_income_children_table`、`income_children_rows` の純粋変換）＋ `pipeline._fetch_kostat` / `_stage_kostat` / `_mart_kostat`（`HttpxFetcher`）。**10 リクエスト（計 ~22 MB）**。raw は `data/raw/growth-fertility/kostat_newlywed/newlywed_<ref_year>.pdf`、staged は `staged/kostat/newlywed_income_children`、mart は `marts/kr_newlywed_income_children`。公開レート制限なし。再取得は年 1 回（12 月の公表後）。
- 既知の欠損・断絶・定義変更:
  - 表のレイアウトは 3 系統（2015: 行＝所得区間・実数＋構成比、2016–2019: 行＝所得区間・構成比＋千쌍、2020–2024: 列＝所得区間・年ブロック）。`kostat.py` はこの 3 系統のみ解析し、見出し・行数・合計（区間の合計＝全体、자녀없음＋자녀있음＝100、1명＋2명＋3명 이상＝자녀있음）が合わないときは `ValueError` → stage の skipped に「`newlywed_<year>.pdf: layout not recognised (<reason>)`」として残す（補完しない）。
  - 2016–2020 年基準資料の 부부 수 は**千쌍単位**（2016–2018 は小数 1 桁、2019–2020 は整数）→ ×1000 で쌍に換算。2021 年以降と 2015 年は実数。最新資料優先のため、mart で千쌍由来なのは 2015（earned_business）・2016・2017・2018 年の行のみ。
  - 共稼ぎ（맞벌이）別・婚姻年次別の平均子ども数は資料にあるが未取込（任意項目）。所得は夫婦合算で、共稼ぎと所得が同時決定（`design/themes/growth-fertility.md` H5 の限界）。
  - 2018 年基準 PDF は本文フォントが抽出で文字化けするが、表部分は正常に抽出される。

### Testa (2012) / Eurobarometer 75.4 と BiB (2025) / GGS-II — 理想・意図・実際の子ども数（growth-fertility H6）
- URL / API:
  - Testa, M.R. (2012) *Family sizes in Europe: evidence from the 2011 Eurobarometer survey*. VID European Demographic Research Paper 2: `https://www.oeaw.ac.at/fileadmin/subsites/Institute/VID/PDF/Publications/EDRP/edrp_2012_02.pdf`（100 ページ、~1 MB）。付表 A.1.1（低/高の個人理想、両性、15–39 歳・55 歳以上）、A.2.1–A.2.4（一般理想・個人理想・実際・追加意図の平均、国 × 性 × 年齢 15–24/25–39/40–54/55+/Total）、A.2.5–A.2.8（同じ 4 指標の分布 0/1/2/3+/[理想なし]/DK と N）。
  - Bundesinstitut für Bevölkerungsforschung (2025) *Intended, ideal and actual fertility in 11 European countries: Evidence on fertility gaps in different age groups from the Generations and Gender Survey*, BiB Working Paper: `https://www.bib.bund.de/Publikation/2025/pdf/Intended-ideal-and-actual-fertility-in-11-European-countries-Evidence-on-fertility-gaps-in-different-age-groups-from-the-Generations-and-Gender-Survey.pdf?__blob=publicationFile&v=2`（31 ページ、~1.8 MB）。Table 1（p. 14）: DE AT NL CZ HR EE NO DK FI MD UK × 年齢（18–29/30–39/40–49/Total）× {意図−実際, 理想−実際, 理想−意図 のギャップ, 実際, 意図（合計）, 個人理想 の平均} ＋ Observations、注記に国別の調査年（GGS-II DE 2021–22, AT 2022–23, NL 2022–23, CZ 2020–22, HR 2023, EE 2021–22, NO 2020, DK 2021, FI 2021–22, MD 2020, UK 2022–23）。
  - マイクロデータ（GESIS EB、GGP、ESS、EVS）は登録制のため使わない。
- 対象指標・粒度: `marts/eu_fertility_ideals`（long）。EB2011: iso3（EU-27、ドイツは全体行。東西別・EU-27 行は落とす）× sex（F/M、A.1.1 のみ T）× age_class × metric[`ideal_general_mean` / `ideal_personal_mean` / `actual_mean` / `intended_additional_mean` / `ideal_zero_share`（個人理想 0 の %）/ `ideal_low_share`（0＋1 の %）/ `ideal_high_share`（3+ の %）/ `ideal_general_zero_share` / `childless_share` / `intended_additional_zero_share`]、分布由来の行には N。GGS2020: iso3 × F × age_class × metric[`actual_mean` / `intended_total_mean` / `ideal_personal_mean` / `gap_intended_actual` / `gap_ideal_actual` / `gap_ideal_intended`]、Total 行に N、`survey_year` は調査開始年。割合は**%**（出典のまま）。
- ライセンス・利用規約（確認日 2026-10-06）: Testa 2012 は VID/ÖAW のワーキングペーパーでライセンス未明示 → 事実（数値）を出典明記で転記するに留め、PDF は再配布しない（raw は gitignore）。基データの Eurobarometer 75.4 は欧州委員会（CC BY 4.0）。BiB 2025 は本文に CC BY-SA 4.0 の表記あり（p. 2）。両者の文言は `surveys.TESTA_LICENSE` / `surveys.BIB_LICENSE` に記載し manifest に残す。出典表記: 「Testa, M.R. (2012) Family sizes in Europe: evidence from the 2011 Eurobarometer survey. VID EDRP 2（data: Eurobarometer 75.4, European Commission）」「BiB (2025) Intended, ideal and actual fertility in 11 European countries, BiB Working Paper（data: GGS-II, CC BY-SA 4.0）」。
- 取得方法（adapter 名、レート制限）: `theme_growth_fertility.surveys`（`eb2011_rows` / `ggs_rows` / `build_ideals_mart` の純粋変換、pypdf）＋ `pipeline._fetch_h6` / `_stage_h6` / `_mart_h6`。2 リクエスト。raw は `data/raw/growth-fertility/testa2012_eb75_4/testa2012_edrp_2012_02.pdf`、`.../bib2025_ggs2/bib2025_ggs2_fertility_gaps.pdf`。staged は `staged/surveys/eb2011_ideals`、`staged/surveys/ggs2020_ideals`。再取得不要（固定文書）。
- 既知の欠損・断絶・定義変更:
  - pypdf の抽出で数値内に空白が入る（「2. 07」）→ 正規化。「United Kingdom」が「United」に、「Czech Rep.」が「Czech」に切れることがある → 別名で補う。分布表の 4 行（A.2.6 イタリア男性 15–24、A.2.8 マルタ 3 ブロック）は数字が混線して読めないため**行を落とし** stage の skipped に「garbled row」として残す（推定しない）。平均表は 27 か国 × 10 列がそろわなければ `ValueError`（fail-closed）。
  - EB の「追加意図」（additionally intended）と GGS の「意図（合計）」（intended total）は定義が異なる。EB の理想は 15 歳以上全体、GGS は女性 18–49。質問文・母集団が異なるため**水準の比較はできない**（H6 の仮定を参照）。
  - A.1.1 は両性合計で年齢 15–39/55+ のみ、N なし。GGS の N は国合計のみ（年齢別 N は非掲載）。

### Standard Eurobarometer（data.europa.eu）— 今後 12 か月の期待（growth-fertility H6）
- URL / API:
  - データセット記録（JSON-LD）: `https://data.europa.eu/api/hub/repo/datasets/<dataset_id>.jsonld`。配布物 `dcat:Distribution` の `dct:title`（"Link to <file>"）で Volume A（`vol(ume)?_A`、AA/AP/AAP/B/C は除外）を選び `dcat:accessURL`（`https://webgate.ec.europa.eu/{ebsm,eurobarometer}/api/public/odp/download?key=<32 hex>`）を取得する。dataset_id は hub 検索 API（`https://data.europa.eu/api/hub/search/search?q=Standard%20Eurobarometer&limit=100`、2026-10-06）で特定し `theme_growth_fertility.eurobarometer.WAVES` に固定（取得時に検索はしない）:
    | 波 | dataset_id | 調査時期（season / fieldwork 開始月） | Volume A の形式 |
    |---|---|---|---|
    | STD91 | `s2253_91_5_std91_eng` | 2019 H1 / 2019-06 | zip（.xls） |
    | STD92 | `s2255_92_3_std92_eng` | 2019 H2 / 2019-11 | zip（.xls、EU27＋UK のみ。候補国は別ファイル、未取込） |
    | STD93 | `s2262_93_1_93_1_eng` | 2020 H1 / 2020-07 | zip（.xlsx） |
    | STD94 | `s2355_94_1_std94_eng` | 2020 H2 / 2021-02（Winter 2020–21） | .xlsx |
    | STD95 | `s2532_95_3_95_eng` | 2021 H1 / 2021-06 | .xlsx |
    | STD96 | `s2553_96_3_std96_eng` | 2021 H2 / 2022-01（Winter 2021–22） | .xlsx |
    | STD97 | `s2693_97_5_std97_eng` | 2022 H1 / 2022-06 | .xlsx |
    | STD98 | `s2872_98_2_std98_eng` | 2022 H2 / 2023-01（Winter 2022–23） | .xlsx |
    | STD99 | `s3052_99_4_std99_eng` | 2023 H1 / 2023-05 | .xlsx |
    | STD100 | `s3053_100_2_std100_eng` | 2023 H2 / 2023-10 | .xlsx |
    | STD101 | `s3216_101_3_std101_eng` | 2024 H1 / 2024-04 | .xlsx |
    | STD102 | `s3215_102_2_std102_eng` | 2024 H2 / 2024-10 | .xlsx |
    | STD103 | `s3372_103_3_std103_eng` | 2025 H1 / 2025-03 | .xlsx |
    | STD104 | `s3378_104_1_std104_eng` | 2025 H2 / 2025-10 | .xlsx |
    | STD105 | `s3613_105_2_std105_eng` | 2026 H1 / 2026-03 | .xlsx |
  - 2019 春以降で欠けている波はない（2026-10-06）。STD90 以前（2018 年秋まで）は data.europa.eu にあるが未取込（H6 の窓は 2019–）。
- 対象指標・粒度: `marts/eu_expectations`: iso3 × wave × item[`life_general`（Your life in general）/ `household_finance`（The financial situation of your household）/ `national_economy`（The economic situation in (OUR COUNTRY)、STD100 は "The state of (OUR COUNTRY)'s economy"）/ `employment_situation`（The employment situation in (OUR COUNTRY)）] の `better_share` / `worse_share` / `same_share` / `dk_share`（**%**、加重）と `net_optimism = better − worse`。`fieldwork_year`/`fieldwork_half` は波の season（春・夏＝1、秋・冬＝2、冬の波は前年に帰属）で波ごとに一意、`fieldwork_start` は実際のフィールドワーク開始月（YYYY-MM）。国は EU27 ＋ UK・候補国・EFTA 等（波により 28–37 か国）。EU27 集計、D-W/D-E（DE を使う）、XK、CY(tcc) は落とす。
- ライセンス・利用規約（確認日 2026-10-06）: 欧州委員会の再利用方針（Commission Decision 2011/833/EU、`https://commission.europa.eu/legal-notice_en`）＝CC BY 4.0 相当。JSON-LD の `dct:license` も `licence/CC_BY_4_0`。出典表記: 「European Commission, Standard Eurobarometer <wave>, Volume A（data.europa.eu）」。
- 取得方法（adapter 名、レート制限）: `theme_growth_fertility.eurobarometer`（`WAVES`、`vol_a`（JSON-LD → 配布物）、`workbook_sheets`（zip / xlsx=openpyxl read-only / xls=xlrd）、`expectation_rows`、`build_expectations_mart`）＋ `pipeline._fetch_h6` / `_stage_h6` / `_mart_h6`。**30 リクエスト**（JSON-LD 15 ＋ Volume A 15、各 0.4–1 MB、計 ~14 MB）。raw は `data/raw/growth-fertility/eurobarometer_std/eb_<code>_meta.json` と `eb_<code>_vol_a.<zip|xlsx>`。staged は `staged/eurobarometer/expectations`。新しい波は hub 検索で dataset_id を確認して `WAVES` に追加する。
- 既知の欠損・断絶・定義変更:
  - シートは質問文（"expectations for the next twelve/12 months"）で探し、英語の項目名で 4 項目に限定する（「国の状況全般」「個人の仕事」「EU の経済」は未取込）。見つからない波は skipped。レイアウト差: STD91–92 は .xls（見出しに "<<Back to content" なし、ラベル TOTAL/DK）、STD93 は仏英ラベルが 1 セル（"Meilleurs\nBetter"）で割合が次行、STD93/STD91 は CY(tcc) 専用シートを別に持つ（国列なしとして無視）。想定外の構造（国見出しなし、回答行欠落、割合が 0–1 でない）は `ValueError` → skipped。
  - STD92 の Volume A 本体は EU27＋UK のみ（候補国は "with CC" ファイル、未取込）。STD100 は 35 か国（CH/NO/IS なし等、波により調査対象国が変わる）。
  - 「−」は回答者 0 を意味し 0 として扱う。割合は Volume A の四捨五入済み整数 %（ごく一部は小数）。
  - 質問は「今後 12 か月の期待」であり不確実性の分散ではない（H6 の限界）。

## 記録テンプレート（ソース採用時）
```
### <ソース名>
- URL / API:
- 対象指標・粒度（国×年 など）:
- ライセンス・利用規約（確認日）:
- 取得方法（adapter 名、レート制限）:
- 既知の欠損・断絶・定義変更:
```
