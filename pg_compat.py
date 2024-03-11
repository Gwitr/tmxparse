"""Extra classes for Pygame compatibility"""

from __future__ import annotations

try:
    import pygame
except ImportError:
    raise ImportError("The tmxparse.pg_compat module requires Pygame to be installed") from None
import pygame.freetype as ft

from . import tmx

class PygameLoader(tmx.BaseLoader):
    """Pygame-aware TMX loader"""

    def __init__(self, convert_alpha: bool = True):
        self.convert_alpha = convert_alpha

    def load_image(self, path: str) -> pygame.Surface:
        img = pygame.image.load(path)
        if self.convert_alpha:
            return img.convert_alpha()
        return img

    def load_font(self, family: str, size: float) -> ft.SysFont:
        return ft.SysFont(family, size)

@PygameLoader.register
class Tile(tmx.Tile):
    """Extra Pygame-related functionality for the base Tile class"""

    @property
    def surface(self) -> pygame.Surface:
        """Fetches the Pygame graphic of the tile"""
        if self.tileset is None:
            return None
        return self.tileset.img.surface.subsurface(self.rect)
