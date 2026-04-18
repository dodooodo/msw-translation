import json

import config_manager
from config_manager import DEFAULT_CONFIG, load_config, save_config


class TestLoadConfig:
    def test_returns_defaults_when_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config_manager, "CONFIG_FILE", str(tmp_path / "config.json"))
        result = load_config()
        assert result["source_language"] == "Korean"
        assert result["translator_engine"] == "dummy"

    def test_creates_file_when_missing(self, tmp_path, monkeypatch):
        path = tmp_path / "config.json"
        monkeypatch.setattr(config_manager, "CONFIG_FILE", str(path))
        load_config()
        assert path.exists()

    def test_all_default_keys_present_on_fresh_load(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config_manager, "CONFIG_FILE", str(tmp_path / "config.json"))
        result = load_config()
        for k in DEFAULT_CONFIG:
            assert k in result

    def test_loads_existing_value(self, tmp_path, monkeypatch):
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"source_language": "Japanese"}), encoding="utf-8")
        monkeypatch.setattr(config_manager, "CONFIG_FILE", str(path))
        result = load_config()
        assert result["source_language"] == "Japanese"

    def test_merges_missing_keys_from_defaults(self, tmp_path, monkeypatch):
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"source_language": "Japanese"}), encoding="utf-8")
        monkeypatch.setattr(config_manager, "CONFIG_FILE", str(path))
        result = load_config()
        for k in DEFAULT_CONFIG:
            assert k in result

    def test_existing_key_not_overwritten_by_default(self, tmp_path, monkeypatch):
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"ocr_interval": 2.5}), encoding="utf-8")
        monkeypatch.setattr(config_manager, "CONFIG_FILE", str(path))
        result = load_config()
        assert result["ocr_interval"] == 2.5

    def test_malformed_json_returns_defaults(self, tmp_path, monkeypatch):
        path = tmp_path / "config.json"
        path.write_text("not valid json!!!", encoding="utf-8")
        monkeypatch.setattr(config_manager, "CONFIG_FILE", str(path))
        result = load_config()
        assert result == DEFAULT_CONFIG


class TestSaveConfig:
    def test_creates_file(self, tmp_path, monkeypatch):
        path = tmp_path / "config.json"
        monkeypatch.setattr(config_manager, "CONFIG_FILE", str(path))
        save_config({"source_language": "English"})
        assert path.exists()

    def test_written_as_valid_json(self, tmp_path, monkeypatch):
        path = tmp_path / "config.json"
        monkeypatch.setattr(config_manager, "CONFIG_FILE", str(path))
        save_config({"source_language": "English", "ocr_interval": 1.5})
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded["source_language"] == "English"
        assert loaded["ocr_interval"] == 1.5

    def test_roundtrip(self, tmp_path, monkeypatch):
        path = tmp_path / "config.json"
        monkeypatch.setattr(config_manager, "CONFIG_FILE", str(path))
        cfg = dict(DEFAULT_CONFIG)
        cfg["source_language"] = "Japanese"
        save_config(cfg)
        monkeypatch.setattr(config_manager, "CONFIG_FILE", str(path))
        loaded = load_config()
        assert loaded["source_language"] == "Japanese"
        assert loaded["translator_engine"] == cfg["translator_engine"]
