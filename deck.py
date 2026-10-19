"""Nextcloud Deck JSON loading and card filtering."""

import json


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
    for label in board.get("labels", []):
        labels[label["id"]] = label
    for stack in board.get("stacks", {}).values():
        for card in stack.get("cards", []):
            for label in card.get("labels", []):
                if label["id"] not in labels:
                    labels[label["id"]] = label
    return labels


def filter_cards(board: dict, stack_ids: list[int], label_ids: list[int]) -> list[dict]:
    """
    Return cards in the selected stacks with at least one selected label.
    Cards without labels remain included when labels are selected.
    """
    selected_stacks = set(stack_ids)
    selected_labels = set(label_ids)
    result: list[dict] = []

    stacks = board.get("stacks", {})
    for stack_id in sorted(stacks, key=lambda key: stacks[key].get("order", 0)):
        if int(stack_id) not in selected_stacks:
            continue
        stack = stacks[stack_id]
        stack_title = stack.get("title", "")
        for card in stack.get("cards", []):
            card_label_ids = {label["id"] for label in card.get("labels", [])}
            if (
                not selected_labels
                or card_label_ids & selected_labels
                or not card_label_ids
            ):
                card["_stack_title"] = stack_title
                result.append(card)
    return result
