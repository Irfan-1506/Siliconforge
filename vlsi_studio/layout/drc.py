"""SCMOS Lambda Design Rule Checker (DRC) for Magic-style layouts."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .layers import LAYER_MAP, LayoutCell, LayoutRect


@dataclass
class DRCViolation:
    rule: str
    layer: str
    message: str
    x1: int
    y1: int
    x2: int
    y2: int


def _rect_distance(a: LayoutRect, b: LayoutRect) -> float:
    dx = max(0, max(a.x1 - b.x2, b.x1 - a.x2))
    dy = max(0, max(a.y1 - b.y2, b.y1 - a.y2))
    return math.hypot(dx, dy)


def run_drc(cell: LayoutCell) -> list[DRCViolation]:
    """Run SCMOS width, spacing, and contact/via enclosure DRC checks."""
    violations: list[DRCViolation] = []
    by_layer: dict[str, list[LayoutRect]] = {}
    for r in cell.rects:
        if r.width <= 0 or r.height <= 0:
            continue
        by_layer.setdefault(r.layer, []).append(r)

    # 1. Minimum Width & Exact Cut Size
    for lname, rects in by_layer.items():
        ldef = LAYER_MAP.get(lname)
        if ldef is None:
            continue
        for r in rects:
            if ldef.exact_size is not None:
                if r.width != ldef.exact_size or r.height != ldef.exact_size:
                    violations.append(
                        DRCViolation(
                            rule="EXACT_SIZE",
                            layer=lname,
                            message=f"{ldef.display_name} must be exactly {ldef.exact_size}x{ldef.exact_size}λ (got {r.width}x{r.height}λ)",
                            x1=r.x1, y1=r.y1, x2=r.x2, y2=r.y2,
                        )
                    )
            else:
                min_dim = min(r.width, r.height)
                if min_dim < ldef.min_width:
                    violations.append(
                        DRCViolation(
                            rule="MIN_WIDTH",
                            layer=lname,
                            message=f"{ldef.display_name} width {min_dim}λ < minimum {ldef.min_width}λ",
                            x1=r.x1, y1=r.y1, x2=r.x2, y2=r.y2,
                        )
                    )

        # 2. Same-layer Minimum Spacing (for disjoint rectangles)
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                a, b = rects[i], rects[j]
                if a.overlaps_or_touches(b):
                    continue
                dist = _rect_distance(a, b)
                if dist < ldef.min_spacing:
                    violations.append(
                        DRCViolation(
                            rule="MIN_SPACING",
                            layer=lname,
                            message=f"{ldef.display_name} spacing {dist:.1f}λ < minimum {ldef.min_spacing}λ",
                            x1=min(a.x1, b.x1),
                            y1=min(a.y1, b.y1),
                            x2=max(a.x2, b.x2),
                            y2=max(a.y2, b.y2),
                        )
                    )

    # 3. Contact Enclosure: Metal1 >= 1λ AND (Poly or NDiff or PDiff) >= 1λ
    m1_rects = by_layer.get("metal1", [])
    m2_rects = by_layer.get("metal2", [])
    lower_conductors = by_layer.get("poly", []) + by_layer.get("ndiff", []) + by_layer.get("pdiff", [])

    for c in by_layer.get("contact", []):
        if not any(m.encloses(c, 1) for m in m1_rects):
            violations.append(
                DRCViolation(
                    rule="CONTACT_M1_ENC",
                    layer="contact",
                    message="Contact must be enclosed by Metal 1 by at least 1λ",
                    x1=c.x1, y1=c.y1, x2=c.x2, y2=c.y2,
                )
            )
        if not any(lc.encloses(c, 1) for lc in lower_conductors):
            violations.append(
                DRCViolation(
                    rule="CONTACT_ACTIVE_ENC",
                    layer="contact",
                    message="Contact must be enclosed by Poly, NDiff, or PDiff by at least 1λ",
                    x1=c.x1, y1=c.y1, x2=c.x2, y2=c.y2,
                )
            )

    # 4. Via Enclosure: Metal1 >= 1λ AND Metal2 >= 1λ
    for v in by_layer.get("via", []):
        if not any(m.encloses(v, 1) for m in m1_rects):
            violations.append(
                DRCViolation(
                    rule="VIA_M1_ENC",
                    layer="via",
                    message="Via must be enclosed by Metal 1 by at least 1λ",
                    x1=v.x1, y1=v.y1, x2=v.x2, y2=v.y2,
                )
            )
        if not any(m.encloses(v, 1) for m in m2_rects):
            violations.append(
                DRCViolation(
                    rule="VIA_M2_ENC",
                    layer="via",
                    message="Via must be enclosed by Metal 2 by at least 1λ",
                    x1=v.x1, y1=v.y1, x2=v.x2, y2=v.y2,
                )
            )

    return violations
