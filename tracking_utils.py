"""Pure helpers for OCR bbox tracking and ghost suppression."""

from ocr_model import OCRBlock


def bbox_iou(b1: tuple, b2: tuple) -> float:
    """Intersection-over-Union for (x, y, w, h) bounding boxes."""
    x1, y1, w1, h1 = b1
    x2, y2, w2, h2 = b2
    ix = max(0.0, min(x1 + w1, x2 + w2) - max(x1, x2))
    iy = max(0.0, min(y1 + h1, y2 + h2) - max(y1, y2))
    inter = ix * iy
    union = w1 * h1 + w2 * h2 - inter
    return inter / union if union > 0 else 0.0


def bbox_overlap_ratio(reference_bbox: tuple, other_bbox: tuple) -> float:
    """Return how much of reference_bbox is covered by other_bbox."""
    x1, y1, w1, h1 = reference_bbox
    x2, y2, w2, h2 = other_bbox
    ix = max(0.0, min(x1 + w1, x2 + w2) - max(x1, x2))
    iy = max(0.0, min(y1 + h1, y2 + h2) - max(y1, y2))
    inter = ix * iy
    area = w1 * h1
    return inter / area if area > 0 else 0.0


def edit_distance(s1: str, s2: str) -> int:
    """Levenshtein distance; clamps at 2 for fast rejection."""
    if abs(len(s1) - len(s2)) >= 2:
        return 2
    dp = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1, 1):
        prev, dp[0] = dp[0], i
        for j, c2 in enumerate(s2, 1):
            prev, dp[j] = dp[j], prev if c1 == c2 else 1 + min(prev, dp[j], dp[j - 1])
    return dp[len(s2)]


def is_same_track(current_bbox: tuple,
                  current_text: str,
                  tracked_bbox: tuple,
                  tracked_text: str,
                  iou_threshold: float = 0.8,
                  max_edit_distance: int = 1) -> bool:
    """True when two OCR observations should be treated as the same tracked block."""
    return (
        bbox_iou(current_bbox, tracked_bbox) > iou_threshold
        and edit_distance(current_text, tracked_text) <= max_edit_distance
    )


def is_occluded(reference_bbox: tuple,
                current_bboxes: list[tuple],
                threshold: float = 0.5) -> bool:
    """True when any current bbox covers enough of the reference bbox."""
    return any(
        bbox_overlap_ratio(reference_bbox, current_bbox) >= threshold
        for current_bbox in current_bboxes
    )


def should_drop_tracked_block(tracked: OCRBlock,
                              current_blocks: list[OCRBlock],
                              occlusion_threshold: float = 0.5) -> bool:
    """True when a tracked block has been superseded by new OCR content."""
    for current in current_blocks:
        if is_same_track(current.bbox, current.text, tracked.bbox, tracked.text):
            return False
        if bbox_overlap_ratio(tracked.bbox, current.bbox) >= occlusion_threshold:
            return True
    return False
