"""Convert an analysis report (Markdown) into text that pastes cleanly into the note.com editor.

note.com has no public write API (official help: 公開予定は未定), so the
realistic route is: convert → copy → paste by hand. The editor supports H2/H3 headings, bold, lists,
links, quotes, code blocks and horizontal rules, but not tables, italics, H4+ or Markdown images.
This module is pure (no I/O) and deterministic: the same report always yields the same draft.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass

_IMG = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
_PLACEHOLDER = re.compile(r"^【画像を挿入: ([^】]+)】$")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<![*\w])\*(?!\*)([^*\n]+?)\*(?!\*)")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_LIST = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
_TABLE_SEP = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


@dataclass(frozen=True)
class NoteDraft:
    """Result of converting one report."""

    title: str
    markdown: str
    html: str
    images: tuple[str, ...]
    tables: int


def _split_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _inline_md(text: str) -> str:
    """Inline cleanup for the Markdown variant: drop backticks and italics, keep bold/links."""
    text = _CODE.sub(r"\1", text)
    return _ITALIC.sub(r"\1", text)


def _inline_html(text: str) -> str:
    """Render the inline subset (bold, code, links) to escaped HTML; italics become plain."""
    text = _ITALIC.sub(r"\1", text)
    out: list[str] = []
    pos = 0
    token = re.compile(f"{_CODE.pattern}|{_BOLD.pattern}|{_LINK.pattern}")
    for m in token.finditer(text):
        out.append(html.escape(text[pos : m.start()]))
        if m.group(1) is not None:
            out.append(f"<code>{html.escape(m.group(1))}</code>")
        elif m.group(2) is not None:
            out.append(f"<strong>{_inline_html(m.group(2))}</strong>")
        else:
            out.append(
                f'<a href="{html.escape(m.group(4), quote=True)}">{_inline_html(m.group(3))}</a>'
            )
        pos = m.end()
    out.append(html.escape(text[pos:]))
    return "".join(out)


def _table_to_bullets(rows: list[list[str]]) -> list[str]:
    header, body = rows[0], rows[1:]
    bullets: list[str] = []
    for row in body:
        cells = row + [""] * (len(header) - len(row))
        pairs = [f"{h} = {c}" for h, c in zip(header[1:], cells[1:], strict=False) if c]
        bullets.append(f"- **{cells[0]}**: {' / '.join(pairs)}" if pairs else f"- **{cells[0]}**")
    return bullets


def _placeholder(name: str) -> str:
    return f"【画像を挿入: {name}】"


def convert_report(markdown: str, embedded: Mapping[str, str] | None = None) -> NoteDraft:
    """Convert report Markdown into a note-ready Markdown body plus an HTML rendering.

    ``embedded`` maps an image basename to an ``src`` (typically a ``data:`` URI). Images found
    there are rendered as ``<img>`` in the HTML; the Markdown always keeps the placeholder.
    """
    embedded = embedded or {}
    title = ""
    images: list[str] = []
    tables = 0
    md_lines: list[str] = []
    html_blocks: list[str] = []
    para: list[str] = []
    list_items: list[tuple[str, str]] = []  # (kind, inline html)

    def flush_para() -> None:
        if para:
            html_blocks.append(f"<p>{_inline_html(' '.join(para))}</p>")
            para.clear()

    def flush_list() -> None:
        if list_items:
            tag = "ol" if list_items[0][0] == "ol" else "ul"
            items = "".join(f"<li>{t}</li>" for _, t in list_items)
            html_blocks.append(f"<{tag}>{items}</{tag}>")
            list_items.clear()

    def flush() -> None:
        flush_para()
        flush_list()

    lines = markdown.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]

        if line.startswith("```"):
            flush()
            j = i + 1
            code: list[str] = []
            while j < len(lines) and not lines[j].startswith("```"):
                code.append(lines[j])
                j += 1
            md_lines.extend([line, *code, "```"])
            html_blocks.append(f"<pre><code>{html.escape(chr(10).join(code))}\n</code></pre>")
            i = j + 1
            continue

        if line.lstrip().startswith("|") and i + 1 < len(lines) and _TABLE_SEP.match(lines[i + 1]):
            flush()
            rows = [_split_row(line)]
            j = i + 2
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                rows.append(_split_row(lines[j]))
                j += 1
            tables += 1
            bullets = _table_to_bullets(rows)
            md_lines.extend(_inline_md(b) for b in bullets)
            items = "".join(f"<li>{_inline_html(b[2:])}</li>" for b in bullets)
            html_blocks.append(f"<ul>{items}</ul>")
            i = j
            continue

        h = _HEADING.match(line)
        if h:
            flush()
            level, raw = len(h.group(1)), h.group(2)
            text = _inline_md(raw)
            if level == 1:
                if not title:
                    title = text
                    i += 1
                    continue
                level = 2
            if level <= 3:
                md_lines.append(f"{'#' * level} {text}")
                html_blocks.append(f"<h{level}>{_inline_html(raw)}</h{level}>")
            else:
                md_lines.append(f"**{text}**")
                html_blocks.append(f"<p><strong>{_inline_html(raw)}</strong></p>")
            i += 1
            continue

        if re.fullmatch(r"\s*(-{3,}|\*{3,}|_{3,})\s*", line):
            flush()
            md_lines.append("---")
            html_blocks.append("<hr>")
            i += 1
            continue

        if not line.strip():
            flush()
            md_lines.append("")
            i += 1
            continue

        def image_block(ref: str, alt: str) -> None:
            images.append(ref)
            name = ref.rsplit("/", 1)[-1]
            md_lines.append(_placeholder(name))
            src = embedded.get(name)
            if src is None:
                html_blocks.append(f"<p>{html.escape(_placeholder(name))}</p>")
            else:
                alt_text = html.escape(alt or name, quote=True)
                html_blocks.append(
                    f'<p><img src="{html.escape(src, quote=True)}" alt="{alt_text}"></p>'
                )

        pm = _PLACEHOLDER.match(line.strip())
        im = _IMG.fullmatch(line.strip())
        if pm or im:
            flush()
            if pm:
                image_block(pm.group(1).strip(), "")
            elif im:
                image_block(im.group(2), im.group(1))
            i += 1
            continue

        def repl_img(m: re.Match[str]) -> str:
            images.append(m.group(2))
            return _placeholder(m.group(2).rsplit("/", 1)[-1])

        line = _IMG.sub(repl_img, line)

        lm = _LIST.match(line)
        if lm:
            flush_para()
            kind = "ol" if lm.group(2)[0].isdigit() else "ul"
            md_lines.append(f"{lm.group(1)}{lm.group(2)} {_inline_md(lm.group(3))}")
            list_items.append((kind, _inline_html(lm.group(3))))
            i += 1
            continue

        if line.startswith(">"):
            flush()
            raw = line[1:].strip()
            md_lines.append(f"> {_inline_md(raw)}")
            html_blocks.append(f"<blockquote>{_inline_html(raw)}</blockquote>")
            i += 1
            continue

        flush_list()
        md_lines.append(_inline_md(line.strip()))
        para.append(line.strip())
        i += 1

    flush()
    body = re.sub(r"\n{3,}", "\n\n", "\n".join(md_lines)).strip() + "\n"
    return NoteDraft(
        title=title,
        markdown=body,
        html="\n".join(html_blocks) + "\n",
        images=tuple(images),
        tables=tables,
    )


_PASTE_JS = """(async () => {
  // note.com の記事編集画面（editor.note.com）で、本文にフォーカスを当ててから
  // DevTools コンソールに貼り付けて実行する。本文を貼り、各【画像を挿入】を図で置き換える。
  const HTML = __HTML__;
  const BASE = __BASE__;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const pm = document.querySelector(".ProseMirror");
  if (!pm) throw new Error("note の本文エディタ（.ProseMirror）が見つかりません");
  pm.focus();
  const paste = (dt) =>
    pm.dispatchEvent(
      new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true })
    );
  const selNode = (node, contents) => {
    const s = window.getSelection();
    const r = document.createRange();
    contents ? r.selectNodeContents(node) : r.selectNode(node);
    s.removeAllRanges();
    s.addRange(r);
  };
  const dt = new DataTransfer();
  dt.setData("text/html", HTML);
  dt.setData("text/plain", "note-draft");
  paste(dt);
  await sleep(1500);
  const RX = /^【画像を挿入: ([^】]+)】$/;
  const log = [];
  for (let n = 0; n < 200; n++) {
    const p = [...pm.querySelectorAll("p")].find((e) => RX.test(e.textContent.trim()));
    if (!p) break;
    const name = p.textContent.trim().match(RX)[1];
    const res = await fetch(BASE + name);
    if (!res.ok) {
      log.push(name + ": fetch " + res.status);
      selNode(p, true);
      document.execCommand("insertText", false, "【画像なし: " + name + "】");
      await sleep(300);
      continue;
    }
    const type = res.headers.get("content-type") || "image/png";
    const file = new File([await res.blob()], name, { type });
    selNode(p, true);
    await sleep(100);
    const d = new DataTransfer();
    d.items.add(file);
    paste(d);
    let ok = false;
    for (let w = 0; w < 120; w++) {
      await sleep(250);
      const f = p.nextElementSibling;
      const img = f && f.tagName === "FIGURE" ? f.querySelector("img") : null;
      if (img && img.src.startsWith("https")) { ok = true; break; }
    }
    if (!ok) { log.push(name + ": upload timeout"); break; }
    selNode(p, true);
    await sleep(100);
    document.execCommand("delete");
    await sleep(300);
    if (p.isConnected && p.textContent.trim() === "") {
      selNode(p, false);
      await sleep(100);
      document.execCommand("delete");
      await sleep(300);
    }
    log.push(name + ": ok");
  }
  console.log(log.join("\\n"));
  const left = (pm.innerText.match(/【画像を挿入/g) || []).length;
  console.log("figures:", pm.querySelectorAll("figure").length, "placeholders left:", left);
})();
"""


def paste_script(draft: NoteDraft, figure_base_url: str) -> str:
    """Build a self-contained script for the note editor's DevTools console.

    It pastes ``draft.html`` into the body and replaces every 【画像を挿入: x.png】 paragraph
    with the figure fetched from ``figure_base_url + x.png`` (the editor accepts pasted image
    *files* and uploads them; it strips ``<img>`` tags, so data URIs cannot be used).
    """
    base = figure_base_url if figure_base_url.endswith("/") else figure_base_url + "/"
    return _PASTE_JS.replace("__HTML__", json.dumps(draft.html, ensure_ascii=False)).replace(
        "__BASE__", json.dumps(base)
    )
