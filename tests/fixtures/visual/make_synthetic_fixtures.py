"""Synthetic fixture generator for visual forensics testing.

This module creates synthetic figure images with known panel layouts and
copy-move relationships for testing panel extraction and copy-move detection.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw


def make_panel_content(
    width: int = 200,
    height: int = 150,
    color: tuple[int, int, int] = (100, 150, 200),
    pattern: str = "solid",
    seed: int = 0,
) -> Image.Image:
    """Create a panel image with a known pattern.

    Args:
        width: Panel width
        height: Panel height
        color: Base color (RGB)
        pattern: Pattern type ("solid", "gradient", "dots", "lines", "checkerboard")
        seed: Random seed for pattern variation

    Returns:
        PIL Image with the pattern
    """
    img = Image.new("RGB", (width, height), color)
    draw = ImageDraw.Draw(img)

    if pattern == "solid":
        # Solid color - simplest and most reliable for detection
        pass
    elif pattern == "gradient":
        # Create a gradient pattern
        for y in range(height):
            intensity = int(255 * y / height)
            draw.line([(0, y), (width, y)], fill=(intensity, intensity, intensity))
    elif pattern == "dots":
        # Create a dot pattern
        for x in range(10, width, 20):
            for y in range(10, height, 20):
                radius = 3 + (seed % 5)
                draw.ellipse(
                    [x - radius, y - radius, x + radius, y + radius],
                    fill=(255, 255, 255),
                )
    elif pattern == "lines":
        # Create a line pattern
        for y in range(0, height, 15):
            draw.line([(0, y), (width, y)], fill=(255, 255, 255), width=2)
    elif pattern == "checkerboard":
        # Create a checkerboard pattern
        cell_size = 20
        for x in range(0, width, cell_size):
            for y in range(0, height, cell_size):
                if ((x // cell_size) + (y // cell_size)) % 2 == 0:
                    draw.rectangle(
                        [x, y, x + cell_size, y + cell_size], fill=(255, 255, 255)
                    )

    return img


def make_2x2_panel_figure(
    output_path: Path,
    size: tuple[int, int] = (800, 600),
    panel_contents: list[Image.Image] | None = None,
    border_color: tuple[int, int, int] = (0, 0, 0),
    border_width: int = 25,
) -> Path:
    """Create a 2x2 panel figure with clear black borders.

    Args:
        output_path: Output file path
        size: Figure size (width, height)
        panel_contents: List of 4 panel images. If None, creates default patterns.
        border_color: Border color (RGB)
        border_width: Border width in pixels

    Returns:
        Path to created figure
    """
    width, height = size
    img = Image.new("RGB", size, border_color)

    # Calculate panel dimensions
    panel_width = (width - 3 * border_width) // 2
    panel_height = (height - 3 * border_width) // 2

    # Create default panel contents if not provided
    if panel_contents is None:
        panel_contents = [
            make_panel_content(panel_width, panel_height, (100, 150, 200), "solid", 0),
            make_panel_content(panel_width, panel_height, (150, 100, 200), "solid", 1),
            make_panel_content(panel_width, panel_height, (200, 150, 100), "solid", 2),
            make_panel_content(panel_width, panel_height, (150, 200, 100), "solid", 3),
        ]

    # Place panels in 2x2 grid
    positions = [
        (border_width, border_width),  # Top-left
        (2 * border_width + panel_width, border_width),  # Top-right
        (border_width, 2 * border_width + panel_height),  # Bottom-left
        (
            2 * border_width + panel_width,
            2 * border_width + panel_height,
        ),  # Bottom-right
    ]

    for i, (panel, (x, y)) in enumerate(zip(panel_contents, positions)):
        # Resize panel to fit
        resized = panel.resize((panel_width, panel_height))
        img.paste(resized, (x, y))

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path)
    return output_path


def make_3x1_panel_figure(
    output_path: Path,
    size: tuple[int, int] = (900, 300),
    panel_contents: list[Image.Image] | None = None,
    border_color: tuple[int, int, int] = (0, 0, 0),
    border_width: int = 25,
) -> Path:
    """Create a 3x1 panel figure (3 panels in a row).

    Args:
        output_path: Output file path
        size: Figure size (width, height)
        panel_contents: List of 3 panel images. If None, creates default patterns.
        border_color: Border color (RGB)
        border_width: Border width in pixels

    Returns:
        Path to created figure
    """
    width, height = size
    img = Image.new("RGB", size, border_color)

    # Calculate panel dimensions
    panel_width = (width - 4 * border_width) // 3
    panel_height = height - 2 * border_width

    # Create default panel contents if not provided
    if panel_contents is None:
        panel_contents = [
            make_panel_content(panel_width, panel_height, (100, 150, 200), "solid", 0),
            make_panel_content(panel_width, panel_height, (150, 100, 200), "solid", 1),
            make_panel_content(panel_width, panel_height, (200, 150, 100), "solid", 2),
        ]

    # Place panels in 1x3 grid
    positions = [
        (border_width, border_width),
        (2 * border_width + panel_width, border_width),
        (3 * border_width + 2 * panel_width, border_width),
    ]

    for i, (panel, (x, y)) in enumerate(zip(panel_contents, positions)):
        resized = panel.resize((panel_width, panel_height))
        img.paste(resized, (x, y))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path)
    return output_path


def make_panel_copy(
    source_panel: Image.Image,
    transform: str = "exact",
    scale_factor: float = 1.0,
    rotation_angle: float = 0.0,
    brightness_factor: float = 1.0,
) -> Image.Image:
    """Apply a known transform to a panel for copy-move testing.

    Args:
        source_panel: Source panel image
        transform: Transform type ("exact", "scaled", "rotated", "brightness")
        scale_factor: Scale factor for "scaled" transform
        rotation_angle: Rotation angle in degrees for "rotated" transform
        brightness_factor: Brightness factor for "brightness" transform

    Returns:
        Transformed panel image
    """
    if transform == "exact":
        return source_panel.copy()
    elif transform == "scaled":
        new_size = (
            int(source_panel.width * scale_factor),
            int(source_panel.height * scale_factor),
        )
        return source_panel.resize(new_size)
    elif transform == "rotated":
        return source_panel.rotate(rotation_angle, expand=True)
    elif transform == "brightness":
        from PIL import ImageEnhance

        enhancer = ImageEnhance.Brightness(source_panel)
        return enhancer.enhance(brightness_factor)
    else:
        raise ValueError(f"Unknown transform: {transform}")


def make_fixture_with_known_copies(
    output_dir: Path,
    copy_type: str = "exact",
) -> dict[str, Any]:
    """Create a complete fixture with known copy-move relationships.

    Args:
        output_dir: Output directory for fixture
        copy_type: Type of copy ("exact", "scaled", "rotated", "brightness")

    Returns:
        Ground truth dictionary with expected panels and relationships
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    images_dir = output_dir / "images"
    images_dir.mkdir(exist_ok=True)

    # Create source panel
    source_panel = make_panel_content(200, 150, (100, 150, 200), "solid", 42)

    # Create figure 1 with 2 panels
    figure1_panels = [
        source_panel,
        make_panel_content(200, 150, (150, 100, 200), "solid", 1),
    ]
    make_2x2_panel_figure(
        images_dir / "Figure1.png",
        panel_contents=figure1_panels
        + [  # Fill remaining 2 slots
            make_panel_content(200, 150, (200, 150, 100), "solid", 2),
            make_panel_content(200, 150, (150, 200, 100), "solid", 3),
        ],
    )

    # Create copied panel
    copied_panel = make_panel_copy(
        source_panel,
        transform=copy_type,
        scale_factor=0.8 if copy_type == "scaled" else 1.0,
        rotation_angle=90 if copy_type == "rotated" else 0.0,
        brightness_factor=1.3 if copy_type == "brightness" else 1.0,
    )

    # Create figure 2 with 2 panels (one is a copy)
    figure2_panels = [
        make_panel_content(200, 150, (100, 200, 150), "solid", 4),
        copied_panel,  # This is a copy of the source panel
    ]
    make_2x2_panel_figure(
        images_dir / "Figure2.png",
        panel_contents=figure2_panels
        + [  # Fill remaining 2 slots
            make_panel_content(200, 150, (200, 100, 150), "solid", 5),
            make_panel_content(200, 150, (150, 150, 200), "solid", 6),
        ],
    )

    # Create ground truth
    ground_truth = {
        "schema_version": "1.0",
        "fixture_type": f"synthetic_copy_{copy_type}",
        "figures": [
            {
                "figure_id": "FE-0001",
                "source_image_path": "images/Figure1.png",
                "label": "Figure 1",
                "expected_panels": 4,
                "panels": [
                    {"panel_id": "PE-0001-01", "label": "a", "is_source": True},
                    {"panel_id": "PE-0001-02", "label": "b", "is_source": False},
                    {"panel_id": "PE-0001-03", "label": "c", "is_source": False},
                    {"panel_id": "PE-0001-04", "label": "d", "is_source": False},
                ],
            },
            {
                "figure_id": "FE-0002",
                "source_image_path": "images/Figure2.png",
                "label": "Figure 2",
                "expected_panels": 4,
                "panels": [
                    {"panel_id": "PE-0002-01", "label": "a", "is_source": False},
                    {
                        "panel_id": "PE-0002-02",
                        "label": "b",
                        "is_copy": True,
                        "copy_source": "PE-0001-01",
                    },
                    {"panel_id": "PE-0002-03", "label": "c", "is_source": False},
                    {"panel_id": "PE-0002-04", "label": "d", "is_source": False},
                ],
            },
        ],
        "expected_relationships": [
            {
                "source_panel_id": "PE-0001-01",
                "target_panel_id": "PE-0002-02",
                "source_type": "copy_move_cross",
                "copy_type": copy_type,
            }
        ],
    }

    # Write ground truth
    ground_truth_path = output_dir / "ground_truth.json"
    ground_truth_path.write_text(json.dumps(ground_truth, indent=2))

    return ground_truth


def make_clean_fixture(output_dir: Path) -> dict[str, Any]:
    """Create a clean fixture with no copies (negative control).

    Args:
        output_dir: Output directory for fixture

    Returns:
        Ground truth dictionary
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    images_dir = output_dir / "images"
    images_dir.mkdir(exist_ok=True)

    # Create 2 figures with unique panels
    figure1_panels = [
        make_panel_content(200, 150, (100, 150, 200), "solid", 0),
        make_panel_content(200, 150, (150, 100, 200), "solid", 1),
        make_panel_content(200, 150, (200, 150, 100), "solid", 2),
        make_panel_content(200, 150, (150, 200, 100), "solid", 3),
    ]
    make_2x2_panel_figure(images_dir / "Figure1.png", panel_contents=figure1_panels)

    figure2_panels = [
        make_panel_content(200, 150, (100, 200, 150), "solid", 4),
        make_panel_content(200, 150, (200, 100, 150), "solid", 5),
        make_panel_content(200, 150, (150, 150, 200), "solid", 6),
        make_panel_content(200, 150, (200, 200, 100), "solid", 7),
    ]
    make_2x2_panel_figure(images_dir / "Figure2.png", panel_contents=figure2_panels)

    # Create ground truth
    ground_truth = {
        "schema_version": "1.0",
        "fixture_type": "synthetic_2x2_clean",
        "figures": [
            {
                "figure_id": "FE-0001",
                "source_image_path": "images/Figure1.png",
                "label": "Figure 1",
                "expected_panels": 4,
                "panels": [
                    {"panel_id": "PE-0001-01", "label": "a", "is_source": True},
                    {"panel_id": "PE-0001-02", "label": "b", "is_source": True},
                    {"panel_id": "PE-0001-03", "label": "c", "is_source": True},
                    {"panel_id": "PE-0001-04", "label": "d", "is_source": True},
                ],
            },
            {
                "figure_id": "FE-0002",
                "source_image_path": "images/Figure2.png",
                "label": "Figure 2",
                "expected_panels": 4,
                "panels": [
                    {"panel_id": "PE-0002-01", "label": "a", "is_source": True},
                    {"panel_id": "PE-0002-02", "label": "b", "is_source": True},
                    {"panel_id": "PE-0002-03", "label": "c", "is_source": True},
                    {"panel_id": "PE-0002-04", "label": "d", "is_source": True},
                ],
            },
        ],
        "expected_relationships": [],  # No copies
    }

    ground_truth_path = output_dir / "ground_truth.json"
    ground_truth_path.write_text(json.dumps(ground_truth, indent=2))

    return ground_truth


def _make_textured_panel(
    width: int,
    height: int,
    seed: int = 0,
) -> Image.Image:
    """Create a textured panel with pseudo-random dots for overlap detection.

    Uses deterministic positioning so the same seed always produces the same
    texture, making it suitable for keypoint-based detection.
    """
    import hashlib

    img = Image.new("RGB", (width, height), (40, 40, 40))
    draw = ImageDraw.Draw(img)
    rng_seed = int(hashlib.md5(str(seed).encode()).hexdigest()[:8], 16) % (2**31)

    for i in range(80):
        rng_seed = (rng_seed * 1103515245 + 12345) % (2**31)
        x = rng_seed % width
        rng_seed = (rng_seed * 1103515245 + 12345) % (2**31)
        y = rng_seed % height
        rng_seed = (rng_seed * 1103515245 + 12345) % (2**31)
        r = 2 + rng_seed % 6
        rng_seed = (rng_seed * 1103515245 + 12345) % (2**31)
        c = 100 + rng_seed % 156
        rng_seed = (rng_seed * 1103515245 + 12345) % (2**31)
        c2 = 100 + rng_seed % 156
        rng_seed = (rng_seed * 1103515245 + 12345) % (2**31)
        c3 = 100 + rng_seed % 156
        draw.ellipse([x - r, y - r, x + r, y + r], fill=(c, c2, c3))

    for i in range(0, width, 12):
        rng_seed = (rng_seed * 1103515245 + 12345) % (2**31)
        v = 60 + rng_seed % 100
        draw.line([(i, 0), (i, height)], fill=(v, v, v), width=1)

    return img


def make_overlap_crop_fixture(output_dir: Path) -> dict[str, Any]:
    """Create a fixture where a crop from panel_a appears in panel_b.

    A 120x90 sub-region from the centre of panel_a is pasted into a
    different position in panel_b, simulating partial panel reuse.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    images_dir = output_dir / "images"
    images_dir.mkdir(exist_ok=True)

    panel_a = _make_textured_panel(300, 240, seed=100)
    crop_box = (80, 60, 200, 170)
    crop_region = panel_a.crop(crop_box)

    panel_b_base = _make_textured_panel(300, 240, seed=200)
    paste_pos = (30, 40)
    panel_b = panel_b_base.copy()
    panel_b.paste(crop_region, paste_pos)

    panel_a.save(images_dir / "panel_a.png")
    panel_b.save(images_dir / "panel_b.png")

    src_poly = [
        [crop_box[0], crop_box[1]],
        [crop_box[2], crop_box[1]],
        [crop_box[2], crop_box[3]],
        [crop_box[0], crop_box[3]],
    ]
    tgt_poly = [
        [paste_pos[0], paste_pos[1]],
        [paste_pos[0] + crop_region.width, paste_pos[1]],
        [paste_pos[0] + crop_region.width, paste_pos[1] + crop_region.height],
        [paste_pos[0], paste_pos[1] + crop_region.height],
    ]

    crop_area = crop_region.width * crop_region.height
    gt: dict[str, Any] = {
        "schema_version": "1.0",
        "fixture_type": "synthetic_overlap_crop",
        "expected_overlap": True,
        "expected_transform_type": "translation",
        "expected_overlap_area_ratio_source": round(
            crop_area / (panel_a.width * panel_a.height), 4
        ),
        "expected_overlap_area_ratio_target": round(
            crop_area / (panel_b.width * panel_b.height), 4
        ),
        "ground_truth_polygon_source": src_poly,
        "ground_truth_polygon_target": tgt_poly,
        "panels": {
            "panel_a": {"width": panel_a.width, "height": panel_a.height},
            "panel_b": {"width": panel_b.width, "height": panel_b.height},
        },
    }
    (output_dir / "ground_truth.json").write_text(json.dumps(gt, indent=2))
    return gt


def make_overlap_scale_fixture(output_dir: Path) -> dict[str, Any]:
    """Create a fixture where a sub-region from panel_a is scaled and pasted into panel_b."""
    output_dir.mkdir(parents=True, exist_ok=True)
    images_dir = output_dir / "images"
    images_dir.mkdir(exist_ok=True)

    panel_a = _make_textured_panel(300, 240, seed=300)
    crop_box = (60, 50, 220, 190)
    crop_region = panel_a.crop(crop_box)

    scale = 0.6
    scaled = crop_region.resize(
        (int(crop_region.width * scale), int(crop_region.height * scale))
    )

    panel_b_base = _make_textured_panel(300, 240, seed=400)
    paste_pos = (50, 60)
    panel_b = panel_b_base.copy()
    panel_b.paste(scaled, paste_pos)

    panel_a.save(images_dir / "panel_a.png")
    panel_b.save(images_dir / "panel_b.png")

    src_poly = [
        [crop_box[0], crop_box[1]],
        [crop_box[2], crop_box[1]],
        [crop_box[2], crop_box[3]],
        [crop_box[0], crop_box[3]],
    ]
    tgt_poly = [
        [paste_pos[0], paste_pos[1]],
        [paste_pos[0] + scaled.width, paste_pos[1]],
        [paste_pos[0] + scaled.width, paste_pos[1] + scaled.height],
        [paste_pos[0], paste_pos[1] + scaled.height],
    ]
    scaled_area = scaled.width * scaled.height
    gt: dict[str, Any] = {
        "schema_version": "1.0",
        "fixture_type": "synthetic_overlap_scale",
        "expected_overlap": True,
        "expected_transform_type": "affine_scale",
        "scale_factor": scale,
        "expected_overlap_area_ratio_source": round(
            scaled_area / (panel_a.width * panel_a.height), 4
        ),
        "expected_overlap_area_ratio_target": round(
            scaled_area / (panel_b.width * panel_b.height), 4
        ),
        "ground_truth_polygon_source": src_poly,
        "ground_truth_polygon_target": tgt_poly,
        "panels": {
            "panel_a": {"width": panel_a.width, "height": panel_a.height},
            "panel_b": {"width": panel_b.width, "height": panel_b.height},
        },
    }
    (output_dir / "ground_truth.json").write_text(json.dumps(gt, indent=2))
    return gt


def make_overlap_flip_fixture(output_dir: Path) -> dict[str, Any]:
    """Create a fixture where a sub-region from panel_a is horizontally flipped and pasted into panel_b."""
    output_dir.mkdir(parents=True, exist_ok=True)
    images_dir = output_dir / "images"
    images_dir.mkdir(exist_ok=True)

    panel_a = _make_textured_panel(300, 240, seed=500)
    crop_box = (70, 50, 230, 190)
    crop_region = panel_a.crop(crop_box)

    flipped = crop_region.transpose(Image.FLIP_LEFT_RIGHT)

    panel_b_base = _make_textured_panel(300, 240, seed=600)
    paste_pos = (40, 40)
    panel_b = panel_b_base.copy()
    panel_b.paste(flipped, paste_pos)

    panel_a.save(images_dir / "panel_a.png")
    panel_b.save(images_dir / "panel_b.png")

    src_poly = [
        [crop_box[0], crop_box[1]],
        [crop_box[2], crop_box[1]],
        [crop_box[2], crop_box[3]],
        [crop_box[0], crop_box[3]],
    ]
    tgt_poly = [
        [paste_pos[0], paste_pos[1]],
        [paste_pos[0] + flipped.width, paste_pos[1]],
        [paste_pos[0] + flipped.width, paste_pos[1] + flipped.height],
        [paste_pos[0], paste_pos[1] + flipped.height],
    ]
    flip_area = flipped.width * flipped.height
    gt: dict[str, Any] = {
        "schema_version": "1.0",
        "fixture_type": "synthetic_overlap_flip",
        "expected_overlap": True,
        "expected_transform_type": "flip_horizontal",
        "expected_overlap_area_ratio_source": round(
            flip_area / (panel_a.width * panel_a.height), 4
        ),
        "expected_overlap_area_ratio_target": round(
            flip_area / (panel_b.width * panel_b.height), 4
        ),
        "ground_truth_polygon_source": src_poly,
        "ground_truth_polygon_target": tgt_poly,
        "panels": {
            "panel_a": {"width": panel_a.width, "height": panel_a.height},
            "panel_b": {"width": panel_b.width, "height": panel_b.height},
        },
    }
    (output_dir / "ground_truth.json").write_text(json.dumps(gt, indent=2))
    return gt


def make_overlap_negative_similar_fixture(output_dir: Path) -> dict[str, Any]:
    """Create a negative fixture: two panels with similar structure but NO actual pixel overlap.

    Both panels use the same dot-line texture template with different seeds,
    simulating two images from the same experimental protocol (e.g. similar
    gel layout) but with genuinely different content.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    images_dir = output_dir / "images"
    images_dir.mkdir(exist_ok=True)

    panel_a = _make_textured_panel(300, 240, seed=700)
    panel_b = _make_textured_panel(300, 240, seed=701)

    panel_a.save(images_dir / "panel_a.png")
    panel_b.save(images_dir / "panel_b.png")

    gt: dict[str, Any] = {
        "schema_version": "1.0",
        "fixture_type": "synthetic_overlap_negative_similar",
        "expected_overlap": False,
        "expected_transform_type": None,
        "expected_overlap_area_ratio_source": 0.0,
        "expected_overlap_area_ratio_target": 0.0,
        "ground_truth_polygon_source": [],
        "ground_truth_polygon_target": [],
        "panels": {
            "panel_a": {"width": panel_a.width, "height": panel_a.height},
            "panel_b": {"width": panel_b.width, "height": panel_b.height},
        },
    }
    (output_dir / "ground_truth.json").write_text(json.dumps(gt, indent=2))
    return gt


def make_overlap_negative_low_texture_fixture(output_dir: Path) -> dict[str, Any]:
    """Create a negative fixture: two low-texture panels (near-solid backgrounds).

    Keypoint detectors should produce very few matches on these.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    images_dir = output_dir / "images"
    images_dir.mkdir(exist_ok=True)

    panel_a = Image.new("RGB", (300, 240), (128, 130, 132))
    draw_a = ImageDraw.Draw(panel_a)
    for y in range(0, 240, 40):
        draw_a.line([(0, y), (300, y)], fill=(132, 134, 136), width=1)
    panel_b = Image.new("RGB", (300, 240), (130, 128, 132))
    draw_b = ImageDraw.Draw(panel_b)
    for y in range(0, 240, 40):
        draw_b.line([(0, y), (300, y)], fill=(134, 132, 136), width=1)

    panel_a.save(images_dir / "panel_a.png")
    panel_b.save(images_dir / "panel_b.png")

    gt: dict[str, Any] = {
        "schema_version": "1.0",
        "fixture_type": "synthetic_overlap_negative_low_texture",
        "expected_overlap": False,
        "expected_transform_type": None,
        "expected_overlap_area_ratio_source": 0.0,
        "expected_overlap_area_ratio_target": 0.0,
        "ground_truth_polygon_source": [],
        "ground_truth_polygon_target": [],
        "panels": {
            "panel_a": {"width": panel_a.width, "height": panel_a.height},
            "panel_b": {"width": panel_b.width, "height": panel_b.height},
        },
    }
    (output_dir / "ground_truth.json").write_text(json.dumps(gt, indent=2))
    return gt


def generate_all_fixtures(base_dir: Path) -> list[dict[str, Any]]:
    """Generate all synthetic fixtures.

    Args:
        base_dir: Base directory for fixtures

    Returns:
        List of ground truth dictionaries
    """
    fixtures = []

    # Clean fixture (negative control)
    fixtures.append(make_clean_fixture(base_dir / "synthetic_2x2_clean"))

    # Copy fixtures (positive controls)
    fixtures.append(
        make_fixture_with_known_copies(base_dir / "synthetic_copy_exact", "exact")
    )
    fixtures.append(
        make_fixture_with_known_copies(base_dir / "synthetic_copy_scaled", "scaled")
    )
    fixtures.append(
        make_fixture_with_known_copies(base_dir / "synthetic_copy_rotated", "rotated")
    )
    fixtures.append(
        make_fixture_with_known_copies(
            base_dir / "synthetic_copy_brightness", "brightness"
        )
    )

    # Overlap fixtures (positive controls)
    fixtures.append(make_overlap_crop_fixture(base_dir / "synthetic_overlap_crop"))
    fixtures.append(make_overlap_scale_fixture(base_dir / "synthetic_overlap_scale"))
    fixtures.append(make_overlap_flip_fixture(base_dir / "synthetic_overlap_flip"))

    # Overlap negative fixtures
    fixtures.append(
        make_overlap_negative_similar_fixture(
            base_dir / "synthetic_overlap_negative_similar"
        )
    )
    fixtures.append(
        make_overlap_negative_low_texture_fixture(
            base_dir / "synthetic_overlap_negative_low_texture"
        )
    )

    return fixtures


if __name__ == "__main__":
    import sys

    output_dir = (
        Path(sys.argv[1]) if len(sys.argv) > 1 else Path("tests/fixtures/visual")
    )
    fixtures = generate_all_fixtures(output_dir)
    print(f"Generated {len(fixtures)} synthetic fixtures in {output_dir}")
    for fixture in fixtures:
        print(f"  - {fixture['fixture_type']}")
