from ocr_model import OCRBlock


def test_default_values():
    b = OCRBlock(text="hello", bbox=(0, 0, 100, 30))
    assert b.conf == 1.0
    assert b.text_color == "#ffffff"
    assert b.bg_color == "#000000"
    assert b.translated == ""
    assert b.sub_bboxes == []
    assert b.sub_texts == []
    assert b.sub_colors == []


def test_is_merged_no_subs():
    b = OCRBlock(text="hello", bbox=(0, 0, 100, 30))
    assert b.is_merged is False


def test_is_merged_one_sub():
    b = OCRBlock(text="hello", bbox=(0, 0, 100, 30), sub_bboxes=[(0, 0, 100, 30)])
    assert b.is_merged is False


def test_is_merged_two_subs():
    b = OCRBlock(
        text="hello world",
        bbox=(0, 0, 200, 30),
        sub_bboxes=[(0, 0, 100, 30), (100, 0, 100, 30)],
    )
    assert b.is_merged is True


def test_explicit_field_values():
    b = OCRBlock(
        text="테스트",
        bbox=(10, 20, 80, 25),
        conf=0.95,
        text_color="#FFE600",
        bg_color="#1a1a1a",
        translated="Test",
    )
    assert b.text == "테스트"
    assert b.conf == 0.95
    assert b.text_color == "#FFE600"
    assert b.translated == "Test"
