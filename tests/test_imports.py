from importlib.resources import files
from pathlib import Path


def test_package_imports_without_gpio() -> None:
    import jsp
    import jsp.panels.inky
    import jsp.panels.waveshare

    assert jsp.__version__
    assert files("jsp").joinpath("py.typed").is_file()


def test_runtime_brand_assets_are_available() -> None:
    packaged = files("jsp").joinpath("assets", "logos")
    repository = Path(__file__).parents[1] / "assets" / "logos"

    for filename in ("jetpack-mark.png", "parsely-mark.png"):
        assert (
            packaged.joinpath(filename).is_file()
            or repository.joinpath(filename).is_file()
        )
