"""Extra classes for Pygame compatibility, as well as some convenience functionality"""

from __future__ import annotations

import math

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

@PygameLoader.register
class Map(tmx.Map):
    """Extra Pygame-related functionality for the base Map class"""

    def render(self, rect: tuple[int, int, int, int] | None = None,
               to: pygame.Surface | None = None) -> pygame.Surface:
        """Render an image or subimage of the map"""
        if rect is None:
            rect = [0, 0, self.width * self.tilewidth, self.height * self.tileheight]
        rect = pygame.Rect(rect)
        if to is None:
            to = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
        for layer in self.layers:
            if isinstance(layer, TileLayer) and layer.visible:
                layer.render(rect, to)
        return to

@PygameLoader.register
class TileLayer(tmx.TileLayer):
    """Extra Pygame-related functionality for the base TileLayer class"""

    def render(self, rect: tuple[int, int, int, int] | None = None,
               to: pygame.Surface | None = None) -> pygame.Surface:
        """Render an image or subimage of the layer"""
        if rect is None:
            rect = [0, 0, self.width * self.map.tilewidth, self.height * self.map.tileheight]
        rect = pygame.Rect(rect)
        if to is None:
            to = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)

        tilex1 = max(0, rect.x // self.map.tilewidth)
        tiley1 = max(0, rect.y // self.map.tileheight)
        tilex2 = min(self.width-1, int(math.ceil((rect.x + rect.w) / self.map.tilewidth)))
        tiley2 = min(self.height-1, int(math.ceil((rect.y + rect.h) / self.map.tileheight)))
        for y in range(tiley1, tiley2+1):
            for x in range(tilex1, tilex2+1):
                # TODO: Implement tint
                tile = self.map.tiles[self.data[x, y]]
                if tile.surface:
                    img = tile.surface
                    # img = tile.surface.copy()
                    # img.set_alpha(self.opacity)
                    to.blit(img, (x * self.map.tilewidth - rect.x, y * self.map.tileheight - rect.y))
        return to
