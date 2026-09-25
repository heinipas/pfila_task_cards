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

1. A native macOS file picker opens — select your Deck JSON export
2. Pick which **stacks** and **labels** to include (Enter = all)
3. A native macOS folder picker opens — choose where to save the PDF

The [Noto Emoji](https://github.com/googlefonts/noto-emoji) font is downloaded automatically on first run (~1.3 MB) so that emojis render correctly in the PDF. If the download fails, emojis are silently stripped.
