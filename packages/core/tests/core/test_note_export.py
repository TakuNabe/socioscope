from socioscope_core.core.note_export import convert_report

REPORT = """# H6: 理想と出生率（2026-10-06, theme: growth-fertility）

## 要約（5 行）
- **問い**: 北欧の低下は `mart` で説明できるか。
- 相関は *r* = +0.56。

## データ
| データ | 出典 | 備考 |
|---|---|---|
| 理想 2011 | Testa (2012) | PDF 転記 |
| TFR | WDI `SP.DYN.TFRT.IN` | |

## 結果
### (a) 理想と TFR
![理想と TFR](figures/h6_ideals_vs_tfr.png)
*図 1: 左: 理想 × TFR。*

#### 細目
本文 [リンク](https://example.com/x) です。

---

## 再現手順
```bash
uv run socioscope run growth-fertility mart
```
"""


def test_title_comes_from_h1_and_is_removed_from_body() -> None:
    d = convert_report(REPORT)
    assert d.title == "H6: 理想と出生率（2026-10-06, theme: growth-fertility）"
    assert not d.markdown.startswith("# ")
    assert "# H6" not in d.markdown


def test_h2_h3_kept_and_h4_becomes_bold_paragraph() -> None:
    d = convert_report(REPORT)
    assert "## 要約（5 行）" in d.markdown
    assert "### (a) 理想と TFR" in d.markdown
    assert "#### 細目" not in d.markdown
    assert "**細目**" in d.markdown
    assert "<h2>要約（5 行）</h2>" in d.html
    assert "<h3>(a) 理想と TFR</h3>" in d.html
    assert "<p><strong>細目</strong></p>" in d.html


def test_images_become_placeholders_and_are_collected() -> None:
    d = convert_report(REPORT)
    assert "【画像を挿入: h6_ideals_vs_tfr.png】" in d.markdown
    assert "![" not in d.markdown
    assert d.images == ("figures/h6_ideals_vs_tfr.png",)
    assert "<img" not in d.html


def test_italic_caption_becomes_plain_text_but_bold_survives() -> None:
    d = convert_report(REPORT)
    assert "図 1: 左: 理想 × TFR。" in d.markdown
    assert "*図 1" not in d.markdown
    assert "**問い**" in d.markdown
    assert "相関は r = +0.56。" in d.markdown
    assert "<strong>問い</strong>" in d.html


def test_inline_code_backticks_are_stripped_in_markdown_and_tagged_in_html() -> None:
    d = convert_report(REPORT)
    assert "で説明できるか" in d.markdown
    assert "`mart`" not in d.markdown
    assert "<code>mart</code>" in d.html


def test_table_becomes_bullet_list_with_header_labels() -> None:
    d = convert_report(REPORT)
    assert "|---|" not in d.markdown
    assert "| データ |" not in d.markdown
    assert "- **理想 2011**: 出典 = Testa (2012) / 備考 = PDF 転記" in d.markdown
    # 空セルは出さない
    assert "- **TFR**: 出典 = WDI SP.DYN.TFRT.IN" in d.markdown
    assert d.tables == 1
    assert "<li><strong>理想 2011</strong>: 出典 = Testa (2012) / 備考 = PDF 転記</li>" in d.html


def test_fenced_code_block_is_preserved_verbatim() -> None:
    d = convert_report(REPORT)
    assert "```bash\nuv run socioscope run growth-fertility mart\n```" in d.markdown
    assert "<pre><code>uv run socioscope run growth-fertility mart\n</code></pre>" in d.html


def test_links_and_rules_render_in_html_with_escaping() -> None:
    d = convert_report(REPORT)
    assert '<a href="https://example.com/x">リンク</a>' in d.html
    assert "<hr>" in d.html
    e = convert_report("# t\n\na < b & c\n")
    assert "<p>a &lt; b &amp; c</p>" in e.html


def test_conversion_is_deterministic_and_handles_missing_title() -> None:
    assert convert_report(REPORT) == convert_report(REPORT)
    d = convert_report("## only h2\ntext\n")
    assert d.title == ""
    assert "## only h2" in d.markdown
