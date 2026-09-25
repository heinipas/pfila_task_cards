#!/usr/bin/env python3
"""
Nextcloud Deck → PDF Task Card Generator

CLI tool: pick a JSON file, filter by stack and/or label, export a PDF with
one page per card showing title, labels, and markdown description.
"""

import json
import os
import platform
import re
import subprocess
import sys

import markdown
from reportlab.lib import colors
from reportlab.lib.pagesizes import A5
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Flowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


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


def _ensure_emoji_font():
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


def process_emojis(text: str) -> str:
    """Wrap emoji characters in <font> tags for ReportLab, or strip them."""
    if _emoji_font_registered:
        def _wrap(m):
            return f'<font name="{_EMOJI_FONT_NAME}">{m.group(0)}</font>'
        return _EMOJI_RE.sub(_wrap, text)
    return _EMOJI_RE.sub("", text)


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


def _table_to_flowable(table_html: str, cell_style, avail_width: float) -> Flowable:
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

    # Distribute widths proportionally with a minimum floor
    pad = round(cell_style.fontSize * 0.5) * 2  # left + right padding
    min_col = pad + 20
    total_chars = sum(col_max_chars) or 1
    raw_widths = [(c / total_chars) * avail_width for c in col_max_chars]
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
        ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.9, 0.9, 0.9)),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE", (0, 0), (-1, -1), fs),
        ("LEADING", (0, 0), (-1, -1), round(fs * 1.35)),
        ("TOPPADDING", (0, 0), (-1, -1), round(fs * 0.5)),
        ("BOTTOMPADDING", (0, 0), (-1, -1), round(fs * 0.5)),
        ("LEFTPADDING", (0, 0), (-1, -1), round(fs * 0.5)),
        ("RIGHTPADDING", (0, 0), (-1, -1), round(fs * 0.5)),
    ]
    if header_empty:
        # Force small row height for empty header: set height and zero out padding
        normal_row = fs * 1.35 + fs * 0.5 + fs * 0.5
        styles_list.append(("ROWHEIGHTS", (0, 0), (-1, 0), 0))
        styles_list.append(("TOPPADDING", (0, 0), (-1, 0), 0))
        styles_list.append(("BOTTOMPADDING", (0, 0), (-1, 0), 0))

    t = Table(rows, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle(styles_list))
    return t


def md_to_flowables(md_text: str, styles, avail_width: float) -> list:
    """Convert a markdown string into a list of ReportLab flowables."""
    if not md_text or not md_text.strip():
        return [Paragraph("<i>No description</i>", styles["italic"])]

    html = markdown.markdown(md_text, extensions=["tables", "fenced_code"])

    # Convert markdown HTML tags to ReportLab-compatible tags
    html = html.replace("<strong>", "<b>").replace("</strong>", "</b>")
    html = html.replace("<em>", "<i>").replace("</em>", "</i>")

    # Apply emoji rendering AFTER markdown→HTML conversion
    html = process_emojis(html)

    flowables: list = []

    for block in _parse_html_blocks(html):
        stripped = block.strip()
        if not stripped:
            flowables.append(Spacer(1, 4))
            continue
        if stripped.startswith("<table"):
            flowables.append(_table_to_flowable(stripped, styles["body"], avail_width))
        elif stripped.startswith("<h1"):
            flowables.append(Paragraph(stripped, styles["h1"]))
        elif stripped.startswith("<h2"):
            flowables.append(Paragraph(stripped, styles["h2"]))
        elif stripped.startswith("<h3"):
            flowables.append(Paragraph(stripped, styles["h3"]))
        elif stripped.startswith(("<ul", "<ol")):
            flowables.append(Paragraph(stripped, styles["body"]))
        elif stripped.startswith("<li"):
            flowables.append(Paragraph(
                "  • " + stripped.replace("<li>", "").replace("</li>", ""),
                styles["body"],
            ))
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


# ── Build PDF ───────────────────────────────────────────────────────────────

def build_pdf(cards: list[dict], output_path: str) -> None:
    """Generate the PDF with one page per card."""
    _ensure_emoji_font()

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A5,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )
    avail_width = A5[0] - 30 * mm  # page width minus margins

    # ── Base font size: all other sizes are relative to this ────────────
    base = 9  # change this single value to scale everything

    sample_styles = getSampleStyleSheet()
    styles = {
        "title": ParagraphStyle(
            "card_title",
            parent=sample_styles["Heading1"],
            fontSize=round(base * 1.3),
            spaceAfter=round(base * 0.5),
        ),
        "h1": ParagraphStyle(
            "md_h1",
            parent=sample_styles["Heading2"],
            fontSize=round(base * 1.2),
            spaceAfter=round(base * 0.4),
        ),
        "h2": ParagraphStyle(
            "md_h2",
            parent=sample_styles["Heading3"],
            fontSize=round(base * 1.1),
            spaceAfter=round(base * 0.35),
        ),
        "h3": ParagraphStyle(
            "md_h3",
            parent=sample_styles["Heading4"],
            fontSize=round(base * 1.1),
            spaceAfter=round(base * 0.3),
        ),
        "body": ParagraphStyle(
            "md_body",
            parent=sample_styles["BodyText"],
            fontSize=base,
            leading=round(base * 1.35),
            spaceAfter=round(base * 0.25),
        ),
        "italic": ParagraphStyle(
            "md_italic",
            parent=sample_styles["BodyText"],
            fontSize=base,
            leading=round(base * 1.35),
            textColor=colors.grey,
        ),
        "code": ParagraphStyle(
            "md_code",
            parent=sample_styles["Code"],
            fontSize=round(base * 0.85),
            leading=round(base * 1.2),
            backColor=colors.Color(0.95, 0.95, 0.95),
        ),
        "label": ParagraphStyle(
            "label",
            parent=sample_styles["Normal"],
            fontSize=base,
            textColor=colors.Color(0.3, 0.3, 0.3),
            spaceAfter=0,
        ),
    }

    story: list = []

    for idx, card in enumerate(cards):
        # Title
        story.append(Paragraph(card["title"], styles["title"]))

        # Bereich (labels)
        labels = card.get("labels", [])
        if labels:
            names = [process_emojis(l.get("title", "")).strip() for l in labels]
            names = [n for n in names if n]
            story.append(Paragraph(f'<b>Bereich:</b> {"  ·  ".join(names)}', styles["label"]))
        else:
            story.append(Paragraph('<b>Bereich:</b> <i>—</i>', styles["label"]))

        # Status (stack name)
        stack_title = card.get("_stack_title", "")
        story.append(Paragraph(
            f'<b>Status:</b> {process_emojis(stack_title)}' if stack_title else '<b>Status:</b> <i>—</i>',
            styles["label"],
        ))

        story.append(Spacer(1, round(base * 0.3) * mm))

        # Assigned users (if any)
        users = card.get("assignedUsers", [])
        if users:
            names = []
            for u in users:
                p = u.get("participant", {})
                names.append(p.get("displayname") or p.get("displayName") or u.get("displayName") or "?")
            story.append(Paragraph(
                f'<b>Zugewiesen an:</b> {", ".join(names)}',
                styles["label"],
            ))
            story.append(Spacer(1, round(base * 0.2) * mm))

        # Description (markdown → HTML → ReportLab)
        desc = card.get("description", "")
        story.extend(md_to_flowables(desc, styles, avail_width))

        # Page break after each card (except the last)
        if idx < len(cards) - 1:
            story.append(PageBreak())

    doc.build(story)


# ── CLI helpers ──────────────────────────────────────────────────────────────

def pick_file_macos() -> str | None:
    """Use macOS native dialog via osascript to pick a file."""
    try:
        result = subprocess.run(
            [
                "osascript", "-e",
                (
                    'POSIX path of (choose file with prompt '
                    '"Select Nextcloud Deck JSON export" of type {"public.json"})'
                ),
            ],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def pick_file_cli() -> str | None:
    """Prompt the user to type or paste a file path."""
    path = input("Path to Nextcloud Deck JSON file: ").strip().strip('"').strip("'")
    return path if path else None


def pick_file() -> str | None:
    """Try macOS native dialog first, fall back to CLI prompt."""
    if platform.system() == "Darwin":
        result = pick_file_macos()
        if result:
            return result
    return pick_file_cli()


def pick_folder_macos() -> str | None:
    """Use macOS native dialog via osascript to pick a folder."""
    try:
        result = subprocess.run(
            [
                "osascript", "-e",
                (
                    'POSIX path of (choose folder with prompt '
                    '"Select output folder for PDF")'
                ),
            ],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def pick_folder(default_name: str) -> str | None:
    """Ask user for an output folder (native dialog on macOS), return full path."""
    if platform.system() == "Darwin":
        folder = pick_folder_macos()
        if folder:
            return os.path.join(folder, default_name)
    # CLI fallback
    out = input(f"Output PDF path [{default_name}]: ").strip()
    return out if out else default_name


def ask_multiselect(options: list[str], prompt: str) -> list[int]:
    """
    Show a numbered list and let the user pick items.
    Returns list of 0-based indices.  Empty input = select all.
    """
    print(f"\n{prompt}")
    print("-" * len(prompt))
    for i, opt in enumerate(options, 1):
        print(f"  {i}. {opt}")
    print()
    raw = input("Enter numbers separated by commas (empty = all): ").strip()
    if not raw:
        return list(range(len(options)))
    indices: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < len(options):
                indices.append(idx)
    return indices if indices else list(range(len(options)))


# ── Data helpers ────────────────────────────────────────────────────────────

def load_deck(path: str) -> dict:
    """Load and return the first board from a Nextcloud Deck JSON export."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    boards = data.get("boards", [])
    if not boards:
        raise ValueError("No boards found in the JSON file.")
    return boards[0]


def collect_labels(board: dict) -> dict[int, dict]:
    """Gather all unique labels from the board."""
    labels: dict[int, dict] = {}
    for lbl in board.get("labels", []):
        labels[lbl["id"]] = lbl
    for stack in board.get("stacks", {}).values():
        for card in stack.get("cards", []):
            for lbl in card.get("labels", []):
                if lbl["id"] not in labels:
                    labels[lbl["id"]] = lbl
    return labels


def filter_cards(board: dict, stack_ids: list[int], label_ids: list[int]) -> list[dict]:
    """
    Return cards that belong to the selected stacks **and** have at least one
    of the selected labels.  If no labels are selected, return all cards from
    the chosen stacks.
    """
    selected_stacks = set(stack_ids)
    selected_labels = set(label_ids)

    result: list[dict] = []
    stacks = board.get("stacks", {})
    for sid in sorted(stacks, key=lambda k: stacks[k].get("order", 0)):
        if int(sid) not in selected_stacks:
            continue
        stack_title = stacks[sid].get("title", "")
        for card in stacks[sid].get("cards", []):
            card_label_ids = {lbl["id"] for lbl in card.get("labels", [])}
            if not selected_labels or card_label_ids & selected_labels or not card_label_ids:
                card["_stack_title"] = stack_title
                result.append(card)
    return result


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

    # 5. Output path (folder picker on macOS)
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
