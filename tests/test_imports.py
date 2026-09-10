from importlib.resources import files
from pathlib import Path


def test_package_imports_without_gpio() -> None:
    import sop
    import sop.panels.inky
    import sop.panels.waveshare

    assert sop.__version__
    assert files("sop").joinpath("py.typed").is_file()


def test_runtime_brand_assets_are_available() -> None:
    packaged = files("sop").joinpath("assets", "logos")
    repository = Path(__file__).parents[1] / "assets" / "logos"

    for filename in ("jetpack-mark.png", "parsely-mark.png"):
        assert (
            packaged.joinpath(filename).is_file()
            or repository.joinpath(filename).is_file()
        )
