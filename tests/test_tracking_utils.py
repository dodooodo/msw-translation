"""Tests for pure OCR tracking helpers."""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from ocr_model import OCRBlock
from tracking_utils import (
    bbox_overlap_ratio,
    is_occluded,
    is_same_track,
    should_drop_tracked_block,
)


def test_bbox_overlap_ratio_uses_reference_area():
    old_bbox = (0, 0, 100, 40)
    new_bbox = (0, 0, 200, 40)

    assert bbox_overlap_ratio(old_bbox, new_bbox) == 1.0


def test_is_occluded_true_when_new_bbox_covers_old_bbox():
    old_bbox = (10, 10, 100, 30)
    current_bboxes = [(0, 0, 150, 60)]

    assert is_occluded(old_bbox, current_bboxes)


def test_is_occluded_false_for_small_overlap():
    old_bbox = (0, 0, 100, 40)
    current_bboxes = [(80, 0, 100, 40)]

    assert not is_occluded(old_bbox, current_bboxes)


def test_is_same_track_for_small_ocr_jitter():
    assert is_same_track(
        (10, 10, 100, 30),
        "스타포스",
        (12, 9, 100, 30),
        "스타포쓰",
    )


def test_should_drop_tracked_block_when_new_text_occludes_old_one():
    tracked = OCRBlock(text="舊文字", bbox=(10, 10, 100, 30))
    current_blocks = [OCRBlock(text="新文字", bbox=(0, 0, 140, 60))]

    assert should_drop_tracked_block(tracked, current_blocks)


def test_should_not_drop_tracked_block_when_same_track_is_present():
    tracked = OCRBlock(text="스타포스", bbox=(10, 10, 100, 30))
    current_blocks = [OCRBlock(text="스타포쓰", bbox=(12, 9, 100, 30))]

    assert not should_drop_tracked_block(tracked, current_blocks)


def test_should_not_drop_tracked_block_when_new_block_is_elsewhere():
    tracked = OCRBlock(text="舊文字", bbox=(10, 10, 100, 30))
    current_blocks = [OCRBlock(text="別處文字", bbox=(250, 10, 100, 30))]

    assert not should_drop_tracked_block(tracked, current_blocks)
