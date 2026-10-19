#!/usr/bin/env python3
"""
Nextcloud Deck → PDF Task Card Generator

CLI tool: pick a JSON file, filter by stack and/or label, export a PDF with
one page per card showing title, labels, and markdown description.
"""

import json
import os
import re
import sys

import markdown
from config import CONFIG, EmojiConfig, RenderConfig, TableConfig
from deck import collect_labels, filter_cards, load_deck
from reportlab.lib import colors
from reportlab.lib.fonts import tt2ps
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.rl_config import canvas_basefontname as _baseFontName
from reportlab.platypus import (
    Flowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from ui import ask_multiselect, pick_file, pick_folder


# ── Helpers ──────────────────────────────────────────────────────────────────

_FONTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
_EMOJI_FONT_PATH = os.path.join(_FONTS_DIR, "NotoEmoji-Regular.ttf")
_EMOJI_FONT_URLS = [
    "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/notoemoji/NotoEmoji%5Bwght%5D.ttf",
    "https://github.com/google/fonts/raw/main/ofl/notoemoji/NotoEmoji%5Bwght%5D.ttf",
]
_EMOJI_FONT_NAME = "NotoEmoji"

_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U0001F900-\U0001F9FF"  # supplemental symbols
    "\U0001FA00-\U0001FA6F"  # chess symbols
    "\U0001FA70-\U0001FAFF"  # symbols extended-A
    "\U00002702-\U000027B0"  # dingbats
    "\U0000FE00-\U0000FE0F"  # variation selectors
    "\U0000200D"             # zero width joiner
    "\U000024C2-\U0001F251"
    "\U00002600-\U000026FF"  # misc symbols
    "\U00002300-\U000023FF"  # misc technical
    "\U0000203C-\U00003299"  # CJK symbols, enclosed alphanumerics
    "]+",
    flags=re.UNICODE,
)

_emoji_font_registered = False


def _ensure_emoji_font(download_if_missing: bool = True):
    """Download Noto Emoji if needed and register it with ReportLab."""
    global _emoji_font_registered
    if _emoji_font_registered:
        return

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    # 1. Try already-downloaded Noto Emoji
    if os.path.isfile(_EMOJI_FONT_PATH):
        try:
            pdfmetrics.registerFont(TTFont(_EMOJI_FONT_NAME, _EMOJI_FONT_PATH))
            _emoji_font_registered = True
            return
        except Exception:
            pass

    if not download_if_missing:
        print("  ⚠ Noto Emoji font is not available – emojis will be stripped.")
        return

    # 2. Download Noto Emoji
    os.makedirs(_FONTS_DIR, exist_ok=True)
    print("Downloading Noto Emoji font...")
    import urllib.request
    downloaded = False
    for url in _EMOJI_FONT_URLS:
        try:
            urllib.request.urlretrieve(url, _EMOJI_FONT_PATH)
            downloaded = True
            break
        except Exception:
            continue
    if not downloaded:
        print("  ⚠ Could not download emoji font – emojis will be stripped.")
        print("  Manual install: download NotoEmoji-Regular.ttf and place in fonts/")
        return
    try:
        pdfmetrics.registerFont(TTFont(_EMOJI_FONT_NAME, _EMOJI_FONT_PATH))
        _emoji_font_registered = True
    except Exception:
        print("  ⚠ Could not register emoji font – emojis will be stripped.")


def process_emojis(text: str, emoji_config: EmojiConfig = CONFIG.emoji) -> str:
    """Wrap emoji characters in <font> tags for ReportLab, or strip them."""
    if not emoji_config.enabled:
        return _EMOJI_RE.sub("", text)
    if _emoji_font_registered:
        def _wrap(m):
            return f'<font name="{_EMOJI_FONT_NAME}">{m.group(0)}</font>'
        return _EMOJI_RE.sub(_wrap, text)
    return _EMOJI_RE.sub("", text)



class CheckBox(Flowable):
    """A small vector checkbox – drawn directly, no fonts or images needed."""

    def __init__(self, checked: bool = False, size: float = 7):
        super().__init__()
        self.checked = checked
        self.size = size

    def wrap(self, availWidth, availHeight):
        return self.size + 2, self.size + 2

    def draw(self):
        c = self.canv
        c.setLineWidth(0.6)
        c.setStrokeColor(colors.black)
        c.setFillColor(colors.white)
        c.rect(0, 0, self.size, self.size, fill=1, stroke=1)
        if self.checked:
            s = self.size
            c.setLineWidth(0.9)
            # checkmark: short stroke up-right, then longer stroke
            c.line(s * 0.2, s * 0.45, s * 0.42, s * 0.25)
            c.line(s * 0.42, s * 0.25, s * 0.82, s * 0.75)


# ── Horizontal rule ─────────────────────────────────────────────────────────

class HRFlowable(Flowable):
    """A thin horizontal line spanning the available width."""

    def __init__(self, width: float | None = None, thickness: float = 0.5):
        super().__init__()
        self._line_width = width
        self._thickness = thickness

    def wrap(self, availWidth, availHeight):
        self._line_width = self._line_width or availWidth
        return self._line_width, self._thickness + 4

    def draw(self):
        self.canv.setStrokeColor(colors.grey)
        self.canv.setLineWidth(self._thickness)
        self.canv.line(0, 2, self._line_width, 2)


# ── Markdown → ReportLab flowables ─────────────────────────────────────────

def _parse_html_blocks(html: str) -> list[str]:
    """Split HTML into meaningful block-level chunks, keeping <table>...</table> together."""
    blocks: list[str] = []
    buf: list[str] = []
    in_table = False

    for line in html.split("\n"):
        stripped = line.strip()
        if not stripped:
            if buf:
                blocks.append("\n".join(buf))
                buf = []
            continue
        if "<table" in stripped:
            in_table = True
            buf = [stripped]
            continue
        if in_table:
            buf.append(stripped)
            if "</table>" in stripped:
                blocks.append("\n".join(buf))
                buf = []
                in_table = False
            continue
        blocks.append(stripped)

    if buf:
        blocks.append("\n".join(buf))
    return blocks


def _strip_tags(html: str) -> str:
    """Remove HTML tags to get plain text length for width measurement."""
    return re.sub(r"<[^>]+>", "", html)


def _table_to_flowable(
    table_html: str,
    cell_style,
    avail_width: float,
    table_config: TableConfig,
) -> Flowable:
    """Parse a <table> HTML block into a ReportLab Table flowable spanning full width."""
    raw_rows: list[list[str]] = []      # raw cell text (with markup)
    rows: list[list[Paragraph]] = []    # Paragraph objects for rendering
    header_empty = False
    for tr_match in re.finditer(r"<tr>(.*?)</tr>", table_html, re.DOTALL):
        raw_cells = []
        all_empty = True
        for td_match in re.finditer(r"<t[hd][^>]*>(.*?)</t[hd]>", tr_match.group(1), re.DOTALL):
            text = td_match.group(1).strip()
            # Convert markdown tags to ReportLab tags in cells too
            text = text.replace("<strong>", "<b>").replace("</strong>", "</b>")
            text = text.replace("<em>", "<i>").replace("</em>", "</i>")
            if text:
                all_empty = False
            raw_cells.append(text)
        if not raw_rows and all_empty:
            header_empty = True
        raw_rows.append(raw_cells)

    if not raw_rows:
        return Paragraph(table_html, cell_style)

    num_cols = max(len(r) for r in raw_rows)

    # Measure longest plain-text per column for proportional widths
    col_max_chars = [0] * num_cols
    for row in raw_rows:
        for ci, text in enumerate(row):
            col_max_chars[ci] = max(col_max_chars[ci], len(_strip_tags(text)))

    # Distribute widths proportionally with a minimum floor.
    pad = round(cell_style.fontSize * 0.5) * 2  # left + right padding
    min_col = pad + 20
    total_chars = sum(col_max_chars) or 1
    if table_config.automatic_column_widths:
        raw_widths = [(c / total_chars) * avail_width for c in col_max_chars]
    else:
        raw_widths = [avail_width / num_cols] * num_cols
    col_widths = [max(w, min_col) for w in raw_widths]
    # Scale down if minimums pushed total over avail_width
    total_w = sum(col_widths)
    if total_w > avail_width:
        scale = avail_width / total_w
        col_widths = [w * scale for w in col_widths]

    # Build Paragraph objects (skip content for empty header)
    for ri, raw_cells in enumerate(raw_rows):
        if ri == 0 and header_empty:
            rows.append([Paragraph("\u00a0", cell_style)] * len(raw_cells))
        else:
            rows.append([Paragraph(c or "\u00a0", cell_style) for c in raw_cells])

    fs = cell_style.fontSize
    styles_list = [
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE", (0, 0), (-1, -1), fs),
        ("LEADING", (0, 0), (-1, -1), round(fs * 1.35)),
        ("TOPPADDING", (0, 0), (-1, -1), round(fs * 0.5)),
        ("BOTTOMPADDING", (0, 0), (-1, -1), round(fs * 0.5)),
        ("LEFTPADDING", (0, 0), (-1, -1), round(fs * 0.5)),
        ("RIGHTPADDING", (0, 0), (-1, -1), round(fs * 0.5)),
    ]
    if table_config.shade_header:
        styles_list.append(("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.9, 0.9, 0.9)))
    if header_empty and table_config.compact_empty_header:
        normal_row = fs * 1.35 + fs * 0.5 + fs * 0.5
        styles_list.append(("ROWHEIGHTS", (0, 0), (-1, 0), round(normal_row * 0.25)))
        styles_list.append(("TOPPADDING", (0, 0), (-1, 0), 0))
        styles_list.append(("BOTTOMPADDING", (0, 0), (-1, 0), 0))

    t = Table(
        rows,
        colWidths=col_widths,
        repeatRows=1 if table_config.repeat_headers else 0,
    )
    t.setStyle(TableStyle(styles_list))
    t.hAlign = "LEFT"
    return t


def _md_segment_to_flowables(
    md_text: str,
    styles,
    avail_width: float,
    config: RenderConfig,
) -> list:
    """Render one markdown segment (without headings) into flowables."""
    html = markdown.markdown(md_text, extensions=["tables", "fenced_code"])

    # Convert markdown HTML tags to ReportLab-compatible tags
    html = html.replace("<strong>", "<b>").replace("</strong>", "</b>")
    html = html.replace("<em>", "<i>").replace("</em>", "</i>")

    # Apply emoji rendering AFTER markdown→HTML conversion
    html = process_emojis(html, config.emoji)

    flowables: list = []

    for block in _parse_html_blocks(html):
        stripped = block.strip()
        if not stripped:
            flowables.append(Spacer(1, 4))
            continue
        if stripped.startswith("<table"):
            flowables.append(
                _table_to_flowable(stripped, styles["body"], avail_width, config.table)
            )
        elif stripped.startswith("<h"):
            m = re.match(r"<h([1-3])>", stripped)
            level = m.group(1) if m else "3"
            inner = re.sub(r"</?h[1-6]>", "", stripped)
            flowables.append(Paragraph(inner, styles[f"h{level}"]))
        elif stripped.startswith(("<ul", "<ol")):
            flowables.append(Paragraph(stripped, styles["body"]))
        elif stripped.startswith("<li"):
            text = stripped.replace("<li>", "").replace("</li>", "").strip()
            m = re.match(r"^\[([ xX])\]\s*", text)
            if m:
                checked = m.group(1).lower() == "x"
                if config.checkbox.enabled:
                    text = text[m.end():]
                    checkbox_size = (
                        config.typography.base_size * config.checkbox.size_scale
                    )
                    box_w = checkbox_size + 7
                    t = Table(
                        [[CheckBox(checked, checkbox_size),
                          Paragraph(text or "\u00a0", styles["body"])]],
                        colWidths=[box_w, avail_width - box_w - 4],
                    )
                    t.setStyle(TableStyle([
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 0),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                        ("TOPPADDING", (0, 0), (-1, -1), 0),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                    ]))
                    t.hAlign = "LEFT"
                    flowables.append(t)
                else:
                    flowables.append(Paragraph("- " + text, styles["body"]))
            else:
                flowables.append(Paragraph("  • " + text, styles["body"]))
        elif stripped.startswith("<p"):
            inner = stripped.replace("<p>", "").replace("</p>", "")
            flowables.append(Paragraph(inner, styles["body"]))
        elif stripped.startswith("<hr"):
            flowables.append(HRFlowable())
        elif stripped.startswith("<pre"):
            flowables.append(Paragraph(
                stripped.replace("<pre><code>", "").replace("</code></pre>", ""),
                styles["code"],
            ))
        else:
            flowables.append(Paragraph(stripped, styles["body"]))

    return flowables


def md_to_flowables(md_text: str, styles, avail_width: float, config: RenderConfig) -> list:
    """Convert a markdown string into a list of ReportLab flowables."""
    if not md_text or not md_text.strip():
        return [Paragraph("<i>No description</i>", styles["italic"])]

    # Split the raw markdown at ATX headings (# ...), so headings are always
    # rendered as headings regardless of markdown's block-context handling
    parts: list[tuple[str, object]] = []
    buf: list[str] = []
    in_fence = False
    for line in md_text.split("\n"):
        if line.strip().startswith("```"):
            in_fence = not in_fence
        m = None if in_fence else re.match(r"^(\s*)(#{1,6})\s+(.*)$", line)
        if m:
            if buf:
                parts.append(("md", "\n".join(buf)))
                buf = []
            parts.append(("h", (min(len(m.group(2)), 3), m.group(3).strip())))
        else:
            buf.append(line)
    if buf:
        parts.append(("md", "\n".join(buf)))

    flowables: list = []
    for kind, payload in parts:
        if kind == "h":
            level, text = payload
            flowables.append(Paragraph(process_emojis(text, config.emoji), styles[f"h{level}"]))
        else:
            flowables.extend(_md_segment_to_flowables(payload, styles, avail_width, config))
    return flowables


# ── Build PDF ───────────────────────────────────────────────────────────────


def _build_card_story(
    card: dict,
    styles: dict,
    avail_width: float,
    config: RenderConfig,
) -> list:
    """Build the flowable list for a single card."""
    parts = []
    parts.append(Paragraph(card["title"], styles["title"]))

    # Bereich (labels)
    metadata = config.metadata
    labels = card.get("labels", [])
    if metadata.show_labels and labels:
        names = [process_emojis(l.get("title", ""), config.emoji).strip() for l in labels]
        names = [n for n in names if n]
        parts.append(Paragraph(
            f'<b>{metadata.labels_title}:</b> {"  ·  ".join(names)}',
            styles["label"],
        ))
    elif metadata.show_labels:
        parts.append(Paragraph(
            f'<b>{metadata.labels_title}:</b> <i>{metadata.missing_value}</i>',
            styles["label"],
        ))

    # Status (stack name) + assigned users on one line
    stack_title = card.get("_stack_title", "")
    status_line = ""
    if metadata.show_status:
        status_line = (
            f'<b>{metadata.status_title}:</b> {process_emojis(stack_title, config.emoji)}'
            if stack_title
            else f'<b>{metadata.status_title}:</b> <i>{metadata.missing_value}</i>'
        )
    users = card.get("assignedUsers", [])
    if metadata.show_assignees and users:
        names = []
        for u in users:
            p = u.get("participant", {})
            names.append(p.get("displayname") or p.get("displayName") or u.get("displayName") or "?")
        prefix = "  ·  " if status_line else ""
        status_line += f'{prefix}<b>{metadata.assignees_title}:</b> {", ".join(names)}'
    if status_line:
        parts.append(Paragraph(status_line, styles["label"]))
    parts.append(Spacer(1, round(config.typography.base_size * 0.3) * mm))

    # Description
    desc = card.get("description", "")
    parts.extend(md_to_flowables(desc, styles, avail_width, config))
    return parts


def build_pdf(cards: list[dict], output_path: str, config: RenderConfig = CONFIG) -> None:
    """Generate the PDF with one page per card, even page count, footer on every page."""
    from reportlab.lib import pagesizes
    from reportlab.pdfgen import canvas as _canvas_mod

    if config.emoji.enabled:
        _ensure_emoji_font(config.emoji.download_if_missing)

    page_size = getattr(pagesizes, config.page.size, None)
    if page_size is None or config.page.size not in {"A4", "A5"}:
        raise ValueError("Page size must be either 'A4' or 'A5'.")
    page_w, _page_h = page_size
    margin = config.page.margin_left_mm * mm
    right_margin = config.page.margin_right_mm * mm
    top_margin = config.page.margin_top_mm * mm
    bottom_margin = config.page.margin_bottom_mm * mm
    # ReportLab frames add 6 points of padding around flowable content.
    content_padding = 6
    avail_width = page_w - margin - right_margin

    # ── Styles ──────────────────────────────────────────────────────────
    typography = config.typography
    base = typography.base_size
    sample_styles = getSampleStyleSheet()
    bold = tt2ps(_baseFontName, 1, 0)
    styles = {
        "title": ParagraphStyle("card_title", parent=sample_styles["Heading1"],
                                fontName=bold,
                                fontSize=round(base * typography.title_scale), spaceAfter=round(base * 0.5)),
        "h1": ParagraphStyle("md_h1", parent=sample_styles["Heading2"],
                             fontName=bold,
                             fontSize=round(base * typography.heading_1_scale), spaceAfter=round(base * 0.4)),
        "h2": ParagraphStyle("md_h2", parent=sample_styles["Heading3"],
                             fontSize=round(base * typography.heading_2_scale), spaceAfter=round(base * 0.35)),
        "h3": ParagraphStyle("md_h3", parent=sample_styles["Heading4"],
                             fontSize=round(base * typography.heading_3_scale), spaceAfter=round(base * 0.3)),
        "body": ParagraphStyle("md_body", parent=sample_styles["BodyText"],
                               fontSize=base, leading=round(base * typography.line_spacing),
                               spaceAfter=round(base * 0.25)),
        "italic": ParagraphStyle("md_italic", parent=sample_styles["BodyText"],
                                 fontSize=base, leading=round(base * typography.line_spacing),
                                 textColor=colors.grey),
        "code": ParagraphStyle("md_code", parent=sample_styles["Code"],
                               fontSize=round(base * typography.code_scale),
                               leading=round(base * typography.line_spacing),
                               backColor=colors.Color(0.95, 0.95, 0.95)),
        "label": ParagraphStyle("label", parent=sample_styles["Normal"],
                                fontSize=base, textColor=colors.Color(0.3, 0.3, 0.3),
                                spaceAfter=0),
    }

    # ── Card flowables + marker to track card boundaries on the canvas ──
    card_titles = [c["title"] for c in cards]

    class _CardMarker(Flowable):
        """Zero-size flowable that tells the canvas which card starts here."""
        def __init__(self, idx):
            super().__init__()
            self.idx = idx
        def wrap(self, aw, ah):
            return 0, 0
        def draw(self):
            self.canv._note_card(self.idx)

    real_counts: list[int] = []

    class _CountingCanvas(_canvas_mod.Canvas):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self._card_idx = -1
            self.card_counts = []
        def _note_card(self, idx):
            self._card_idx = idx
            while len(self.card_counts) <= idx:
                self.card_counts.append(0)
        def showPage(self):
            if self._card_idx >= 0:
                self.card_counts[self._card_idx] += 1
            super().showPage()
        def save(self):
            real_counts.clear()
            real_counts.extend(self.card_counts)
            super().save()

    def _assemble(pad_even: bool) -> list:
        # Build fresh flowables each pass – ReportLab keeps layout state on
        # flowables, so reusing them in a second build() causes LayoutErrors.
        story = []
        for i, card in enumerate(cards):
            story.append(_CardMarker(i))
            story.extend(_build_card_story(card, styles, avail_width, config))
            if (pad_even and i < len(real_counts) and real_counts[i] % 2 != 0):
                story.append(PageBreak())
            if i < len(cards) - 1:
                story.append(PageBreak())
        return story

    # ── Pass 1: build once to count the real pages per card ─────────────
    from io import BytesIO
    counting_doc = SimpleDocTemplate(
        BytesIO(), pagesize=page_size,
        leftMargin=margin, rightMargin=right_margin,
        topMargin=top_margin, bottomMargin=bottom_margin,
    )
    counting_doc.build(_assemble(False), canvasmaker=_CountingCanvas)

    # ── Pass 2: build final PDF, padding odd cards to even page counts ───
    padded_counts = [c + (c % 2) for c in real_counts]  # round up to even
    total_counts = real_counts

    class _FooterCanvas(_canvas_mod.Canvas):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self._card_idx = -1
            self._card_page = 0
        def _note_card(self, idx):
            self._card_idx = idx
            self._card_page = 0
        def showPage(self):
            if self._card_idx >= 0:
                self._card_page += 1
                # Padding pages are deliberately blank and are not included
                # in the page count shown on the card's real pages.
                if (config.footer.enabled
                        and self._card_page <= real_counts[self._card_idx]):
                    self._draw_footer()
            super().showPage()
        def _draw_footer(self):
            w, _h = self._pagesize
            footer_font_size = (
                config.typography.base_size * config.footer.font_scale
            )
            self.setFont("Helvetica", footer_font_size)
            self.setFillColor(colors.Color(0.4, 0.4, 0.4))
            title = (
                card_titles[self._card_idx].strip()
                if 0 <= self._card_idx < len(card_titles)
                else ""
            )
            if config.footer.show_card_title and title:
                self.drawString(
                    margin + content_padding,
                    config.footer.bottom_offset_mm * mm,
                    title,
                )
            total = total_counts[self._card_idx] if 0 <= self._card_idx < len(total_counts) else "?"
            if config.footer.show_page_number:
                self.drawRightString(
                    w - right_margin - content_padding,
                    config.footer.bottom_offset_mm * mm,
                    f"Seite {self._card_page}/{total}",
                )
        def save(self):
            # Safety net: ReportLab can swallow a trailing PageBreak, so add
            # the padding blank page here if it is still missing.
            if (config.page.even_pages_per_card and self._card_idx >= 0
                    and self._card_idx < len(padded_counts)
                    and self._card_page < padded_counts[self._card_idx]):
                self._card_page += 1
                if (config.footer.enabled
                        and self._card_page <= real_counts[self._card_idx]):
                    self._draw_footer()
                super().showPage()
            super().save()

    doc = SimpleDocTemplate(
        output_path, pagesize=page_size,
        leftMargin=margin, rightMargin=right_margin,
        topMargin=top_margin, bottomMargin=bottom_margin,
    )
    doc.build(_assemble(config.page.even_pages_per_card), canvasmaker=_FooterCanvas)


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    # 1. Pick JSON file
    json_path = pick_file()
    if not json_path:
        print("No file selected. Exiting.")
        sys.exit(0)

    try:
        board = load_deck(json_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Error loading JSON: {exc}", file=sys.stderr)
        sys.exit(1)

    stacks: dict = board.get("stacks", {})
    all_labels = collect_labels(board)

    # 2. Filter by stack
    stack_list = sorted(stacks.values(), key=lambda s: s.get("order", 0))
    stack_names = [f'{s["title"]}  ({len(s.get("cards", []))} cards)' for s in stack_list]
    stack_indices = ask_multiselect(stack_names, "Select stacks:")
    selected_stack_ids = [stack_list[i]["id"] for i in stack_indices]

    # 3. Filter by label (show card count per label across selected stacks)
    label_list = sorted(all_labels.values(), key=lambda l: l.get("title", ""))
    if label_list:
        cards_in_stacks = filter_cards(board, selected_stack_ids, [])
        label_card_counts: dict[int, int] = {}
        for c in cards_in_stacks:
            for lbl in c.get("labels", []):
                label_card_counts[lbl["id"]] = label_card_counts.get(lbl["id"], 0) + 1
        label_names = [
            f'{l.get("title", "???")}  ({label_card_counts.get(l["id"], 0)} cards)'
            for l in label_list
        ]
        label_indices = ask_multiselect(label_names, "Select labels:")
        selected_label_ids = [label_list[i]["id"] for i in label_indices]
    else:
        selected_label_ids = []

    # 4. Filter cards
    cards = filter_cards(board, selected_stack_ids, selected_label_ids)
    if not cards:
        print("No cards match the selected filters.")
        sys.exit(0)

    print(f"\n→ {len(cards)} card(s) selected for export.")

    # 5. Output path (native folder picker where available)
    default_name = os.path.splitext(os.path.basename(json_path))[0] + "_cards.pdf"
    output_path = pick_folder(default_name)
    if not output_path:
        print("No output path selected. Exiting.")
        sys.exit(0)

    # 6. Build PDF
    try:
        build_pdf(cards, output_path)
        print(f"✓ Exported {len(cards)} card(s) to {output_path}")
    except OSError as exc:
        print(f"Error writing PDF: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
