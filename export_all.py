"""Export every card from the standard Deck JSON export."""

from pathlib import Path

from deck import filter_cards, load_deck
from pfila_task_card_generator import build_pdf


BASE_DIR = Path(__file__).resolve().parent
INPUT_PATH = BASE_DIR / "data" / "Pfila 2027.json"
OUTPUT_PATH = BASE_DIR / "cards.pdf"


def main() -> None:
    board = load_deck(str(INPUT_PATH))
    stack_ids = [stack["id"] for stack in board.get("stacks", {}).values()]
    cards = filter_cards(board, stack_ids, [])
    if not cards:
        raise ValueError(f"No cards found in {INPUT_PATH}.")

    build_pdf(cards, str(OUTPUT_PATH))
    print(f"Exported {len(cards)} card(s) to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
