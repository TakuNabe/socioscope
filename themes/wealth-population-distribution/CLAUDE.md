# themes/wealth-population-distribution
設計: `design/themes/wealth-population-distribution.md`。規約: root `CLAUDE.md`、`.claude/rules/themes.md`。
構成は `themes/growth-fertility/CLAUDE.md` と同じ（`<source>.py` 純粋変換 / `pipeline.py` / `wiring.py` / `analysis/`）。

## 状態
fetch/stage/mart は未実装（stage 関数は skip を返す）。最初の item は WID.world の採用（ライセンス CC BY 4.0 の確認・CSV 取得・`staged/wid/*` のスキーマ決定）。

## テーブル（予定）
| name | 粒度 | 列 |
|---|---|---|
| `staged/wid/top_shares` | iso3×year×percentile | iso3, year, variable (sptinc/shweal…), percentile (p99p100…), value, source |
| `staged/worldbank/gini` | iso3×year | iso3, country, year, value, indicator, source |
| `marts/wealth_population_panel` | iso3×year | iso3, year, top1_income_share, top10_income_share, top1_wealth_share, gini, population, pop65_share, gdp_pcap_ppp |

## 注意
資産統計はソース・年代で定義が異なる。mart に `source` 列と `definition_note` 列を残し、系列断絶を可視化できるようにする。
