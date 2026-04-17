"""
ocr_model.py
Shared data model for the entire OCR → translate → render pipeline.
No external dependencies — safe to import from any module.
"""

from dataclasses import dataclass, field


@dataclass
class OCRBlock:
    """A single detected text region, flowing through every pipeline stage."""

    text: str
    bbox: tuple[float, float, float, float]   # (x, y, w, h) in logical pixels

    conf: float = 1.0           # OCR confidence [0.0, 1.0]
    text_color: str = "#ffffff" # sampled from screenshot (macOS only)
    bg_color:   str = "#000000" # sampled from screenshot (macOS only)
    translated: str = ""        # filled by TranslationPipeline

    # Populated by block_merger when multiple raw OCR lines are joined into one
    # sentence. Empty lists mean this is a single unmerged block.
    sub_bboxes: list[tuple[float, float, float, float]] = field(default_factory=list)
    sub_texts:  list[str]                                = field(default_factory=list)
    sub_colors: list[tuple[str, str]]                   = field(default_factory=list)

    @property
    def is_merged(self) -> bool:
        """True when this block was created by merging multiple OCR lines."""
        return len(self.sub_bboxes) > 1
