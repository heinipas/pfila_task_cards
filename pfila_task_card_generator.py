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

_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U00002702-\U000027B0"  # dingbats
    "\U0000FE00-\U0000FE0F"  # variation selectors
    "\U0000200D"             # zero width joiner
    "\U000024C2-\U0001F251"
    "]+",
    flags=re.UNICODE,
)


def strip_emojis(text: str) -> str:
    """Remove emoji characters that ReportLab's built-in fonts cannot render."""
    return _EMOJI_RE.sub("", text).strip()


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


def _table_to_flowable(table_html: str, cell_style) -> Flowable:
    """Parse a <table> HTML block into a ReportLab Table flowable."""
    rows: list[list[str]] = []
    for tr_match in re.finditer(r"<tr>(.*?)</tr>", table_html, re.DOTALL):
        cells = []
        for td_match in re.finditer(r"<t[hd][^>]*>(.*?)</t[hd]>", tr_match.group(1), re.DOTALL):
            text = re.sub(r"<[^>]+>", "", td_match.group(1)).strip()
            cells.append(text)
        rows.append(cells)

    if not rows:
        return Paragraph(table_html, cell_style)

    t = Table(rows, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.9, 0.9, 0.9)),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("LEADING", (0, 0), (-1, -1), 11),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def md_to_flowables(md_text: str, styles) -> list:
    """Convert a markdown string into a list of ReportLab flowables."""
    if not md_text or not md_text.strip():
        return [Paragraph("<i>No description</i>", styles["italic"])]

    html = markdown.markdown(md_text, extensions=["tables", "fenced_code"])
    flowables: list = []

    for block in _parse_html_blocks(html):
        stripped = block.strip()
        if not stripped:
            flowables.append(Spacer(1, 4))
            continue
        if stripped.startswith("<table"):
            flowables.append(_table_to_flowable(stripped, styles["body"]))
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
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A5,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )

    sample_styles = getSampleStyleSheet()
    styles = {
        "title": ParagraphStyle(
            "card_title",
            parent=sample_styles["Heading1"],
            fontSize=15,
            spaceAfter=4,
        ),
        "h1": ParagraphStyle(
            "md_h1",
            parent=sample_styles["Heading2"],
            fontSize=12,
            spaceAfter=4,
        ),
        "h2": ParagraphStyle(
            "md_h2",
            parent=sample_styles["Heading3"],
            fontSize=10,
            spaceAfter=3,
        ),
        "h3": ParagraphStyle(
            "md_h3",
            parent=sample_styles["Heading4"],
            fontSize=9,
            spaceAfter=3,
        ),
        "body": ParagraphStyle(
            "md_body",
            parent=sample_styles["BodyText"],
            fontSize=8,
            leading=11,
            spaceAfter=2,
        ),
        "italic": ParagraphStyle(
            "md_italic",
            parent=sample_styles["BodyText"],
            fontSize=8,
            leading=11,
            textColor=colors.grey,
        ),
        "code": ParagraphStyle(
            "md_code",
            parent=sample_styles["Code"],
            fontSize=7,
            leading=10,
            backColor=colors.Color(0.95, 0.95, 0.95),
        ),
        "label": ParagraphStyle(
            "label",
            parent=sample_styles["Normal"],
            fontSize=8,
            textColor=colors.Color(0.3, 0.3, 0.3),
            spaceAfter=6,
        ),
    }

    story: list = []

    for idx, card in enumerate(cards):
        # Title
        story.append(Paragraph(card["title"], styles["title"]))

        # Labels (plain text, emojis stripped for PDF rendering)
        labels = card.get("labels", [])
        if labels:
            names = [strip_emojis(l.get("title", "")).strip() for l in labels]
            names = [n for n in names if n]
            story.append(Paragraph("  ·  ".join(names), styles["label"]))
        else:
            story.append(Paragraph("<i>No labels</i>", styles["label"]))

        story.append(Spacer(1, 4 * mm))

        # Assigned users (if any)
        users = card.get("assignedUsers", [])
        if users:
            user_names = ", ".join(u.get("displayName", u.get("username", "?")) for u in users)
            story.append(Paragraph(
                f'<b>Assigned:</b> {user_names}',
                styles["label"],
            ))
            story.append(Spacer(1, 2 * mm))

        # Description (markdown → HTML → ReportLab), emojis stripped
        desc = strip_emojis(card.get("description", ""))
        story.extend(md_to_flowables(desc, styles))

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
        for card in stacks[sid].get("cards", []):
            card_label_ids = {lbl["id"] for lbl in card.get("labels", [])}
            if not selected_labels or card_label_ids & selected_labels or not card_label_ids:
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
