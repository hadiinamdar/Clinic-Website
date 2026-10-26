"""Fills the website's placeholder text from clinic_config.json (pure Python).

The HTML file keeps its readable placeholders (e.g. ``Dr. [Doctor Name]``), so
it still opens fine straight from disk. When the page is served by the backend,
every placeholder that has a value in clinic_config.json is replaced, with the
value escaped for wherever it lands (HTML, JSON-LD or a JavaScript string).
"""
from __future__ import annotations

import html
import json
import re

# (placeholder text, clinic_config.json key). Most specific first.
REPLACEMENTS: list[tuple[str, str]] = [
    ("Dr. [Doctor Name]", "doctor_name"),
    ("डॉ. [नाम]", "doctor_name"),
    ("डॉ. [नाव]", "doctor_name"),
    ("[MD / MS / DM / MCh]", "postgraduate_qualification"),
    ("[Professional bodies]", "memberships"),
    ("[Fellowship details]", "fellowships"),
    ("[Awards and publications]", "awards_and_research"),
    ("[qualifications]", "qualifications"),
    ("[योग्यता]", "qualifications"),
    ("[पात्रता]", "qualifications"),
    ("[specialty]", "specialty"),
    ("[XX]", "years_experience"),
    ("[____]", "registration_number"),
]

_SCRIPT_BLOCK = re.compile(r"(<script\b[^>]*>.*?</script>)", re.S | re.I)
_DEV_NOTE = re.compile(r'<p class="note" data-dev-note>.*?</p>', re.S)
_REVIEWS_SECTION = re.compile(r'<section id="reviews"[^>]*>.*?</section>', re.S)
_REVIEWS_LINK = '<a href="#reviews">Reviews</a>'


def _esc_html(value: str) -> str:
    return html.escape(value, quote=True)


def _esc_json(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)[1:-1].replace("<", "\\u003c").replace(">", "\\u003e")


def _esc_js(value: str) -> str:
    value = value.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')
    value = value.replace("\r", "").replace("\n", "\\n")
    return (
        value.replace("<", "\\x3c").replace(">", "\\x3e")
        .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    )


_ESCAPERS = {"html": _esc_html, "json": _esc_json, "js": _esc_js}


def _article(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


def _fill(chunk: str, cfg: dict, context: str) -> str:
    esc = _ESCAPERS[context]
    specialty = (cfg.get("specialty") or "").strip()
    if specialty and "a [specialty]" in chunk:  # keep "a"/"an" grammatical
        chunk = chunk.replace("a [specialty]", f"{_article(specialty)} {esc(specialty)}")
    for placeholder, key in REPLACEMENTS:
        value = str(cfg.get(key) or "").strip()
        if value and placeholder in chunk:
            chunk = chunk.replace(placeholder, esc(value))
    return chunk


def apply_config(page: str, cfg: dict) -> str:
    parts = _SCRIPT_BLOCK.split(page)
    out = []
    for part in parts:
        head = part[:80].lower()
        if head.startswith("<script"):
            context = "json" if "ld+json" in head else "js"
        else:
            context = "html"
        out.append(_fill(part, cfg, context))
    page = "".join(out)

    if cfg.get("hide_placeholder_notes"):
        page = _DEV_NOTE.sub("", page)
    if not cfg.get("show_sample_reviews", True):
        page = _REVIEWS_SECTION.sub("", page).replace(_REVIEWS_LINK, "")
    return page


def unfilled_keys(rendered_page: str) -> list[str]:
    """clinic_config.json keys whose placeholder text is still visible on the site."""
    return sorted({key for placeholder, key in REPLACEMENTS if placeholder in rendered_page})
