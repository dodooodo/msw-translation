import json
import os

CONFIG_FILE = "config.json"

DEFAULT_CONFIG = {
    "source_language":   "Korean",
    "target_language":   "Traditional Chinese",
    "translator_engine": "dummy",
    # font_size / text_color are kept for future manual-override UI;
    # current rendering derives both values from screenshot pixels automatically.
    "font_size":         26,
    "text_color":        "#FFE600",
    "ocr_interval":      1.0,
    "last_roi":          [],
    # OCR preprocessing / stabilization
    "min_confidence":    0.0,    # drop Vision OCR blocks below this confidence (0 = off)
    "min_text_length":   1,      # drop blocks shorter than this many characters (1 = off)
    "linger_frames":     3,      # ticks to ghost-render a block after OCR miss (3×0.2s ≈ 0.6s)
    "tracked_occlusion_threshold": 0.5,  # drop tracked block when newer OCR covers this fraction
    # Block merger thresholds
    "merge_max_height_ratio": 1.2,  # max row-height ratio to consider same font size
    "merge_gap_ratio":        0.8,  # vertical gap must be < avg_height × this value
    "merge_min_h_overlap":    0.3,  # horizontal overlap must be ≥ this fraction of the narrower block
    # Update tracking
    "community_glossary_seen_version": 0,  # last community glossary index version seen by user
    # Global hotkey (toggle pause from inside fullscreen games — pynput format)
    "hotkey_pause": "<ctrl>+<alt>+p",
    # Glossary fuzzy-match thresholds (used in Pass 2 of GlossaryService.protect)
    # Terms with length <= fuzzy_length_threshold use fuzzy_short_max_distance;
    # longer terms use fuzzy_long_max_distance.  Set either distance to 0 to
    # disable fuzzy matching for that class of terms.
    "fuzzy_length_threshold":    3,  # char-count boundary between "short" and "long" terms
    "fuzzy_short_max_distance":  1,  # max OCR errors allowed for short terms (≤ threshold)
    "fuzzy_long_max_distance":   2,  # max OCR errors allowed for long terms  (> threshold)
}

def load_config():
    if not os.path.exists(CONFIG_FILE):
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
            # 確保所有新的預設設定都有被載入
            for k, v in DEFAULT_CONFIG.items():
                if k not in config:
                    config[k] = v
            return config
    except Exception as e:
        print(f"載入設定檔失敗: {e}")
        return DEFAULT_CONFIG

def save_config(config):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"儲存設定檔失敗: {e}")
