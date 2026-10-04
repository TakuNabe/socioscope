# theme: growth-fertility
設計: `design/themes/growth-fertility.md`。
```bash
uv run socioscope run growth-fertility fetch   # World Bank WDI 3 指標 → data/raw/growth-fertility/worldbank/
uv run socioscope run growth-fertility stage   # → data/staged/worldbank/{tfr,gdp_pcap_ppp,gdp_growth}.parquet
uv run socioscope run growth-fertility mart    # → data/marts/growth_fertility_panel.parquet
```
