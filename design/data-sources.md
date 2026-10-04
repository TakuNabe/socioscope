# データソース方針

## ルール
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
| e-Stat（政府統計の総合窓口） | 人口動態統計・国民生活基礎調査・全国家計構造調査 | API（アプリ ID 要） | 政府標準利用規約 2.0 | 候補（日本） |
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

## 記録テンプレート（ソース採用時）
```
### <ソース名>
- URL / API:
- 対象指標・粒度（国×年 など）:
- ライセンス・利用規約（確認日）:
- 取得方法（adapter 名、レート制限）:
- 既知の欠損・断絶・定義変更:
```
