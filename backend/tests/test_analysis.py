import numpy as np
import pytest

from stemchub.analysis import (
    aggregate_footprint,
    analyze_live_dead,
    classic_segmenter,
    find_channels,
    max_projection,
    outline_overlay,
)

PIXEL_UM = 0.33
RADIUS_PX = 12  # ~8 µm nuclei


def disk(shape, cy, cx, r):
    yy, xx = np.ogrid[: shape[0], : shape[1]]
    return (yy - cy) ** 2 + (xx - cx) ** 2 <= r**2


def synthetic_stack(centres, dead_idx, z=3, shape=(200, 200), seed=0):
    """(C=2, Z, Y, X): Hoechst disks for every nucleus, EthD signal only in the dead ones; each nucleus in one z-plane."""
    rng = np.random.default_rng(seed)
    stack = rng.normal(100, 5, size=(2, z, *shape)).astype(np.float32)
    for i, (cy, cx) in enumerate(centres):
        m = disk(shape, cy, cx, RADIUS_PX)
        stack[0, i % z][m] += 2000
        if i in dead_idx:
            stack[1, i % z][m] += 1500
    return stack


CENTRES = [(40, 40), (40, 120), (110, 70), (160, 150), (150, 40)]


@pytest.mark.parametrize(
    "names, expected",
    [(["H3342", "EtHD12"], (0, 1)), (["EthD-1", "Hoechst"], (1, 0)), (["DAPI", "PI"], (0, 1)), (["C0", "C1"], (0, 1))],
)
def test_find_channels(names, expected):
    assert find_channels(names) == expected


def test_max_projection():
    stack = np.zeros((3, 4, 4))
    stack[1, 0, 0], stack[2, 3, 3] = 5, 7
    proj = max_projection(stack)
    assert proj.shape == (4, 4) and proj[0, 0] == 5 and proj[3, 3] == 7


def test_counts_nuclei_and_dead_cells():
    res = analyze_live_dead(
        synthetic_stack(CENTRES, dead_idx={1, 3}),
        ["H3342", "EtHD12"],
        PIXEL_UM,
        classic_segmenter,
        "classic",
        nucleus_diameter_um=2 * RADIUS_PX * PIXEL_UM,
    )
    assert res.nuclei_count == 5
    assert res.dead_count == 2
    assert res.dead_fraction == pytest.approx(0.4)
    expected_area = np.pi * RADIUS_PX**2 * PIXEL_UM**2
    assert res.mean_nucleus_area_um2 == pytest.approx(expected_area, rel=0.15)
    dead_centres = sorted((round(n.centroid_y), round(n.centroid_x)) for n in res.nuclei if n.dead)
    assert dead_centres == [(40, 120), (160, 150)]


def test_channel_order_does_not_matter():
    stack = synthetic_stack(CENTRES, dead_idx={0})[::-1]  # EthD first
    res = analyze_live_dead(stack, ["EtHD12", "H3342"], PIXEL_UM, classic_segmenter, "classic", 2 * RADIUS_PX * PIXEL_UM)
    assert (res.nuclei_count, res.dead_count) == (5, 1)


def test_empty_image_gives_zero_not_an_error():
    stack = np.full((2, 1, 64, 64), 100, dtype=np.float32)
    res = analyze_live_dead(stack, ["H3342", "EtHD12"], PIXEL_UM, lambda img, d: np.zeros(img.shape, np.int32), "none")
    assert (res.nuclei_count, res.dead_fraction, res.mean_nucleus_area_um2) == (0, 0.0, None)


def test_rejects_single_channel():
    with pytest.raises(ValueError, match="2 channels"):
        analyze_live_dead(np.zeros((1, 2, 8, 8)), ["H3342"], PIXEL_UM, classic_segmenter, "classic")


def test_overlay_colours_dead_and_alive():
    labels = np.zeros((20, 20), np.int32)
    labels[2:8, 2:8], labels[12:18, 12:18] = 1, 2
    rgba = outline_overlay(labels, dead_labels={2})
    assert tuple(rgba[2, 2]) == (60, 220, 120, 255)  # alive outline
    assert tuple(rgba[12, 12]) == (240, 60, 200, 255)  # dead outline
    assert rgba[5, 5, 3] == 0 and rgba[0, 0, 3] == 0  # inside and background transparent


def test_no_ethd_signal_means_no_dead_cells():
    """Regression: on the sample data the EthD channel is pure noise; a global Otsu threshold called ~60 % 'dead'."""
    stack = synthetic_stack(CENTRES, dead_idx=set())
    res = analyze_live_dead(stack, ["H3342", "EtHD12"], PIXEL_UM, classic_segmenter, "classic", 2 * RADIUS_PX * PIXEL_UM)
    assert res.nuclei_count == 5
    assert res.dead_count == 0


def test_slight_crosstalk_is_not_death():
    stack = synthetic_stack(CENTRES, dead_idx=set())
    stack[1] += 0.01 * stack[0]  # 1 % Hoechst crosstalk -> nuclei ~1.2x background (sample data: at most 1.13x)
    res = analyze_live_dead(stack, ["H3342", "EtHD12"], PIXEL_UM, classic_segmenter, "classic", 2 * RADIUS_PX * PIXEL_UM)
    assert res.dead_count == 0


def test_aggregate_footprint_covers_gaps_and_lumen():
    """A hollow aggregate: a ring of nuclei around an empty lumen counts with its full outline."""
    shape, ring_r, n = (240, 240), 70, 16
    labels = np.zeros(shape, np.int32)
    for i in range(n):
        a = 2 * np.pi * i / n
        labels[disk(shape, 120 + ring_r * np.sin(a), 120 + ring_r * np.cos(a), RADIUS_PX)] = i + 1
    area = aggregate_footprint(labels, 2 * RADIUS_PX).sum()
    outer = np.pi * (ring_r + RADIUS_PX) ** 2
    assert area == pytest.approx(outer, rel=0.12)
    assert area > 2.5 * (labels > 0).sum()  # far more than the nuclei alone (here 2.8x)


def test_aggregate_footprint_ignores_a_stray_nucleus():
    labels = np.zeros((100, 100), np.int32)
    labels[disk((100, 100), 50, 50, RADIUS_PX)] = 1
    assert not aggregate_footprint(labels, 2 * RADIUS_PX).any()
