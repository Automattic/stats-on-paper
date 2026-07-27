def test_package_imports_without_gpio() -> None:
    import jsp
    import jsp.panels.inky
    import jsp.panels.waveshare

    assert jsp.__version__
