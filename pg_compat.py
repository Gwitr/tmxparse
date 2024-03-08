"""Extra classes for Pygame compatibility"""

from __future__ import annotations

from typing import Type, Any
import xml.etree.ElementTree as ET

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

    @classmethod
    def register(cls, cls2: Type[Any]) -> Type[Any]:
        union = {tmx.Tile, tmx.Tileset, tmx.Map} & set(cls2.__bases__)
        if _NO_DIRECT_INHERIT and union:
            # FIXME: Make this hack unnecessary
            base = next(iter(union)).__name__
            raise TypeError(f"Please inherit from tmxparse.pg_compat.{base} instead of "
                f"from tmxparse.{base} when using PygameLoader")
        return super().register(cls2)

class TileCollection(tmx.TileCollection):
    """tmxparse.TileCollection, modified to use the tmxparse.pg_compat.Tile class"""

    def __getitem__(self, gid: int) -> Tile:
        tile = super().__getitem__(gid)
        return Tile(tile.tileset, tile.id, tile.properties)

_NO_DIRECT_INHERIT = False

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
class Tileset(tmx.Tileset, tag="tileset"):
    """tmxparse.Tileset, modified to use tmxparse.pg_compat.Tile"""

    def __getitem__(self, tileid: int) -> Tile:
        tile = super().__getitem__(tileid)
        return Tile(tile.tileset, tile.id, tile.properties)

@PygameLoader.register
class Map(tmx.Map):
    """tmxparse.Map, modified to use tmxparse.pg_compat.TileCollection"""

    tiles: TileCollection

    def load_xml(self, _loader: PygameLoader, _element: ET.Element) -> None:
        self.tiles = TileCollection(self.tilesets)

_NO_DIRECT_INHERIT = True
