import pytest
from typer.testing import CliRunner

from socioscope_core import cli
from socioscope_core.core.pipeline import Context, Pipeline, Stage, StageResult
from socioscope_core.testing.fakes import FakeFetcher, InMemoryRawStore, InMemoryTableStore


def test_run_passes_only_filter_into_context(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[frozenset[str] | None] = []
    p = Pipeline(slug="demo", title="Demo")

    @p.register(Stage.FETCH)
    def fetch(ctx: Context) -> StageResult:
        seen.append(ctx.sources)
        return StageResult(stage=Stage.FETCH, written=("x",))

    monkeypatch.setattr(cli, "discover_themes", lambda: {"demo": p})
    monkeypatch.setattr(
        cli,
        "build_context",
        lambda settings, sources=None: Context(
            fetcher=FakeFetcher(),
            raw=InMemoryRawStore(),
            tables=InMemoryTableStore(),
            sources=sources,
        ),
    )
    runner = CliRunner()
    r = runner.invoke(cli.app, ["run", "demo", "fetch", "--only", "oecd", "--only", "wb"])
    assert r.exit_code == 0 and "written  x" in r.output
    r = runner.invoke(cli.app, ["run", "demo", "fetch"])
    assert r.exit_code == 0
    assert seen == [frozenset({"oecd", "wb"}), None]


def test_note_draft_writes_md_and_html_and_lists_images(tmp_path) -> None:
    report = tmp_path / "reports" / "2026-10-06-h6.md"
    report.parent.mkdir()
    report.write_text(
        "# タイトル\n\n## 結果\n![図](figures/a.png)\n\n| x | y |\n|---|---|\n| 1 | 2 |\n",
        encoding="utf-8",
    )
    runner = CliRunner()
    r = runner.invoke(cli.app, ["note-draft", str(report), "--out", str(tmp_path / "out")])
    assert r.exit_code == 0, r.output
    md = (tmp_path / "out" / "2026-10-06-h6.md").read_text(encoding="utf-8")
    html = (tmp_path / "out" / "2026-10-06-h6.html").read_text(encoding="utf-8")
    assert "【画像を挿入: a.png】" in md and "<h2>結果</h2>" in html
    assert "title    タイトル" in r.output
    assert str((report.parent / "figures" / "a.png").resolve()) in r.output
    assert "1 table(s)" in r.output


def test_note_draft_defaults_to_exports_dir_and_rejects_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    report = tmp_path / "r.md"
    report.write_text("# t\nbody\n", encoding="utf-8")
    runner = CliRunner()
    assert runner.invoke(cli.app, ["note-draft", str(report)]).exit_code == 0
    assert (tmp_path / "exports" / "note" / "r.md").exists()
    assert (tmp_path / "exports" / "note" / "r.html").exists()
    assert runner.invoke(cli.app, ["note-draft", str(tmp_path / "nope.md")]).exit_code == 2


def test_note_draft_embed_images_inlines_png_found_by_basename(tmp_path) -> None:
    report = tmp_path / "docs" / "a.md"
    report.parent.mkdir()
    report.write_text(
        "# t\n\n【画像を挿入: s01.png】\n\n【画像を挿入: missing.png】\n", encoding="utf-8"
    )
    figs = tmp_path / "themes" / "x" / "figures" / "summary"
    figs.mkdir(parents=True)
    (figs / "s01.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    runner = CliRunner()
    r = runner.invoke(
        cli.app,
        [
            "note-draft",
            str(report),
            "--out",
            str(tmp_path / "out"),
            "--embed-images",
            "--figures",
            str(tmp_path / "themes"),
        ],
    )
    assert r.exit_code == 0, r.output
    html = (tmp_path / "out" / "a.html").read_text(encoding="utf-8")
    assert '<img src="data:image/png;base64,iVBORw0KGgpmYWtl" alt="s01.png">' in html
    assert "【画像を挿入: missing.png】" in html
    assert "embedded 1 image(s)" in r.output
    assert "missing  missing.png" in r.output


def test_copy_html_to_clipboard_passes_a_file_not_the_html_as_argv(monkeypatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/usr/bin/osascript")
    monkeypatch.setattr(cli.subprocess, "run", lambda args, check: calls.append(list(args)) or None)
    big = "<p>x</p>" * 1_000_000
    cli.copy_html_to_clipboard(big)
    assert len(calls) == 1 and calls[0][0] == "/usr/bin/osascript"
    assert len(calls[0][2]) < 500 and "class HTML" in calls[0][2]


def test_note_draft_paste_script_requires_figure_base_url(tmp_path) -> None:
    report = tmp_path / "r.md"
    report.write_text("# t\n\n【画像を挿入: s01.png】\n", encoding="utf-8")
    runner = CliRunner()
    r = runner.invoke(
        cli.app, ["note-draft", str(report), "--out", str(tmp_path), "--paste-script"]
    )
    assert r.exit_code == 2 and "--figure-base-url" in r.output
    r = runner.invoke(
        cli.app,
        [
            "note-draft",
            str(report),
            "--out",
            str(tmp_path),
            "--paste-script",
            "--figure-base-url",
            "https://raw.githubusercontent.com/o/r/main/figs",
        ],
    )
    assert r.exit_code == 0, r.output
    js = (tmp_path / "r.paste.js").read_text(encoding="utf-8")
    assert '"https://raw.githubusercontent.com/o/r/main/figs/"' in js
    assert "written  " in r.output and "r.paste.js" in r.output
