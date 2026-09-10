from importlib.resources import files


def test_package_imports_without_gpio() -> None:
    import sop
    import sop.panels.inky
    import sop.panels.waveshare

    assert sop.__version__
    assert files("sop").joinpath("py.typed").is_file()
