# Adding a New Translation Engine

All engine logic lives in `translator_engine.py`. No other file needs to change.

## Steps

### 1. Add a translation function

```python
# translator_engine.py

def _translate_myengine(texts: list[str], source_lang: str, target_lang: str) -> list[str]:
    """
    Translate `texts` from source_lang to target_lang.
    Must return a list of the same length as `texts`, in the same order.
    On any error, return the original texts as fallback.
    """
    try:
        # ... call your API ...
        return results
    except Exception as e:
        print(f"[MyEngine] Error: {e}")
        return texts   # always return something
```

### 2. Wire it in `engine_translate`

```python
def engine_translate(texts: list[str], config: dict) -> list[str]:
    engine = config.get("translator_engine", "dummy")
    ...
    if engine == "myengine":
        return _translate_myengine(texts, source_lang, target_lang)
    ...
```

### 3. Expose it in the settings UI

In `settings_ui.py`, add to the `engine_combo` item list and both maps:

```python
self.engine_combo.addItems([
    "Dummy (測試用不翻譯)",
    "Apple 翻譯 (macOS 內建)",
    "Windows 翻譯 (系統內建)",
    "Google Translate",
    "My Engine",          # ← add here
])
engine_map = {"dummy": 0, "apple": 1, "windows": 2, "google": 3, "myengine": 4}
```

And in `_save_and_close`:

```python
engine_rev_map = {0: "dummy", 1: "apple", 2: "windows", 3: "google", 4: "myengine"}
```

## Rules

- `engine_translate` receives the **protected text** (glossary placeholders
  already inserted). Do not strip or modify `__T0__`-style tokens.
- Always return a list of exactly `len(texts)` strings.
- On failure, return the originals — never raise an exception out of the function.
- The function is called from a background daemon thread; blocking I/O is fine.
