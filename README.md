# pfila_task_cards

Export Nextcloud Deck task cards as a printable PDF (one page per card).

## Install

```bash
pip install reportlab markdown
```

## Run

```bash
python pfila_task_card_generator.py
```

1. A native file picker opens — select your Deck JSON export
2. Pick which **stacks** and **labels** to include (Enter = all)
3. A native folder picker opens — choose where to save the PDF

To export every card from the standard `data/Pfila 2027.json` file directly
to `cards.pdf`, run:

```bash
python export_all.py
```

The [Noto Emoji](https://github.com/googlefonts/noto-emoji) font is downloaded automatically on first run (~1.3 MB) so that emojis render correctly in the PDF. If the download fails, emojis are silently stripped.

## Configuration

The settings are intentionally kept in a small Python file for this private
helper. Edit the commented `CONFIG = RenderConfig()` section in
[config.py](./config.py) to customize:

- A4/A5 page size, margins, and optional even-page padding for duplex printing
- Base font size and relative title/heading/code/checkbox/footer sizing
- Relative spacing after metadata, before/after headings, and after paragraphs
- Vector checkbox rendering (`enabled = True`) or preserved Markdown task-list
  markers (`enabled = False`)
- Emoji rendering and whether the missing font may be downloaded
- Automatic table column sizing, header shading, repeated headers, and the
  compact empty-header workaround
- Metadata visibility and labels
- Footer visibility, card title/page number, font size, and bottom offset

The defaults preserve the existing output style.

On macOS the native file and folder pickers are used. On Windows and Linux,
the script uses Tk's native dialogs when available and falls back to the
command-line prompts when Tk or a graphical display is unavailable.
