"""Small cross-platform input and selection helpers."""

import os
import platform
import subprocess


def pick_file_macos() -> str | None:
    """Use the macOS native dialog via osascript to pick a file."""
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


def pick_file_gui() -> str | None:
    """Use Tk's native file dialog on Windows and Linux."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        return None

    try:
        root = tk.Tk()
    except tk.TclError:
        return None
    root.withdraw()
    try:
        return filedialog.askopenfilename(
            title="Select Nextcloud Deck JSON export",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        ) or None
    finally:
        root.destroy()


def pick_file_cli() -> str | None:
    """Prompt the user to type or paste a file path."""
    path = input("Path to Nextcloud Deck JSON file: ").strip().strip('"').strip("'")
    return path if path else None


def pick_file() -> str | None:
    """Try a native file dialog, falling back to a CLI prompt."""
    if platform.system() == "Darwin":
        result = pick_file_macos()
    else:
        result = pick_file_gui()
    return result or pick_file_cli()


def pick_folder_macos() -> str | None:
    """Use the macOS native dialog via osascript to pick a folder."""
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


def pick_folder_gui() -> str | None:
    """Use Tk's native folder dialog on Windows and Linux."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        return None

    try:
        root = tk.Tk()
    except tk.TclError:
        return None
    root.withdraw()
    try:
        return filedialog.askdirectory(
            title="Select output folder for PDF",
        ) or None
    finally:
        root.destroy()


def pick_folder(default_name: str) -> str | None:
    """Ask for an output path using a native dialog where available."""
    if platform.system() == "Darwin":
        folder = pick_folder_macos()
    else:
        folder = pick_folder_gui()
    if folder:
        return os.path.join(folder, default_name)

    out = input(f"Output PDF path [{default_name}]: ").strip()
    return out if out else default_name


def ask_multiselect(options: list[str], prompt: str) -> list[int]:
    """
    Show a numbered list and let the user pick items.
    Returns list of 0-based indices. Empty input selects all.
    """
    print(f"\n{prompt}")
    print("-" * len(prompt))
    for i, option in enumerate(options, 1):
        print(f"  {i}. {option}")
    print()
    raw = input("Enter numbers separated by commas (empty = all): ").strip()
    if not raw:
        return list(range(len(options)))
    indices: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            index = int(part) - 1
            if 0 <= index < len(options):
                indices.append(index)
    return indices if indices else list(range(len(options)))
