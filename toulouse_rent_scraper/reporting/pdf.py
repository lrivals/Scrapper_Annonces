# reporting/pdf.py
# =========================
# Sprint 5.5 — rapports Markdown → PDF.
# Conversion HTML par un petit convertisseur (le sous-ensemble que génère
# reporting/generator.py : titres, tableaux, listes, citations, liens, images, gras),
# puis PDF par Chromium headless via Playwright (déjà installé) : pas de dépendance
# de plus. Sans rapport avec le Chrome du scraping : profil temporaire, aucun site visité.
# =========================

import html
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Sequence

from utils.logger import setup_logger

logger = setup_logger("reporting")

_CSS = """
body { font-family: "DejaVu Sans", Arial, sans-serif; font-size: 10.5pt; color: #1f2328; line-height: 1.45; }
h1 { font-size: 17pt; border-bottom: 2px solid #2f6feb; padding-bottom: 4px; }
h2 { font-size: 13pt; margin-top: 18px; page-break-after: avoid; }
h3 { font-size: 11.5pt; margin-top: 12px; page-break-after: avoid; }
table { border-collapse: collapse; margin: 6px 0 10px; min-width: 55%; page-break-inside: avoid; }
th, td { border: 1px solid #d0d7de; padding: 3px 6px; text-align: left; vertical-align: top; }
th { background: #f0f3f6; }
blockquote { margin: 6px 0; padding: 2px 10px; border-left: 3px solid #d0d7de; color: #57606a; }
img { max-width: 260px; max-height: 180px; border-radius: 4px; }
a { color: #0969da; text-decoration: none; }
hr { border: 0; border-top: 1px solid #d0d7de; margin: 12px 0; }
li { margin: 2px 0; }
"""


def _url(escaped: str) -> str:
    """URL déjà échappée par _inline (& → &amp;) : seuls les guillemets restent à neutraliser."""
    return escaped.replace('"', "%22")


def _inline(text: str, images: bool = True) -> str:
    """Échappement HTML puis images, liens, gras."""
    out = html.escape(text, quote=False)
    out = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)",
                 (lambda m: f'<img alt="{m.group(1)}" src="{_url(m.group(2))}">') if images else "", out)
    out = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)",
                 lambda m: f'<a href="{_url(m.group(2))}">{m.group(1)}</a>', out)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    return out


def _cells(line: str) -> List[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def markdown_to_html(text: str, images: bool = True) -> str:
    """
    Convertit le Markdown des rapports en HTML (corps seulement). `images=False` retire les
    photos (le PDF les embarquerait en pleine résolution : plusieurs dizaines de Mo).
    """
    out: List[str] = []
    lines = text.splitlines()
    i = 0
    list_tag: Optional[str] = None

    def close_list():
        nonlocal list_tag
        if list_tag:
            out.append(f"</{list_tag}>")
            list_tag = None

    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()

        # Tableau : ligne d'en-tête suivie de |---|
        if stripped.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|$", lines[i + 1].strip()):
            close_list()
            head = "".join(f"<th>{_inline(c, images)}</th>" for c in _cells(stripped))
            rows = []
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append("<tr>" + "".join(f"<td>{_inline(c, images)}</td>" for c in _cells(lines[i])) + "</tr>")
                i += 1
            out.append(f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>")
            continue

        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        bullet = re.match(r"^[-*]\s+(.*)$", stripped)
        numbered = re.match(r"^\d+\.\s+(.*)$", stripped)
        if heading:
            close_list()
            level = len(heading.group(1))
            out.append(f"<h{level}>{_inline(heading.group(2), images)}</h{level}>")
        elif stripped in ("---", "***"):
            close_list()
            out.append("<hr>")
        elif bullet or numbered:
            tag = "ul" if bullet else "ol"
            if list_tag != tag:
                close_list()
                out.append(f"<{tag}>")
                list_tag = tag
            out.append(f"<li>{_inline((bullet or numbered).group(1), images)}</li>")
        elif stripped.startswith(">"):
            close_list()
            out.append(f"<blockquote>{_inline(stripped.lstrip('> '), images)}</blockquote>")
        elif not stripped:
            close_list()
        else:
            close_list()
            paragraph = _inline(stripped, images)
            if paragraph:
                out.append(f"<p>{paragraph}</p>")
        i += 1
    close_list()
    return "\n".join(out)


def html_document(body: str, title: str) -> str:
    return (
        f'<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>{html.escape(title)}</title>'
        f"<style>{_CSS}</style></head><body>{body}</body></html>"
    )


def _footer(title: str) -> str:
    return (
        '<div style="font-size:8px;width:100%;padding:0 12mm;color:#57606a;display:flex;'
        'justify-content:space-between"><span>' + html.escape(title)
        + f" — généré le {datetime.now():%d/%m/%Y %H:%M}</span>"
        '<span><span class="pageNumber"></span>/<span class="totalPages"></span></span></div>'
    )


def _launch(playwright):
    """Chromium de Playwright, sinon le Chrome du système (headless, profil temporaire)."""
    try:
        return playwright.chromium.launch(headless=True)
    except Exception:
        from scrapers.browser import find_chrome_binary
        return playwright.chromium.launch(headless=True, executable_path=find_chrome_binary())


def markdown_files_to_pdf(paths: Sequence[Path], title: str, output: Optional[Path] = None) -> List[Path]:
    """
    Un seul PDF qui assemble les rapports donnés (un saut de page entre chacun), à côté
    du premier : rapports_<date>.pdf. Retourne [chemin du PDF], ou [] en cas d'échec
    (un PDF raté ne doit pas faire échouer le run).
    """
    paths = [Path(p) for p in paths if Path(p).exists()]
    if not paths:
        return []
    output = output or paths[0].parent / f"rapports_{datetime.now():%Y-%m-%d}.pdf"
    body = '<div style="page-break-after: always"></div>'.join(
        markdown_to_html(p.read_text(encoding="utf-8"), images=False) for p in paths
    )
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = _launch(p)
            try:
                page = browser.new_page()
                page.set_content(html_document(body, title), wait_until="load", timeout=60_000)
                page.pdf(
                    path=str(output), format="A4", print_background=True,
                    margin={"top": "14mm", "bottom": "16mm", "left": "12mm", "right": "12mm"},
                    display_header_footer=True, header_template="<span></span>",
                    footer_template=_footer(title),
                )
            finally:
                browser.close()
    except Exception as e:
        logger.error(f"Export PDF impossible : {e}")
        return []
    logger.info(f"PDF créé : {output}")
    return [output]
