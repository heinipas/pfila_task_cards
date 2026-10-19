"""Editable PDF rendering configuration."""

from dataclasses import dataclass, field


@dataclass
class PageConfig:
    # Select the paper size used for each PDF page.
    # Supported values: "A4", "A5"
    size: str = "A5"
    margin_left_mm: float = 12
    margin_right_mm: float = 15
    margin_top_mm: float = 10
    margin_bottom_mm: float = 10
    # Add blank pages so every card starts on a fresh sheet when duplex printing.
    even_pages_per_card: bool = False


@dataclass
class TypographyConfig:
    base_size: float = 9
    title_scale: float = 1.4
    heading_1_scale: float = 1.2
    heading_2_scale: float = 1.1
    heading_3_scale: float = 1.1
    code_scale: float = 0.85
    line_spacing: float = 1.1
    # Vertical spacing is expressed as multiples of base_size.
    metadata_gap_scale: float = 0.0
    heading_before_scale: float = 1.0
    heading_after_scale: float = 0.7
    paragraph_after_scale: float = 0.0


@dataclass
class CheckboxConfig:
    # Draw vector checkboxes for Markdown task lists when enabled.
    # When disabled, the original "- [ ]" and "- [x]" markers are preserved.
    enabled: bool = True
    # Checkbox side length as a multiple of TypographyConfig.base_size.
    size_scale: float = 0.8


@dataclass
class EmojiConfig:
    # Render emojis with the local/downloaded Noto Emoji font when enabled.
    enabled: bool = True
    # Download the font automatically when it is not already in the fonts folder.
    download_if_missing: bool = True


@dataclass
class TableConfig:
    automatic_column_widths: bool = True
    shade_header: bool = True
    repeat_headers: bool = True
    compact_empty_header: bool = True
    # Compensate for the text baseline so cell content appears vertically centered.
    cell_top_padding_scale: float = 0.25
    cell_bottom_padding_scale: float = 0.55


@dataclass
class MetadataConfig:
    show_labels: bool = True
    show_status: bool = True
    show_assignees: bool = True
    labels_title: str = "Bereich"
    status_title: str = "Status"
    assignees_title: str = "Zugewiesen an"
    missing_value: str = "—"


@dataclass
class FooterConfig:
    enabled: bool = True
    show_card_title: bool = True
    show_page_number: bool = True
    # Footer font size as a multiple of TypographyConfig.base_size.
    font_scale: float = 0.8
    bottom_offset_mm: float = 10


@dataclass
class RenderConfig:
    page: PageConfig = field(default_factory=PageConfig)
    typography: TypographyConfig = field(default_factory=TypographyConfig)
    checkbox: CheckboxConfig = field(default_factory=CheckboxConfig)
    emoji: EmojiConfig = field(default_factory=EmojiConfig)
    table: TableConfig = field(default_factory=TableConfig)
    metadata: MetadataConfig = field(default_factory=MetadataConfig)
    footer: FooterConfig = field(default_factory=FooterConfig)


# Edit this object to customize the generated PDF.
CONFIG = RenderConfig()
