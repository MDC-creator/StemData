import pytest

from stemchub.naming import ImageRef, parse_image_path, parse_process_path


@pytest.mark.parametrize(
    "path, expected",
    [
        ("INDUZELL/U3/day05/New-05.czi", ImageRef("U3", 5, "New-05.czi")),
        ("/INDUZELL/u3/day5/a b.CZI", ImageRef("U3", 5, "a b.CZI")),
        ("INDUZELL/U1/day-02/x.czi", ImageRef("U1", -2, "x.czi")),
        ("INDUZELL/run_7-b/day10/x.czi", ImageRef("RUN_7-B", 10, "x.czi")),
    ],
)
def test_image_paths_following_the_rule(path, expected):
    assert parse_image_path(path, "INDUZELL") == expected


@pytest.mark.parametrize(
    "path",
    [
        "INDUZELL/U3/New-05.czi",  # no day folder
        "INDUZELL/U3/d05/New-05.czi",  # wrong day folder name
        "INDUZELL/U3/day05/New-05.tif",  # not a czi
        "OTHER/U3/day05/New-05.czi",  # outside the watched folder
        "INDUZELL/U3/day05/sub/New-05.czi",  # too deep
    ],
)
def test_image_paths_not_following_the_rule(path):
    assert parse_image_path(path, "INDUZELL") is None


def test_process_csv_path():
    assert parse_process_path("INDUZELL/u3/process.csv", "INDUZELL") == "U3"
    assert parse_process_path("INDUZELL/U3/day05/process.csv", "INDUZELL") is None
    assert parse_process_path("INDUZELL/exports/U3_results.csv", "INDUZELL") is None
