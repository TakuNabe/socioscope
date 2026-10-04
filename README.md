# socioscope

グローバル／日本国内の公開統計・公開情報を収集・構造化し、社会学的な分析と因果推論を行うモノレポ。

## テーマ
| slug | 問い | 状態 |
|---|---|---|
| `wealth-population-distribution` | 戦後、資本主義の進展とともに富の偏りは極端化しているのか（世界各国・日本） | 設計中 |
| `growth-fertility` | 経済成長と出生率の関係は国間・国内（所得階層）でフラクタルか | 分析中（World Bank fetch〜mart 実装済み。H1 report: `themes/growth-fertility/reports/2026-10-04-h1-income-tfr.md`） |

## セットアップ
```bash
uv sync --all-packages
cp .env.example .env   # ANTHROPIC_API_KEY（LLM 構造化を使う場合のみ）
make check             # lint / type / test
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
- `ModuleNotFoundError: socioscope_core` が出て、`uv run python -v -c pass 2>&1 | grep pth` に `Skipping hidden .pth file` が出る場合: macOS の hidden フラグが `.venv` 配下に付いている（Python 3.13 は hidden な .pth を無視する）。`chflags -R nohidden .venv` か `rm -rf .venv && uv sync --all-packages` で直る。
