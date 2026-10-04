# data/

| ディレクトリ | git | 内容 |
|---|---|---|
| `raw/` | **管理しない**（manifest のみ） | 取得したままの生データ。`manifest.jsonl` に URL・sha256・取得日時・ライセンスを記録。`socioscope run <theme> fetch` で再取得。 |
| `staged/<domain>/` | 管理する | 正規化済み Parquet。共通キー: `iso3`, `year`。1 ソース 1 ファイルを基本に。 |
| `marts/` | 管理する | テーマ別の分析用テーブル（`<theme>_<name>.parquet`）。 |
| `llm_cache/` | 管理する | LLM 構造化の結果（JSONL, ADR 0003）。 |
| `socioscope.duckdb` | 管理しない | `socioscope db build` で `staged.*`/`marts.*` view を再生成。 |

詳細: `docs/adrs/0002-parquet-as-source-of-truth-duckdb-as-derived.md`

## データのライセンス
Parquet はコード（MIT）とは別に、出典のライセンスを継承する。WID.world 由来のテーブル（`staged/wid/*`、`marts/wealth_population_panel`）は CC BY-NC-SA 4.0 なので**非商用に限る**。e-Stat 由来のテーブル（`staged/estat/*`、`marts/jp_income_class_fertility`）は政府標準利用規約（第2.0版、CC BY 4.0 互換）で、再配布時は「出典：政府統計の総合窓口(e-Stat)、国民生活基礎調査（厚生労働省）を加工」の表記が必要。OECD 由来のテーブル（`staged/oecd/*`）は OECD Terms & Conditions（2024-07-01 改定。出典表示で商用含め自由利用、OECD 発行物は CC BY 4.0）で、再配布時は「OECD (2026), OECD Tax Database / SOCX / Revenue Statistics, https://sdmx.oecd.org (accessed on 2026-10-04)」の表記と、同じ表記義務の継承が必要。WID と OECD を結合した `marts/wealth_institutions_panel` は厳しい方（WID の CC BY-NC-SA 4.0、**非商用**）に従う。出典表記は `design/data-sources.md` の記載に従う。
