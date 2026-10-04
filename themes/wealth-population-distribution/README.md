# theme: wealth-population-distribution
設計: `design/themes/wealth-population-distribution.md`。データソース: WID.world（CC BY-NC-SA 4.0、`design/data-sources.md`）。
```bash
uv run socioscope run wealth-population-distribution fetch   # WID.world 国別 zip × 46 か国 → data/raw/wealth-population-distribution/wid_world/
uv run socioscope run wealth-population-distribution stage   # → data/staged/wid/{top_shares,population}.parquet
uv run socioscope run wealth-population-distribution mart    # → data/marts/wealth_population_panel.parquet
uv run socioscope db build && uv run socioscope db query "select * from marts.wealth_population_panel where iso3='JPN' and year>=2000"
```
対象国・ISO 変換・テーブル定義は `CLAUDE.md` を参照。
