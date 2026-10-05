# プロジェクト venv はドット名でない `venv/` に置く（iCloud の UF_HIDDEN 付与対策）

- **Status**: Accepted
- **Date**: 2026-10-05
- **関連**: ADR 0001（uv workspace）、ADR 0004（worktree 並列）、`Makefile`（`sync` / `doctor`）、`.claude/settings.json`（`env.UV_PROJECT_ENVIRONMENT`）、`README.md` トラブルシュート

## Context
macOS 上でこのリポジトリを `uv sync` / `uv run` すると、しばらく後に `.venv` 配下の `*.pth` に macOS の `UF_HIDDEN` フラグが付き、Python 3.13 の `site.py` が `Skipping hidden .pth file` として無視する。workspace member（`socioscope_core`・`theme_*`）は editable install（`_editable_impl_*.pth`）で `sys.path` に載るため、`ModuleNotFoundError: socioscope_core` になる。従来は `chflags -R nohidden .venv`（`make sync`）と `uv run --no-sync` で回避していたが、再同期のたびに再発した。

### 調査結果（2026-10-05、uv 0.11.26 / CPython 3.13 / macOS 25.6）
- **uv はフラグを付けていない**。本 worktree で `uv sync --all-packages` 直後に `ls -lO .venv …/*.pth` を見るとフラグは無く（`-`）、`touch pyproject.toml` 後の `uv run` 再同期でも付かない。uv の設定・環境変数にフラグ関連の項目は無い（`docs.astral.sh/uv/reference/settings` に venv パスやフラグを扱うキーは存在しない）。
- **フラグはリポジトリ全体のドット始まり項目に付いている**。main checkout では `.git`・`.gitignore`・`.github`・`.claude`・`.python-version`・`.env.example`・`.mypy_cache`・各 `**/.gitkeep` が hidden、ドット名でない項目は一つも hidden でない。配下にも伝播する（`.git/objects` が hidden）。`.pth` 自体はドット名でないが、hidden な `.venv` の配下にあるため同様に付く。
- **同じ親ディレクトリの他リポジトリ（shochupedia・kuma-informer）も同じ状態**。一方 `~/.cache`・`~/.local`・`~/.zshrc` など `~/Desktop` 外のドット項目には付いていない。
- **`~/Desktop` は iCloud Drive「デスクトップと書類」同期の対象**（`~/Library/Mobile Documents/com~apple~CloudDocs/Desktop -> /Users/taku/Desktop`）。フラグの ctime は checkout よりずっと後（例 `.gitignore` 21:23、`.claude` 00:00、`.git/objects` 00:10）で、同期デーモンが後追いで付与している挙動と一致する。iCloud 同期フォルダ内の venv で同じ症状が出る報告は複数ある（CPython gh-113356 のスレッド、`alexbejan/jevkit#1` など）。
- **CPython 側**: hidden な `.pth` の無視は 3.13 で導入された意図的な挙動（gh-113356 → PR 113357 / 113659、`._*.pth` など不正ファイルの回避）。3.13.x・3.14 でも維持されている。3.12 に下げれば回避できるが、`requires-python >=3.13` を変える理由にはならない。

**根本原因**: iCloud Drive がドット始まりの名前の項目（とその配下）に `UF_HIDDEN` を付与し、Python 3.13 がそれを尊重する。uv・本リポジトリのコードの問題ではない。

## Decision
プロジェクト環境を **ドット名でない `venv/`** に置く。
- `.claude/settings.json` の `env` に `UV_PROJECT_ENVIRONMENT=venv` を設定（Claude Code のセッション・hook・subagent すべてに効く）。
- `Makefile` で `export UV_PROJECT_ENVIRONMENT ?= venv`（`make *` 経由の uv も同じ環境）。
- `make sync` は `uv sync --all-packages` 後に **`.venv -> venv` の symlink** を作る。環境変数の無い素の `uv run`（ターミナル）も `.venv` 経由で同じ実体を使う。`site.py` の hidden 判定は `.pth` の実体（`venv/lib/.../*.pth`、ドット名でない親）に対して行われるため影響しない。実体の `.venv/` が残っていれば `make sync` が削除して symlink に置き換える。
- `make doctor` を追加（defence in depth）: `uv run --no-sync python -c "import socioscope_core, theme_growth_fertility, theme_wealth_population_distribution"` を試し、失敗時は `Skipping hidden .pth file` の有無と対処（`make sync`）を表示。`venv/` 配下の hidden フラグ件数も警告する。
- `chflags -R nohidden` と `uv run --no-sync` の運用は廃止。`.gitignore` に `venv/` を追加。
- 相対パスは **workspace root 基準**で解決されるので、`.claude/worktrees/*` の各 worktree が独立した `venv/` を持つ（ADR 0004 の worktree 並列を壊さない。`packages/core` から実行しても root の `venv` を使うことを確認済み）。
- CI（Ubuntu）は環境変数を設定せず従来どおり `.venv` を使う。変更不要。

## Alternatives considered
- **(a) `UV_PROJECT_ENVIRONMENT` を repo 外の固定パス（例 `~/.cache/socioscope/venv`）にする**: iCloud の影響は確実に避けられるが、固定パスだと main と各 worktree が **1 つの venv を共有**し、editable `.pth` が最後に sync した checkout を指す（別 worktree のコードを import する）。Claude Code の `env` で checkout ごとに異なる値を算出できないため却下。相対の `venv` なら同じ利点を worktree 独立で得られる。
- **(b) uv の設定キー**: `uv.toml` / `[tool.uv]` に venv パスやフラグを制御する項目は存在しない（uv settings reference を確認）。uv がフラグを付けているわけでもないので対象外。
- **(c) editable を止める（`uv sync --no-editable` / `editable = false`）**: `.pth` を使わなくなるので症状は消えるが、ソース編集が即反映されず TDD の Red→Green ループが壊れる。開発用途では不採用（デプロイ向け）。
- **(d) 同期後に毎回 `chflags -R nohidden`**: 従来の対処。uv の自動再同期（`uv run`）の経路では走らず、再発する。症状の後始末であって原因の除去ではない。
- **(e) `sitecustomize` / `usercustomize`**: `.pth` 処理そのものが失敗するので不適用。
- **Python 3.12 への降格**: hidden 判定が無いので回避できるが、3.13 の要件・型機能を捨てる理由にならず、他のドット項目（`.git` 等）への付与も解決しない。不採用。
- **リポジトリを iCloud 同期外（例 `~/code`）へ移動**: 本来の最善策で、`.git/objects` まで hidden になる現状（git 自体には無害だが Finder で見えない等）も解消する。ただしリポジトリ側で強制できないため、README で推奨するに留め、ここでは配置に依存しない対策を採る。

## Consequences
**良い点**: 再同期しても再発しない（フラグが付く名前空間に venv が無い）。`chflags`・`--no-sync` の運用が不要になり、`uv run` の自動同期をそのまま使える。worktree ごとの環境独立は維持。`make doctor` で症状を一発で診断できる。
**コスト・リスク**: `.venv` 固定を前提にするツール（一部エディタの自動検出）には `.venv` symlink で対応するが、uv が環境を作り直す際（Python 更新など）に symlink を実体ディレクトリで置き換える可能性がある → `make sync` を再実行すれば戻る。既存 checkout では初回に `make sync` が必要（`uv run` を先に打つと `.venv/` 実体が作られ、やがて hidden 化する）。`.gitkeep` や `.claude` など他のドット項目の hidden 化は本 ADR の範囲外（git の動作には影響しない）。

## 追記（2026-10-05）: ドット名ディレクトリ配下の worktree
Claude Code のエージェント worktree は `.claude/worktrees/<id>/` に作られる。親の `.claude` がドット名なので iCloud は **その配下すべて**（`venv/` を含む）に hidden フラグを付与し、本 ADR の「ドット名でない venv」が効かない。対処として `make sync` の最後に `chflags -R nohidden venv` を保険として実行する（main checkout では no-op）。worktree 内で `uv run` が自動再同期した場合は再発しうるので、worktree で import エラーが出たら `make sync` を打つ。根本対策はリポジトリを iCloud 同期外に置くこと（上記）。
