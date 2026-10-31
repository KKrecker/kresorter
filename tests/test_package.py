import safeclean


def test_version_is_exposed() -> None:
    assert safeclean.__version__ == "0.0.1"
