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
| World Inequality Database (WID.world) | 所得・資産の上位シェア、長期系列 | CSV ダウンロード / R パッケージ | CC BY 4.0 | 候補（wealth） |
| UN World Population Prospects | 人口・年齢構成・出生率 | CSV / API | CC BY 3.0 IGO | 候補 |
| OECD Data Explorer | 所得分配（IDD）、出生率 | SDMX API | OECD 利用規約 | 候補 |
| Maddison Project / Penn World Table | 長期 GDP 系列 | Excel/CSV | 要確認 | 候補（戦後長期） |
| Our World in Data | 整形済み系列（出典明記） | CSV / grapher API | CC BY | 候補（検証用） |
| e-Stat（政府統計の総合窓口） | 人口動態統計・国民生活基礎調査・全国家計構造調査 | API（アプリ ID 要） | 政府標準利用規約 2.0 | 候補（日本） |
| 国立社会保障・人口問題研究所 | 出生動向基本調査、将来推計人口 | CSV/Excel | 要確認 | 候補（日本） |
| 国税庁 統計年報 / 民間給与実態統計 | 所得分布 | Excel | 政府標準利用規約 | 候補（日本） |
| 野村総研 富裕層レポート等 | 資産階層別世帯数（推計） | PDF（公開レポート） | 引用のみ | 候補（LLM 構造化対象） |

## 記録テンプレート（ソース採用時）
```
### <ソース名>
- URL / API:
- 対象指標・粒度（国×年 など）:
- ライセンス・利用規約（確認日）:
- 取得方法（adapter 名、レート制限）:
- 既知の欠損・断絶・定義変更:
```
