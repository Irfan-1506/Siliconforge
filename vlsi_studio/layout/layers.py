"""SCMOS/Magic technology layers and layout geometry primitives (in lambda units)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class LayerDef:
    name: str
    display_name: str
    color_hex: str
    alpha: int
    z_order: int
    hatch: str  # "solid", "diag", "cross", "dense"
    min_width: int
    min_spacing: int
    exact_size: int | None = None


LAYERS: list[LayerDef] = [
    LayerDef("nwell", "N-Well", "#2D6A4F", 90, 1, "diag", min_width=10, min_spacing=6),
    LayerDef("pwell", "P-Well", "#7F4F24", 80, 2, "diag", min_width=10, min_spacing=6),
    LayerDef("ndiff", "N-Diffusion", "#22C55E", 160, 3, "solid", min_width=3, min_spacing=3),
    LayerDef("pdiff", "P-Diffusion", "#D97706", 160, 4, "solid", min_width=3, min_spacing=3),
    LayerDef("poly", "Polysilicon", "#EF4444", 180, 5, "solid", min_width=2, min_spacing=2),
    LayerDef("metal1", "Metal 1", "#3B82F6", 170, 6, "diag", min_width=3, min_spacing=3),
    LayerDef("metal2", "Metal 2", "#A855F7", 170, 7, "diag", min_width=3, min_spacing=3),
    LayerDef("contact", "Contact (M1-Poly/Diff)", "#E5E7EB", 220, 8, "cross", min_width=2, min_spacing=2, exact_size=2),
    LayerDef("via", "Via (M1-M2)", "#FACC15", 220, 9, "cross", min_width=2, min_spacing=2, exact_size=2),
]

LAYER_MAP: dict[str, LayerDef] = {layer.name: layer for layer in LAYERS}


@dataclass
class LayoutRect:
    layer: str
    x1: int
    y1: int
    x2: int
    y2: int

    def __post_init__(self) -> None:
        if self.x1 > self.x2:
            self.x1, self.x2 = self.x2, self.x1
        if self.y1 > self.y2:
            self.y1, self.y2 = self.y2, self.y1

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        return self.y2 - self.y1

    def overlaps_or_touches(self, other: LayoutRect) -> bool:
        return not (self.x2 < other.x1 or other.x2 < self.x1 or self.y2 < other.y1 or other.y2 < self.y1)

    def strictly_overlaps(self, other: LayoutRect) -> bool:
        return not (self.x2 <= other.x1 or other.x2 <= self.x1 or self.y2 <= other.y1 or other.y2 <= self.y1)

    def encloses(self, inner: LayoutRect, margin: int = 1) -> bool:
        return (
            self.x1 + margin <= inner.x1
            and self.y1 + margin <= inner.y1
            and self.x2 - margin >= inner.x2
            and self.y2 - margin >= inner.y2
        )


@dataclass
class LayoutLabel:
    text: str
    layer: str
    x: int
    y: int


@dataclass
class LayoutCell:
    name: str = "untitled"
    rects: list[LayoutRect] = field(default_factory=list)
    labels: list[LayoutLabel] = field(default_factory=list)
