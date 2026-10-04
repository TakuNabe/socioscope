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
| OECD Data Explorer | 所得分配（IDD）、出生率 | SDMX API | OECD 利用規約 | 候補 |
| Maddison Project / Penn World Table | 長期 GDP 系列 | Excel/CSV | 要確認 | 候補（戦後長期） |
| Our World in Data | 整形済み系列（出典明記） | CSV / grapher API | CC BY | 候補（検証用） |
| e-Stat（政府統計の総合窓口） | 国民生活基礎調査 所得票（所得階級×配偶者の有無・児童のいる世帯） | 統計表ファイル直接ダウンロード（`stat-search/file-download?statInfId=…&fileKind=1`、appId 不要） | **政府標準利用規約（第2.0版）＝CC BY 4.0 互換**（確認 2026-10-04） | **採用**（growth-fertility H3） |
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
- ライセンス・利用規約（確認日 2026-10-04）:
  - サイト各ページの `rel="license"` リンクは **CC BY-NC-SA 4.0**（`creativecommons.org/licenses/by-nc-sa/4.0/`）。ツールチップ文「Creative Commons Attribution 4.0」は HTML コメントアウトされており無効。`wid.world/terms-of-use/` は 404。zip 内 README にライセンス記載なし。World Inequality Report も CC BY-NC-SA 4.0。
  - 判定: **CC BY-NC-SA 4.0 として扱う**（出典表示・非営利・継承）。本リポジトリは非営利の研究用途で問題なし。WID 由来の staged/marts Parquet を再配布するときは出典（World Inequality Database, wid.world）と同ライセンスを明記する。raw はコミットしない（既定どおり）。CC BY 4.0 の明示が必要なら WID へ問い合わせ（人間ゲート）。
- 取得方法（adapter 名、レート制限）: `theme_wealth_population_distribution.wid`（純粋変換）＋ `pipeline.fetch`（`HttpxFetcher`）。OECD 38 ＋ 非 OECD G20 8 の 46 か国を 1 回ずつ逐次取得（合計 ~196MB）。公開レート制限なし。再取得は年 1 回程度（WID の年次更新時）。
- 既知の欠損・断絶・定義変更: 戦前は少数国のみ（日本の所得シェアは 1820/1850 以降に飛び飛び、資産シェアは 1820 から 56 年分）。`data_quality` 4〜5 は推計・外挿を含む。資産統計の定義は国で異なる（metadata の `source`/`method` 列参照、今回は staged に含めず raw に保持）。ISO2→ISO3 は `wid_iso2_to_iso3.csv`（pycountry 由来・旧国コードは ISO 3166-3、コソボ KS→XKX）で決定的に変換し、地域集計（WO, QE, XF…）・サブナショナル（US-CA, CN-RU…）・非 ISO コード（XI, ZZ…）は捨てる。

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

## 記録テンプレート（ソース採用時）
```
### <ソース名>
- URL / API:
- 対象指標・粒度（国×年 など）:
- ライセンス・利用規約（確認日）:
- 取得方法（adapter 名、レート制限）:
- 既知の欠損・断絶・定義変更:
```
