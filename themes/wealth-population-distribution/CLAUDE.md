# themes/wealth-population-distribution
設計: `design/themes/wealth-population-distribution.md`。規約: root `CLAUDE.md`、`.claude/rules/themes.md`。
データソースの調査記録: `design/data-sources.md`（WID.world）。

## 構成
```
src/theme_wealth_population_distribution/
  wid.py                 WID.world 国別 zip の URL 組み立て、zip → CSV 抽出、CSV → 行 の純粋変換（決定的・テスト対象）
  wid_iso2_to_iso3.csv   WID alpha2 → ISO3 の固定表（pycountry から生成しコミット。手で直す場合は理由をコメント）
  pipeline.py            fetch / stage / mart（Port 経由。I/O はここだけ）
  wiring.py              PIPELINE（entry point）
  analysis/              report 用スクリプト（決定的、seed 固定）
tests/                   fixtures/wid_data_sample.csv（合成の数行）＋ Fake による状態テスト
```

## 状態
WID.world を採用し fetch/stage/mart 実装済み（ライセンスは **CC BY-NC-SA 4.0** 扱い、`design/data-sources.md` 参照）。
World Bank Gini、UN WPP 等は未接続。

## テーブル
| name | 粒度 | 列 |
|---|---|---|
| `staged/wid/top_shares` | iso3×year×variable×percentile | iso3, year, variable (`sptinc992j` / `shweal992j`), percentile (`p0p50`,`p50p90`,`p90p100`,`p99p100`), value (0–1 のシェア), data_quality (0–5 / None), source |
| `staged/wid/population` | iso3×year | iso3, year, value (人), data_quality, source |
| `marts/wealth_population_panel` | iso3×year | iso3, year, top1_income_share, top10_income_share, bottom50_income_share, top1_wealth_share, top10_wealth_share, population, source |
| `staged/worldbank/gini`（予定） | iso3×year | iso3, country, year, value, indicator, source |

## 規約・決定
- **対象国**: `wid.COUNTRIES` の 46 か国（OECD 38 ＋ 非 OECD G20 8: AR BR CN IN ID RU SA ZA）。raw は国別 zip（計 ~196MB）。全量 zip は 882MB で予算超過のため使わない。国を増やすときは raw サイズ（1 国 1〜9MB）を見て `COUNTRIES` を編集し、fetch を再実行する。
- **raw**: `data/raw/wealth-population-distribution/wid_world/WID_fulldataset_<ISO2>.zip` をそのまま保存（gitignore、manifest に URL・sha256・ライセンス）。zip 展開は stage 側で `wid.extract_data_csv`（bytes → bytes の純粋関数）で行う。metadata CSV は raw に保持し staged には出さない。
- **変数コード**: bulk CSV の `variable` は `sptincj992`（型+概念+pop+age）。staged ではサイト表記 `sptinc992j`（型+概念+age+pop）に正規化する（`wid.canonical_code`）。
- **ISO2→ISO3**: `wid_iso2_to_iso3.csv` の固定表で変換。表にない・2 文字でないコードは**捨てる**（地域集計 `WO`/`QE`/`XF`/`QE-MER`、サブナショナル `US-CA`/`CN-RU`/`DE-*`、非 ISO `XI`/`ZZ`/`XE`）。旧国は ISO 3166-3（`SU`→`SUN`, `YU`→`YUG`, `DD`→`DDR`, `CS`/`XC`→`CSK`）、コソボ `KS`/`XK`→`XKX`（World Bank 流儀）。flag 付きで残す案は、mart の `iso3` キーの意味を崩すので採らなかった。
- **欠損**: `None` のまま。補完しない。`data_quality` 4〜5 は WID 側の推計・外挿を含むので分析時に感度分析に使う。
- 資産統計はソース・年代で定義が異なる。断絶の説明は raw の `WID_metadata_<ISO2>.csv`（`source`/`method` 列）にある。必要になったら `definition_note` 列として staged に起こす。
