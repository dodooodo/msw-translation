"""Tests for merge_blocks_by_proximity in block_merger.py."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from block_merger import merge_blocks_by_proximity
from ocr_model import OCRBlock


def block(x: float, y: float, w: float, h: float,
          text: str = "T",
          text_color: str = "#ffffff",
          bg_color:   str = "#000000") -> OCRBlock:
    return OCRBlock(text=text, bbox=(x, y, w, h),
                    text_color=text_color, bg_color=bg_color)


# ------------------------------------------------------------------
# Edge cases
# ------------------------------------------------------------------

def test_empty_input():
    assert merge_blocks_by_proximity([]) == []


def test_single_block_returned_unchanged():
    b = block(0, 0, 100, 20, text="hello")
    result = merge_blocks_by_proximity([b])
    assert len(result) == 1
    assert result[0].text == "hello"


def test_single_block_not_merged():
    b = block(0, 0, 100, 20)
    result = merge_blocks_by_proximity([b])
    assert not result[0].is_merged
    assert result[0].sub_bboxes == []


# ------------------------------------------------------------------
# Two blocks that DO merge
# ------------------------------------------------------------------

def _mergeable_pair():
    """Two blocks stacked vertically, same width, gap well within threshold."""
    # gap = 35 - 20 = 15; max_gap = 20 * 0.8 = 16 → merge
    a = block(10, 0,  100, 20, text="A")
    b = block(10, 35, 100, 20, text="B")
    return a, b


def test_two_blocks_merge():
    a, b = _mergeable_pair()
    result = merge_blocks_by_proximity([a, b])
    assert len(result) == 1
    assert result[0].is_merged


def test_merged_text_joined():
    a, b = _mergeable_pair()
    result = merge_blocks_by_proximity([a, b])
    assert result[0].text == "A B"


def test_merged_sub_bboxes_populated():
    a, b = _mergeable_pair()
    result = merge_blocks_by_proximity([a, b])
    m = result[0]
    assert len(m.sub_bboxes) == 2
    assert m.sub_bboxes[0] == a.bbox
    assert m.sub_bboxes[1] == b.bbox


def test_merged_sub_texts_populated():
    a, b = _mergeable_pair()
    result = merge_blocks_by_proximity([a, b])
    assert result[0].sub_texts == ["A", "B"]


def test_merged_block_bbox_encloses_both():
    # A: x 10..110, y 0..20  |  B: x 10..110, y 35..55
    a, b = _mergeable_pair()
    result = merge_blocks_by_proximity([a, b])
    mx, my, mw, mh = result[0].bbox
    assert mx == 10
    assert my == 0
    assert mx + mw == 110     # rightmost x
    assert my + mh == 55      # bottommost y


def test_merged_confidence_is_minimum():
    a = OCRBlock(text="A", bbox=(0, 0, 100, 20), conf=0.9)
    b = OCRBlock(text="B", bbox=(0, 35, 100, 20), conf=0.5)
    result = merge_blocks_by_proximity([a, b])
    assert result[0].conf == pytest.approx(0.5)


# ------------------------------------------------------------------
# Two blocks that do NOT merge
# ------------------------------------------------------------------

def test_gap_too_large():
    # gap = 50 - 20 = 30; max_gap = 20 * 0.8 = 16 → no merge
    a = block(10, 0,  100, 20)
    b = block(10, 50, 100, 20)
    result = merge_blocks_by_proximity([a, b])
    assert len(result) == 2


def test_height_ratio_too_large():
    # heights 20 vs 26 → ratio = 26/20 = 1.3 > 1.2 → no merge
    a = block(10, 0,  100, 20)
    b = block(10, 25, 100, 26)
    result = merge_blocks_by_proximity([a, b])
    assert len(result) == 2


def test_no_horizontal_overlap():
    # A ends at x=100, B starts at x=200 — completely to the right
    a = block(0,   0,  100, 20)
    b = block(200, 25, 100, 20)
    result = merge_blocks_by_proximity([a, b])
    assert len(result) == 2


# ------------------------------------------------------------------
# Overlap threshold boundary
# ------------------------------------------------------------------

def test_overlap_at_exactly_30_percent_merges():
    # A: x 0..100  |  B: x 70..170  → overlap=30, min_w=100 → 30% ≥ 30% → merge
    a = block(0,  0,  100, 20)
    b = block(70, 25, 100, 20)
    result = merge_blocks_by_proximity([a, b])
    assert len(result) == 1


def test_overlap_below_30_percent_does_not_merge():
    # A: x 0..100  |  B: x 71..171  → overlap=29, min_w=100 → 29% < 30% → no merge
    a = block(0,  0,  100, 20)
    b = block(71, 25, 100, 20)
    result = merge_blocks_by_proximity([a, b])
    assert len(result) == 2


# ------------------------------------------------------------------
# Three blocks chain
# ------------------------------------------------------------------

def test_three_blocks_merge_into_one():
    # All three satisfy merge conditions pairwise
    a = block(10, 0,  100, 20, text="A")
    b = block(10, 35, 100, 20, text="B")
    c = block(10, 70, 100, 20, text="C")
    result = merge_blocks_by_proximity([a, b, c])
    assert len(result) == 1
    assert len(result[0].sub_bboxes) == 3
    assert result[0].text == "A B C"


def test_middle_block_breaks_chain():
    # A and B merge, but C has a large gap from B → two groups
    a = block(10, 0,  100, 20, text="A")
    b = block(10, 35, 100, 20, text="B")
    c = block(10, 200, 100, 20, text="C")   # large gap from B
    result = merge_blocks_by_proximity([a, b, c])
    assert len(result) == 2
    assert result[0].text == "A B"
    assert result[1].text == "C"


# ------------------------------------------------------------------
# Color propagation
# ------------------------------------------------------------------

def test_color_propagation():
    a = block(10, 0,  100, 20, text_color="#ff0000", bg_color="#000000")
    b = block(10, 35, 100, 20, text_color="#00ff00", bg_color="#111111")
    result = merge_blocks_by_proximity([a, b])
    colors = result[0].sub_colors
    assert colors[0] == ("#ff0000", "#000000")
    assert colors[1] == ("#00ff00", "#111111")


# needed for approx
import pytest
