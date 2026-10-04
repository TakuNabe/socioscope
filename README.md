# socioscope

グローバル／日本国内の公開統計・公開情報を収集・構造化し、社会学的な分析と因果推論を行うモノレポ。

## テーマ
| slug | 問い | 状態 |
|---|---|---|
| `wealth-population-distribution` | 戦後、資本主義の進展とともに富の偏りは極端化しているのか（世界各国・日本） | 分析中（WID.world 取得〜mart 実装済み（46 か国）。H1 report: `themes/wealth-population-distribution/reports/2026-10-04-h1-ushape.md`。H2 用に OECD SDMX（最高税率・社会支出・税収）fetch〜mart 実装済み（OECD 38）。H2 report（限定・関連のみ）: `.../2026-10-04-h2-institutions.md`。**総括（一般向け・日本語）**: `.../2026-10-05-summary-wealth-population-distribution.md`） |
| `growth-fertility` | 経済成長と出生率の関係は国間・国内（所得階層）でフラクタルか | 分析中（World Bank fetch〜mart 実装済み。H1 report: `themes/growth-fertility/reports/2026-10-04-h1-income-tfr.md`。H3 用に e-Stat 国民生活基礎調査（所得階級×有配偶率・児童のいる世帯）fetch〜mart 実装済み） |

## セットアップ
```bash
make sync              # uv sync --all-packages（venv は `venv/`、`.venv` は symlink。ADR 0005）
cp .env.example .env   # ANTHROPIC_API_KEY（LLM 構造化を使う場合のみ）
make check             # lint / type / test
make doctor            # import できない時の診断
```

## 使い方
```bash
uv run socioscope themes                      # 登録テーマ一覧
uv run socioscope run growth-fertility fetch  # 取得（data/raw + manifest）
uv run socioscope run growth-fertility stage  # 正規化 → data/staged/*.parquet
uv run socioscope run growth-fertility mart   # 分析用テーブル → data/marts/*.parquet
uv run socioscope db build                    # Parquet から socioscope.duckdb を再生成
uv run socioscope db query "select * from marts.growth_fertility_panel limit 5"
```

## レイアウト
```
packages/core/      共有ライブラリ（取得・来歴・LLM 構造化・Parquet/DuckDB・CLI）
themes/<slug>/      テーマごとのパイプライン・SQL・ノートブック・レポート
data/               raw（gitignore）/ staged・marts（Parquet, git 管理）/ llm_cache
design/, docs/      設計・ADR・spec・方法論
.claude/            Claude Code ハーネス（agents / skills / rules / hooks）
```
設計の詳細は `CLAUDE.md` と `design/overview.md`、決定は `docs/adrs/` を参照。

## トラブルシュート
- `ModuleNotFoundError: socioscope_core`（`uv run python -v -c pass 2>&1 | grep pth` に `Skipping hidden .pth file`）: macOS で `~/Desktop`・`~/Documents` が iCloud Drive 同期の対象だと、ドット始まりの項目（`.venv` を含む）とその配下に `UF_HIDDEN` が付き、Python 3.13 は hidden な `.pth` を無視する。本リポジトリは venv を **`venv/`（ドット名でない）** に置くことで回避している（ADR 0005）。`make doctor` で診断、`make sync` で復旧。Claude Code 外の素の `uv run` も `.venv -> venv` symlink 経由で同じ環境を使う。実体の `.venv/` が残っている場合は `make sync` が symlink に置き換える。根本的には iCloud 同期外（例 `~/code`）にリポジトリを置くのが最善。

## ライセンス
- **コード・ドキュメント**: MIT（`LICENSE`）。
- **データ（`data/staged`, `data/marts`）**: 各出典のライセンスに従う派生物で、MIT の対象外。出典と条件は `design/data-sources.md` と `data/raw/manifest.jsonl` の `license` 列を正とする。
  - World Bank WDI 由来: CC BY 4.0（出典表記）。
  - e-Stat（国民生活基礎調査）由来: 政府標準利用規約（第2.0版）、CC BY 4.0 互換。出典表記必須（「出典：政府統計の総合窓口(e-Stat)」、加工した旨を記載）。
  - WID.world 由来: **CC BY-NC-SA 4.0**（出典表記・非商用・同一ライセンス継承）。本プロジェクトは非商用の研究目的に限る。
  - OECD（SDMX: Tax Database / SOCX / Revenue Statistics）由来: OECD Terms & Conditions（2024-07-01 改定、出典表示で自由利用。OECD 発行物は CC BY 4.0）。出典表記「OECD (2026), <dataset>, https://sdmx.oecd.org (accessed on 2026-10-04)」。`marts/wealth_institutions_panel` は WID と OECD の結合なので WID の NC 条件を継承する。
