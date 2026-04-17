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
    # Block merger thresholds
    "merge_max_height_ratio": 1.2,  # max row-height ratio to consider same font size
    "merge_gap_ratio":        0.8,  # vertical gap must be < avg_height × this value
    "merge_min_h_overlap":    0.3,  # horizontal overlap must be ≥ this fraction of the narrower block
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
