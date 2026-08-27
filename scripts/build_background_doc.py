"""One-off script: render the geopolitics-tracker background/brand document to PDF+HTML.

Not part of the Ingestion->Extraction->Analysis->Reporting->Publishing pipeline -
this produces a standalone bilingual-brand document (Hebrew RTL + English LTR),
reusing the same rendering approach as src/reporting/render.py (WeasyPrint, a
locally embedded variable font, the site's base light-theme color tokens) so
the document reads as part of the same brand family as the live reports/site,
while using a more elegant, modern screen-friendly typeface (Assistant) suited
to a principles/one-pager document rather than the site's own Heebo. Source
content lives in src/common/about_content.py (shared with publish.py's
about.html) - reproduced verbatim, not re-paraphrased here.
"""

import base64
from pathlib import Path

from weasyprint import HTML as WeasyHTML

from src.common.about_content import CONTENT, render_sections_html

REPO_ROOT = Path(__file__).resolve().parents[1]
FONT_PATH = REPO_ROOT / "scripts" / "assets" / "Assistant-Variable.ttf"
LOGO_PATH = REPO_ROOT / "scripts" / "assets" / "MS_Logo.png"
OUTPUT_DIR = REPO_ROOT / "scripts" / "output"

# Same base light-theme tokens as src/reporting/render.py's :root block.
COLORS = {
    "bg": "#f3efe8",
    "bg-elevated": "#fffdfa",
    "text": "#221f1b",
    "text-muted": "#6d675e",
    "border": "#e4ddd0",
    "masthead-accent": "#7a2e2a",
}


def _b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def build_html(lang: str) -> str:
    is_he = lang == "he"
    dir_attr = "rtl" if is_he else "ltr"
    content = CONTENT[lang]

    font_b64 = _b64(FONT_PATH)
    logo_b64 = _b64(LOGO_PATH)
    sections_html = render_sections_html(content["sections"])

    page_title = f"geopolitics-tracker - {content['doc_meta']}"
    identity_dir = "rtl" if is_he else "ltr"
    identity_align = "right" if is_he else "left"
    body_dir = "rtl" if is_he else "ltr"
    body_align = "right" if is_he else "left"

    return f"""<!doctype html>
<html lang="{lang}" dir="{dir_attr}">
<head>
<meta charset="utf-8">
<title>{page_title}</title>
<style>
  @font-face {{
    font-family: "Assistant";
    src: url("data:font/ttf;base64,{font_b64}") format("truetype-variations");
    font-weight: 200 800;
  }}

  :root {{
    --bg: {COLORS['bg']};
    --bg-elevated: {COLORS['bg-elevated']};
    --text: {COLORS['text']};
    --text-muted: {COLORS['text-muted']};
    --border: {COLORS['border']};
    --masthead-accent: {COLORS['masthead-accent']};
  }}

  * {{ box-sizing: border-box; }}

  body {{
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: "Assistant", system-ui, sans-serif;
    line-height: 1.7;
  }}

  .page {{ max-width: 44rem; margin: 0 auto; padding: 2.5rem 1.8rem 3rem; }}

  .header {{ direction: ltr; text-align: left; margin-bottom: 2rem; }}

  .letterhead {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 1.5rem; }}
  .identity-line {{ direction: {identity_dir}; text-align: {identity_align}; font-size: 1.15rem; margin: 0; white-space: nowrap; }}
  .identity-name {{ font-weight: 800; color: var(--text); }}
  .identity-sep {{ color: var(--text-muted); }}
  .identity-role {{ font-weight: 400; color: var(--text-muted); }}
  .logo {{ flex: 0 0 auto; height: 76px; width: auto; margin-inline-start: 1.5rem; }}

  .header-bottom-rule {{ border-bottom: 3px solid var(--masthead-accent); padding-bottom: 1.6rem; }}

  .doc-meta {{
    margin: 0 0 .6rem;
    font-size: .85rem;
    font-weight: 700;
    color: var(--masthead-accent);
  }}
  .doc-title {{
    margin: 0 0 1rem;
    font-size: 2.4rem;
    font-weight: 800;
    letter-spacing: -0.01em;
  }}
  .doc-subtitle {{
    direction: {body_dir};
    text-align: {body_align};
    margin: 0;
    font-size: 1rem;
    font-style: italic;
    color: var(--text-muted);
  }}

  .body {{ direction: {body_dir}; text-align: {body_align}; }}

  .body p {{ margin: 0 0 1.1rem; font-size: 1rem; }}

  .body h2 {{
    display: flex;
    align-items: center;
    gap: .9rem;
    margin: 1.9rem 0 1.1rem;
    font-size: 1.3rem;
    font-weight: 700;
    color: var(--masthead-accent);
    white-space: nowrap;
  }}
  .body h2::after {{
    content: "";
    flex: 1;
    height: 1px;
    background: var(--border);
  }}

  .body ul {{ margin: 0 0 1.1rem; padding-inline-start: 1.4rem; }}
  .body ul li {{ margin-bottom: .6rem; font-size: 1rem; }}

  @page {{
    size: A4;
    margin: 2cm 1.8cm;
    @bottom-center {{ content: counter(page); font-size: 9px; color: #888; }}
  }}
</style>
</head>
<body>
  <div class="page">
    <div class="header">
      <div class="header-bottom-rule">
        <div class="letterhead">
          <p class="identity-line">
            <span class="identity-name">{content['identity_name']}</span>
            <span class="identity-sep">-</span>
            <span class="identity-role">{content['identity_role']}</span>
          </p>
          <img class="logo" src="data:image/png;base64,{logo_b64}" alt="">
        </div>
        <p class="doc-meta">{content['doc_meta']}</p>
        <h1 class="doc-title">{content['title']}</h1>
        <p class="doc-subtitle">{content['subtitle']}</p>
      </div>
    </div>

    <div class="body">
{sections_html}
    </div>
  </div>
</body>
</html>
"""


def run() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for lang, suffix in (("he", ""), ("en", "-en")):
        html_str = build_html(lang)

        html_path = OUTPUT_DIR / f"geopolitics-tracker-background-doc{suffix}.html"
        html_path.write_text(html_str, encoding="utf-8")
        print(f"wrote {html_path}")

        pdf_path = OUTPUT_DIR / f"geopolitics-tracker-background-doc{suffix}.pdf"
        WeasyHTML(string=html_str, base_url=str(html_path)).write_pdf(str(pdf_path))
        print(f"wrote {pdf_path}")


if __name__ == "__main__":
    run()
