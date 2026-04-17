"""
block_merger.py
Merges vertically adjacent OCR blocks that belong to the same sentence.
Pure Python — no Qt, no Quartz, no platform dependencies.
"""

from ocr_model import OCRBlock


def merge_blocks_by_proximity(
    blocks: list[OCRBlock],
    gap_ratio: float = 0.8,
    max_height_ratio: float = 1.2,
    min_h_overlap: float = 0.3,
) -> list[OCRBlock]:
    """
    Group vertically adjacent OCR blocks into sentences and return one
    merged OCRBlock per group.

    Merge conditions (all three must hold):
      1. Font size similar: row-height ratio < max_height_ratio
      2. Vertical gap small: gap < average row height × gap_ratio
      3. Horizontal overlap sufficient: overlap ≥ min_h_overlap fraction of the narrower block's width
         (prevents left/right separate UI elements from being joined)

    Merged blocks carry sub_bboxes / sub_texts / sub_colors so the renderer
    can align each translated line to its original row position.
    Single-block groups leave those fields as empty lists.
    """
    if not blocks:
        return blocks

    sorted_blocks = sorted(blocks, key=lambda b: b.bbox[1])
    groups: list[list[OCRBlock]] = []
    current: list[OCRBlock] = [sorted_blocks[0]]

    for block in sorted_blocks[1:]:
        prev = current[-1]
        _, _, pw, ph = prev.bbox
        _, _, bw, bh = block.bbox

        # Condition 1 — similar font size
        h_ratio = max(ph, bh) / max(min(ph, bh), 1)
        same_size = h_ratio < max_height_ratio

        # Condition 2 — close vertically
        prev_bottom = prev.bbox[1] + ph
        gap = block.bbox[1] - prev_bottom
        close_enough = gap < (ph + bh) / 2 * gap_ratio

        # Condition 3 — horizontal overlap
        x1s, x1e = prev.bbox[0],  prev.bbox[0] + pw
        x2s, x2e = block.bbox[0], block.bbox[0] + bw
        overlap   = min(x1e, x2e) - max(x1s, x2s)
        h_overlap = overlap / max(min(pw, bw), 1) >= min_h_overlap

        if same_size and close_enough and h_overlap:
            current.append(block)
        else:
            groups.append(current)
            current = [block]
    groups.append(current)

    merged: list[OCRBlock] = []
    for group in groups:
        if len(group) == 1:
            merged.append(group[0])
            continue

        all_x  = [b.bbox[0]              for b in group]
        all_y  = [b.bbox[1]              for b in group]
        all_x2 = [b.bbox[0] + b.bbox[2]  for b in group]
        all_y2 = [b.bbox[1] + b.bbox[3]  for b in group]

        combined = OCRBlock(
            text       = " ".join(b.text for b in group),
            bbox       = (min(all_x), min(all_y),
                          max(all_x2) - min(all_x),
                          max(all_y2) - min(all_y)),
            conf       = min(b.conf for b in group),
            text_color = group[0].text_color,
            bg_color   = group[0].bg_color,
            sub_bboxes = [b.bbox for b in group],
            sub_texts  = [b.text for b in group],
            sub_colors = [(b.text_color, b.bg_color) for b in group],
        )
        merged.append(combined)

    return merged
