"""Live/dead analysis of a two-channel confocal stack (Hoechst 33342 = all nuclei, EthD = dead cells).

Pure numpy / scikit-image: no OMERO or database code here, so it can be unit-tested with synthetic images.

Steps:
  1. maximum-intensity projection over z for each channel
  2. segment nuclei in the Hoechst projection (Cellpose "nuclei" model, or a classic fallback)
  3. per nucleus: area, centroid, mean Hoechst and EthD intensity
  4. a nucleus counts as dead if its mean EthD intensity clearly stands out from the EthD background
     (measured outside the nuclei): at least `ethd_min_z` robust SDs above it AND `ethd_min_ratio` × brighter.
     A global Otsu threshold is NOT used: when a sample has no dead cells, the EthD channel is pure noise
     and Otsu would still split it in two, calling ~half of all nuclei "dead" (seen on the sample data).

Known limitation: a max projection merges nuclei that lie on top of each other in z, so counts in thick
aggregates are underestimated. A 3D segmentation is a later improvement.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage as ndi
from skimage import feature, filters, measure, morphology, segmentation

Segmenter = Callable[[np.ndarray, float], np.ndarray]  # (2D image, nucleus diameter in px) -> label image


@dataclass
class NucleusFeatures:
    label: int
    area_um2: float
    centroid_x: float
    centroid_y: float
    hoechst_mean: float
    ethd_mean: float
    dead: bool


@dataclass
class AnalysisResult:
    nuclei: list[NucleusFeatures]
    labels: np.ndarray
    ethd_threshold: float
    aggregate_area_um2: float
    segmenter: str
    hoechst_projection: np.ndarray = field(repr=False)

    @property
    def nuclei_count(self) -> int:
        return len(self.nuclei)

    @property
    def dead_count(self) -> int:
        return sum(n.dead for n in self.nuclei)

    @property
    def dead_fraction(self) -> float:
        return self.dead_count / self.nuclei_count if self.nuclei else 0.0

    @property
    def mean_nucleus_area_um2(self) -> float | None:
        return float(np.mean([n.area_um2 for n in self.nuclei])) if self.nuclei else None


def find_channels(names: list[str]) -> tuple[int, int]:
    """Index of the nuclear (Hoechst/DAPI) and the dead-cell (EthD/PI) channel; falls back to 0 and 1."""
    lowered = [n.lower() for n in names]
    nuc = next((i for i, n in enumerate(lowered) if any(k in n for k in ("h33", "hoechst", "dapi"))), 0)
    dead = next((i for i, n in enumerate(lowered) if any(k in n for k in ("ethd", "eth", "pi", "propidium"))), None)
    if dead is None or dead == nuc:
        dead = 1 if nuc == 0 else 0
    return nuc, dead


def max_projection(stack: np.ndarray) -> np.ndarray:
    """(Z, Y, X) or (Y, X) -> (Y, X) float32."""
    arr = np.asarray(stack, dtype=np.float32)
    return arr.max(axis=0) if arr.ndim == 3 else arr


def classic_segmenter(image: np.ndarray, diameter_px: float) -> np.ndarray:
    """Otsu threshold + distance-transform watershed. Fast, no model download; less accurate than Cellpose."""
    smoothed = filters.gaussian(image, sigma=max(diameter_px / 10, 1))
    mask = smoothed > filters.threshold_otsu(smoothed)
    mask = morphology.remove_small_objects(mask, max_size=int(np.pi * (diameter_px / 4) ** 2))  # drops specks
    distance = ndi.distance_transform_edt(mask)
    peaks = feature.peak_local_max(distance, min_distance=max(int(diameter_px / 3), 2), labels=measure.label(mask))
    markers = np.zeros_like(mask, dtype=np.int32)
    markers[tuple(peaks.T)] = np.arange(1, len(peaks) + 1)
    return segmentation.watershed(-distance, markers, mask=mask).astype(np.int32)


def cellpose_segmenter() -> Segmenter:
    """Loads the Cellpose 3 'nuclei' model once and returns a segmenter function."""
    from cellpose import models  # heavy import, only in the worker image

    model = models.Cellpose(gpu=False, model_type="nuclei")

    def run(image: np.ndarray, diameter_px: float) -> np.ndarray:
        masks, _flows, _styles, _diams = model.eval(image, diameter=diameter_px, channels=[0, 0])
        return np.asarray(masks, dtype=np.int32)

    return run


def aggregate_footprint(labels: np.ndarray, diameter_px: float) -> np.ndarray:
    """Outline of the aggregate(s): nuclei joined across the gaps between them, inside filled (incl. a lumen)."""
    nuclei = labels > 0
    if not nuclei.any():
        return nuclei
    radius = max(int(round(diameter_px)), 1)
    padded = np.pad(nuclei, radius)  # so closing also works for aggregates touching the image border
    closed = morphology.closing(padded, morphology.disk(radius))[radius:-radius, radius:-radius]
    filled = ndi.binary_fill_holes(closed)
    return morphology.remove_small_objects(filled, max_size=int(3 * np.pi * (diameter_px / 2) ** 2))  # stray nuclei


def ethd_dead_threshold(ethd: np.ndarray, labels: np.ndarray, min_z: float, min_ratio: float) -> float:
    """EthD level a nucleus must exceed to count as dead, from the background outside all nuclei."""
    background = ethd[labels == 0] if (labels == 0).any() else ethd.ravel()
    median = float(np.median(background))
    mad_sd = float(np.median(np.abs(background - median)) * 1.4826)  # robust standard deviation
    return median + max(min_z * mad_sd, (min_ratio - 1.0) * median)


def analyze_live_dead(
    stack: np.ndarray,
    channel_names: list[str],
    pixel_size_um: float,
    segmenter: Segmenter,
    segmenter_name: str,
    nucleus_diameter_um: float = 10.0,
    ethd_min_z: float = 6.0,
    ethd_min_ratio: float = 1.5,
) -> AnalysisResult:
    """stack: (C, Z, Y, X) or (C, Y, X)."""
    if stack.ndim not in (3, 4) or stack.shape[0] < 2:
        raise ValueError(f"expected a stack with at least 2 channels, got shape {stack.shape}")
    nuc_c, dead_c = find_channels(channel_names)
    hoechst = max_projection(stack[nuc_c])
    ethd = max_projection(stack[dead_c])

    diameter_px = nucleus_diameter_um / pixel_size_um
    labels = segmenter(hoechst, diameter_px)
    ethd_threshold = ethd_dead_threshold(ethd, labels, ethd_min_z, ethd_min_ratio)
    pixel_area = pixel_size_um**2

    nuclei = []
    for region in measure.regionprops(labels, intensity_image=np.stack([hoechst, ethd], axis=-1)):
        hoechst_mean, ethd_mean = (float(v) for v in region.intensity_mean)
        cy, cx = region.centroid
        nuclei.append(
            NucleusFeatures(
                label=int(region.label),
                area_um2=float(region.area * pixel_area),
                centroid_x=float(cx),
                centroid_y=float(cy),
                hoechst_mean=hoechst_mean,
                ethd_mean=ethd_mean,
                dead=ethd_mean > ethd_threshold,
            )
        )

    footprint = aggregate_footprint(labels, diameter_px)
    return AnalysisResult(
        nuclei=nuclei,
        labels=labels,
        ethd_threshold=ethd_threshold,
        aggregate_area_um2=float(footprint.sum() * pixel_area),
        segmenter=segmenter_name,
        hoechst_projection=hoechst,
    )


def outline_overlay(labels: np.ndarray, dead_labels: set[int]) -> np.ndarray:
    """RGBA image (uint8) with nucleus outlines: green = alive, magenta = dead. Transparent elsewhere."""
    boundaries = segmentation.find_boundaries(labels, mode="inner")
    rgba = np.zeros((*labels.shape, 4), dtype=np.uint8)
    dead_mask = np.isin(labels, list(dead_labels)) if dead_labels else np.zeros_like(boundaries)
    rgba[boundaries & ~dead_mask] = (60, 220, 120, 255)
    rgba[boundaries & dead_mask] = (240, 60, 200, 255)
    return rgba
