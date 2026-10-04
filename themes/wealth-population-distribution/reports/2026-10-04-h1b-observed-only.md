# H1b: U 字判定は「観測年のみ」でどう変わるか — WID の補間・外挿を切り分けた感度分析（2026-10-04, theme: wealth-population-distribution）

## 要約（3〜5 行）
- H1（`2026-10-04-h1-ushape.md`）の限界「WID のどの年が推計・外挿か検証できなかった」への追補。WID 国別 zip の `WID_metadata_<ISO2>.csv` を staged に起こし（`staged/wid/metadata`, `staged/wid/data_points`）、`method` 文に書かれた**年別の構築方法**（observed / partial / imputed）と、データ CSV の `data_quality`（0–5）を突き合わせた。
- **資産上位 1% シェアには、WID が年別に「観測」と明示する年が 1 つも無い**（46 か国 2,281 国×年のうち observed 0、imputed 148 = 1980 年以前の「所得税データの傾向から構築」、残り 93.5% は記述なし＝不明）。したがって「観測年のみ」の U 字判定は資産では**判定不能（適格 0/46）**。代理指標 `data_quality == 0` を落とすと適格 9 か国に減り、うち U 字 5（ESP FRA GBR SWE USA）。H1 の「資産で U 字は少数派（12/46）」は、観測年だけで**支持も反証もできない**。
- 所得上位 1% シェアは 26 か国（欧州 DINA 系列）に年別記述があり、国×年の 23.7% が observed、7.2% partial、32.8% imputed、36.4% 不明。**観測年のみ（V1）では適格 15 か国・U 字 1（FIN）**: U 字の「谷までの下降」はほぼ全て 1980 年以前の推計年に依存している。一方「1980 年以降の上昇」は観測年のみでも **14/15（93%）** で、H1 の弱い形の結論は変わらない。
- 日本: 所得・資産とも WID の metadata に年別の構築記述が無く（所得は 1950–79 年が「所得税データの傾向から構築」=imputed、1980 年以降は不明）、観測年のみでは**何も言えない**。H1 の日本の記述（1980 年比 +2.2 pp・順位低下）は、1980 年以降の年を残す変種（V2, V3）では数値が変わらないが、その年が観測か推計かは WID 側から確認できない。
- `data_quality` の意味は WID の公開文書に無い（R パッケージ manual の「観測レベルの品質スコア」のみ）。本データでの経験則: 所得では **observed 年は q3–5 のみ**、q0–2 の年は observed に一度も現れない。ただし q3 以上でも imputed 年が多い（imputed の 543 件が q3）ので「q が高い＝観測」ではない。H1 が感度分析で「4–5 を推計扱い」として落としたのは**向きが逆**で、最良の年を落としていた（H1 の数値は変更せず、限界節に注記）。すべて記述であり因果は扱わない。

## 問いと仮説
`design/themes/wealth-population-distribution.md` の H1（上位 1%/10% 資産シェアは 1980 年前後を谷として U 字型に上昇している国が多数派）について、H1 レポートの限界節に挙げた「WID の推計部分に判定が依存している可能性」を、WID の metadata で確認できる範囲で定量化する。

推定したい量: H1 と同じ **事前定義の U 字基準を満たす国の割合**（記述的）を、「観測年のみ」のサンプルで再計算したときの値と、観測／推計の国×年の内訳。事前登録の H1 の追補であり、新しい仮説は立てない。変種 V0–V5 は結果を見る前にスクリプト docstring に列挙した。対象は H1 の文言に合わせ上位 1%（資産・所得）のみ（上位 10% は H1 で同じ傾向だったので省略。事前の範囲限定）。

## データ
| 変数 | 出典 | 定義・単位 | 期間・国 | 備考（欠損・断絶） |
|---|---|---|---|---|
| `top1_wealth_share`, `top1_income_share` | `marts/wealth_population_panel`（H1 と同一、10,396 行） | 上位 1% 純個人資産／税引前国民所得シェア、成人・均等割、0–1 | 46 か国、窓 1950–2024 | H1 と同じ。欠損は補完しない |
| `construction` | `staged/wid/data_points`（6,261 行: iso3×variable×year） | WID_metadata の `method` 文から機械的に起こした年別ラベル。**observed** = 一次入力（survey / tax data）がすべて直接観測、**partial** = 一次入力の一方が interpolated/extrapolated、**imputed** = 一次入力なし（純粋な補間・外挿）または「Before YYYY, series is constructed based on the trend observed in the fiscal income data」「Before YYYY, pretax income shares estimated based on methodology in long-run paper」の対象年、**None** = metadata に年別の記述なし | 所得: 26 か国に年別記述（1980–2023 年）。資産: 年別記述なし、19 か国に 1980 年以前の trend 記述 | 変換規則は `wid.parse_method` / `wid.classify_segment`（テスト済）。WID の表記ゆれ（`distribtion`）も含めて 23 種の記述を全部分類。未知の語彙は fail-closed |
| `top1_income_observed`, `top1_wealth_observed` | mart に追加した bool 列 | `construction == "observed"` なら True、partial/imputed なら False、不明なら null | — | 本レポートでは `data_points` を直接使った（同じ情報） |
| `data_quality` | `staged/wid/top_shares` | WID 観測レベル品質スコア 0–5 | — | 定義は非公開（`design/data-sources.md` 参照）。同一国×変数×年で百分位間の差は無し |

- 窓 1950–2024 の国×年の内訳（stdout `coverage by construction`）:

| 系列 | n | observed | partial | imputed | 不明 |
|---|---|---|---|---|---|
| 上位 1% 資産 | 2,281 | 0 (0.0%) | 0 | 148 (6.5%) | 2,133 (93.5%) |
| 上位 1% 所得 | 2,696 | 640 (23.7%) | 193 (7.2%) | 883 (32.8%) | 980 (36.4%) |

- 所得で observed 年が 1 つ以上ある国は 26/46、1990 年より前に observed が 3 年以上ある国は 15（AUT BEL CHE 等は 2000 年代以降のみ observed）。observed の最初の年は最も早くて 1980 年（CZE DNK FIN FRA HUN IRL PRT SVK SWE）。**1980 年より前に「observed」と明示された年は所得・資産ともゼロ**。
- 不明（記述なし）の国: 所得では AUS CAN NZL CRI ISR RUS SAU（全年）と、`Before 1980 ... trend` 記述のみの国（USA JPN KOR IND IDN TUR ZAF CHL ARG BRA COL MEX CHN）の 1980 年以降。資産では 1980 年以降の全国。
- raw・ライセンス: H1 と同じ（WID.world, CC BY-NC-SA 4.0、`data/raw/manifest.jsonl`、再取得 2026-10-04）。

## 方法
識別戦略: なし（記述）。H1 の U 字基準・窓・適格性（`a20261004_h1_ushape.Criterion`）をそのまま使い、系列の年を以下で欠損化してから `classify_all` → `majority_test` / `rise_since_1980_test` を再実行する（行は落とさず値を None にする。補完しない）。

事前列挙の変種:
- V0 基準（全年、H1 と同一。照合用）
- V1 metadata 厳格: `construction == observed` のみ残す（partial・imputed・不明を欠損化）
- V2 metadata 緩和: `construction == imputed` のみ欠損化（observed・partial・不明は残す）
- V3 `data_quality == 0` を欠損化（代理指標）
- V4 `data_quality <= 1` を欠損化（代理・強）
- V5 V2 と V3 の併用

加えて、construction × data_quality の照合表（窓内）で代理指標の向きを経験的に確認する。乱数なし（2 回実行で stdout バイト一致）。

## 結果
図（`reports/figures/`、出典 WID.world CC BY-NC-SA 4.0、縦軸シェア 0–1、横軸年）:
- `h1b_top1_income_small_multiples.png`: 46 か国の上位 1% 所得シェア。● observed、○ partial、点線 imputed、灰線 不明。タイトルの U/–/(n/a) は V1 の判定、`obs=観測年/全年`。
- `h1b_top1_wealth_small_multiples.png`: 同、資産。全小図が灰（不明）か点線（1980 年以前の推計）で、● が 1 つも無い。

### U 字の割合（適格国のうち k/n、Wilson 95%、片側二項 p）
| 変種 | 上位 1% 資産 | 上位 1% 所得 |
|---|---|---|
| V0 基準（= H1） | 12/46 = 0.26 [0.16, 0.40], p = 1.00 | 22/46 = 0.48 [0.34, 0.62], p = 0.67 |
| V1 観測年のみ | **適格 0/46（判定不能）** | **1/15 = 0.07 [0.01, 0.30]**, p = 1.00（U: FIN） |
| V2 imputed 年のみ除外 | 9/46 = 0.20 [0.11, 0.33] | 9/38 = 0.24 [0.13, 0.39]（不適格 8） |
| V3 q=0 除外 | 5/9 = 0.56 [0.27, 0.81], p = 0.50（不適格 37） | 21/46 = 0.46 [0.32, 0.60] |
| V4 q≤1 除外 | 5/8 = 0.63 [0.31, 0.86], p = 0.36（不適格 38） | 21/37 = 0.57 [0.41, 0.71], p = 0.26 |
| V5 V2+V3 | 4/8 = 0.50 [0.22, 0.79] | 9/38 = 0.24 |

補助指標「1980 年（最近傍）→最新年の変化 > 0」:
| 変種 | 上位 1% 資産 | 上位 1% 所得 |
|---|---|---|
| V0 | 35/46 = 0.76 | 37/46 = 0.80 |
| V1 | 判定不能 | **14/15 = 0.93 [0.70, 0.99]**, p = 0.0005 |
| V2 | 35/46 = 0.76 | 31/38 = 0.82 |
| V3 | 7/9 = 0.78 | 37/46 = 0.80 |
| V4 | 6/8 = 0.75 | 32/37 = 0.86 |

読み方:
- **資産**: V1 で全国が不適格なのは、WID の資産系列に年別の「観測」記述が存在しないため。V2（1980 年以前の trend 構築年を落とす）で U 字が 12 → 9 に減るのは IND ITA USA の「谷までの下降」が 1950–70 年代の推計年だけで成り立っていたから。V3/V4（`data_quality` 代理）では 46 か国中 37–38 か国が不適格になり（資産の国×年の 69% が q0）、残る 8–9 か国（長期の一次資料がある FRA GBR SWE USA ESP 等）では U 字が 5/8–5/9 と過半だが、区間は 0.5 をまたぎ、サンプルは Piketty 系研究の対象国に偏る。
- **所得**: 観測年のみ（V1）では U 字は 1/15。observed の最初の年が 1980 年以降なので、1980 年前後の谷「までの下降」は観測年だけでは原理的に見えない（判定基準の構造的な帰結であり、U 字が「無い」ことの証拠ではない）。V2 でも 22 → 9（DNK FRA GBR HUN IRL ITA NLD POL PRT SWE USA ZAF が非 U に変わる: いずれも下降局面が 1980 年以前の推計年）。他方「1980 年以降の上昇」は V1 で 14/15 と、観測年だけで最も強く出る。
- **data_quality × construction（所得、窓内）**: observed 640 年はすべて q3–5（q3 138, q4 448, q5 54）。partial は q2–4。imputed は q0–5 に散らばる（q0 50, q1 105, q2 49, q3 543, q4 115, q5 21）。つまり **q ≤ 2 ⇒ 非観測** は本データで成立するが、**q ≥ 3 ⇒ 観測** は成立しない。資産は observed が無いので照合できない（imputed 148 年は q0 24, q2 82, q4 28 等でばらつく）。`data_quality == 0` を「補間・外挿」の代理にするのは資産では過剰（1980 年以降の 1,572 年が q0 で、SAU JPN 等は全年 q0）。
- **日本**: 所得は 1950–79 年が imputed（「所得税データの傾向から構築」）、1980 年以降は記述なし。資産は 1950–70 年が imputed、1980 年以降は記述なし。V1 では両系列とも年が残らない。V2/V3 では H1 と同じ値（所得 1980 年比 +2.2 pp、2024 年順位 22/46; 資産 +1.9 pp、29/46）だが、根拠となる 1980 年以降の年の観測性は不明。V4 では日本の 2014–2024 年（q1）が落ち、最終年が 2013 年になる（stdout の `rank 2024: None/6` は 2024 年に q ≥ 2 の国が 6 か国しか残らないことを示す）。

## 頑健性
本レポート自体が H1 の頑健性分析であり、変種は上表の V0–V5 で全部。U 字基準のパラメータ（δ、谷の窓、分析窓）は H1 で動かしたので再掲しない。V1 で所得の適格国を「1990 年より前に observed 3 年」から緩めることはしなかった（事後に基準を変えない）。

## 限界・言えないこと
- **因果は言えない**（H1 と同じ）。
- **「観測」ラベルは WID の自由記述を機械的に分類したもの**で、WID の内部的な区分ではない。年別記述があるのは欧州 DINA 系列 26 か国だけで、米国・日本・豪州・カナダ等の所得系列や全資産系列は「不明」。不明 = 推計という意味ではない（USA の DINA は 1962 年以降マイクロデータだが metadata に年別記述が無い）。したがって V1 は「WID が年別に観測と明示した年」という**狭い定義**であり、観測年を過小に数える。
- **`data_quality` の定義は非公開**。向き（高いほど良い）と「q ≤ 2 は非観測」は本データでの経験則に過ぎず、WID の更新で変わりうる。
- **資産については metadata から何も言えない**。資産系列の構築方法は `source_text`（Bajard et al. 2021 「Estimates and Imputations」、Blanchet & Martínez-Toledano 2021 等）の文献を読む必要があり、本レポートはそれをしていない。
- U 字判定が観測年のみで激減するのは、基準が 1950–60 年代の水準を必要とする構造によるもので、観測年の系列が「U 字でない」証拠ではない（打ち切りによる判定不能と、非 U は区別して報告した）。
- 国レベルの話であり、個人・世帯には読み替えない。

## 再現手順
```bash
uv sync --all-packages && chflags -R nohidden .venv
uv run socioscope run wealth-population-distribution fetch   # 46 zip（CC BY-NC-SA 4.0）
uv run socioscope run wealth-population-distribution stage && uv run socioscope run wealth-population-distribution mart
uv run socioscope db build && uv run socioscope db query "select construction, count(*) from staged.wid_data_points group by 1"
uv run python themes/wealth-population-distribution/src/theme_wealth_population_distribution/analysis/a20261004_h1b_observed_only.py \
  > themes/wealth-population-distribution/reports/2026-10-04-h1b-observed-only.stdout.txt
uv run pytest themes/wealth-population-distribution   # tests/test_wid.py（metadata 解析）・test_analysis_h1b.py
```
使用テーブル: `marts/wealth_population_panel`（10,396 行、既存列に `top1_income_observed BOOLEAN, top1_wealth_observed BOOLEAN` を追加）、`staged/wid/data_points`（6,261 行: `iso3, year, variable, is_observed, construction, basis, method_segment, source`）、`staged/wid/metadata`（138 行: `iso3, variable, shortname, unit, source_text, method, avg_quality, source`）、`staged/wid/top_shares`（`data_quality`）。LLM 構造化は使っていない。スクリプトは決定的（2 回実行で stdout バイト一致）。H1 スクリプトも新 mart で再実行し、コミット済み stdout とバイト一致を確認。

## チェックリスト回答
- **A-1** H1 の事前登録仮説・指標の追補。変種 V0–V5 と対象（上位 1% のみ）はスクリプト docstring に結果を見る前に列挙。
- **A-2** 推定量: 観測年のみでの U 字基準充足国の割合（記述）。
- **B-1** 出典・定義・取得日（2026-10-04）・ライセンスは H1 と共通。metadata 列の実フォーマットは `design/data-sources.md` に記録。
- **B-2** 観測／推計／不明の内訳を国別に列挙（stdout）。補完なし。`data_quality` の定義が非公開であることと経験則の限界を明記。
- **B-3** V1 の適格国が減る理由（observed の最初の年が 1980 年）と、それが判定不能であって非 U ではないことを明記。
- **C-1〜C-3** 識別戦略なし、因果の仮定なし。
- **C-4** 国レベルのみ。
- **D-1** 回帰なし。二項検定の独立性の限界は H1 と同じ。
- **D-2** 事前列挙の 6 変種をすべて報告。
- **D-3** 資産は観測年では判定不能、所得は U 字が 1/15 まで下がる一方「1980 年以降の上昇」は 14/15。結論の変化を要約に明記。
- **E-1** 「整合的」「記述」のみ。
- **E-2** 図は軸・単位・出典・凡例・n（obs/全年）を記載。
- **E-3** 限界節あり。
- **E-4** 再現コマンド・テーブルのスキーマ・行数を記載。LLM 列なし。
