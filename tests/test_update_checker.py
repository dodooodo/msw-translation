from update_checker import _version_tuple


def test_strips_v_prefix():
    assert _version_tuple("v0.2.1") == (0, 2, 1)


def test_without_prefix():
    assert _version_tuple("0.2.1") == (0, 2, 1)


def test_major_minor_patch():
    assert _version_tuple("1.2.3") == (1, 2, 3)


def test_two_component_version():
    assert _version_tuple("1.0") == (1, 0)


def test_non_numeric_segments_filtered():
    assert _version_tuple("v1.2.alpha") == (1, 2)


def test_newer_version_compares_greater():
    assert _version_tuple("0.2.0") > _version_tuple("0.1.9")


def test_older_patch_compares_less():
    assert _version_tuple("0.1.0") < _version_tuple("0.1.1")


def test_equal_versions():
    assert _version_tuple("1.0.0") == _version_tuple("1.0.0")


def test_v_prefix_matches_bare():
    assert _version_tuple("v1.0.0") == _version_tuple("1.0.0")
