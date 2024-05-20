"""Extra classes for Pygame compatibility, as well as some convenience functionality. Experimental, untested"""

from __future__ import annotations

import math
from typing import cast, Any

try:
    import pygame
except ImportError:
    raise ImportError("The tmxparse.pg_compat module requires Pygame to be installed") from None
import pygame.freetype as ft

from . import tmx

class LayerRenderer:
    """Helper class to handle fast rendering of a scrolling map's layer"""

    layer: tmx.LayerBase
    target_width: int
    target_height: int

    def __init__(self, layer, target_width, target_height):
        self.layer = layer
        self.target_width = target_width
        self.target_height = target_height
        self.last_xy = [None, None]
        self.invalid_rects = []

    @property
    def last_x(self):
        return self.last_xy[0]

    @last_x.setter
    def last_x(self, value):
        self.last_xy[0] = value

    @property
    def last_y(self):
        return self.last_xy[1]

    @last_y.setter
    def last_y(self, value):
        self.last_xy[1] = value

    def invalidate(self, rect):
        self.invalid_rects.append(rect)

    def _render_invalid(self, target):
        for r in self.invalid_rects:
            self.layer.render((r[0]-self.last_x, r[1]-self.last_y, r[2], r[3]), target.subsurface(r))
        self.invalid_rects.clear()

    def render(self, x, y, target, do_scroll=True):
        # TODO: Animated tiles
        # TODO: Parallax
        x = round(-x)
        y = round(-y)
        if self.last_x is None:
            self.invalidate((0, 0, self.target_width, self.target_height))
        else:
            diffx = x - self.last_x
            diffy = y - self.last_y
            if diffx == 0 and diffy == 0:
                self._render_invalid(target)
                return
            if do_scroll:
                tmp = target.copy()
                target.fill(0)
                target.blit(tmp, (diffx, diffy))

            rects = [
                [0, 0, self.target_width, abs(diffy)],               # the top/bottom update area
                [0, 0, abs(diffx), self.target_height - abs(diffy)]  # the left/right update area
            ]
            if diffy > 0:
                rects[1][1] = diffy
            else:
                rects[0][1] = self.target_height + diffy
            if diffx > 0:
                rects[1][0] = 0
            else:
                rects[1][0] = self.target_width + diffx

            self.invalidate(rects[0])
            self.invalidate(rects[1])

        self.last_x = x
        self.last_y = y
        self._render_invalid(target)

class MapRenderer:
    """Helper class to handle fast rendering of a scrolling map"""

    map: Map
    target_width: int
    target_height: int
    last_x: int | None
    last_y: int | None

    def __init__(self, tmap, target_width, target_height):
        self.map = tmap
        self.target_width = target_width
        self.target_height = target_height
        self.last_x = None
        self.last_y = None
        self.invalid_rects = []

    def invalidate(self, rect):
        self.invalid_rects.append(rect)

    def _render_invalid(self, target):
        w, h = target.get_size()
        for r in self.invalid_rects:
            self.map.render(
                (r[0]-self.last_x, r[1]-self.last_y, r[2], r[3]),
                target.subsurface((r[0], r[1], min(r[2]+r[0], w)-r[0], min(r[3]+r[1], h)-r[1]))
            )
        self.invalid_rects.clear()

    def render(self, x, y, target):
        # TODO: Animated tiles
        x = round(-x)
        y = round(-y)
        if self.last_x is None:
            self.invalidate((0, 0, self.target_width, self.target_height))
        else:
            diffx = x - self.last_x
            diffy = y - self.last_y
            if diffx == 0 and diffy == 0:
                self._render_invalid(target)
                return
            x = target.copy()
            target.fill(0)
            target.blit(x, (diffx, diffy))

            rects = [
                [0, 0, self.target_width, abs(diffy)],               # the top/bottom update area
                [0, 0, abs(diffx), self.target_height - abs(diffy)]  # the left/right update area
            ]
            if diffy > 0:
                rects[1][1] = diffy
            else:
                rects[0][1] = self.target_height + diffy
            if diffx > 0:
                rects[1][0] = 0
            else:
                rects[1][0] = self.target_width + diffx

            self.invalidate(rects[0])
            self.invalidate(rects[1])

        self.last_x = x
        self.last_y = y
        self._render_invalid(target)

class PygameLoader(tmx.BaseLoader):
    """Pygame-aware TMX loader"""

    __slots__ = ("convert_alpha",)

    def __init__(self, convert_alpha: bool = True):
        self.convert_alpha = convert_alpha

    def load_image(self, path: str) -> pygame.Surface:
        img = pygame.image.load(path)
        if self.convert_alpha:
            return img.convert_alpha()
        return img

    def load_font(self, family: str, size: float) -> ft.Font:
        return ft.SysFont(family, cast(int, size))

@PygameLoader.register
class Tile(tmx.Tile):
    """Extra Pygame-related functionality for the base Tile class"""

    __slots__ = ()

    @property
    def surface(self) -> pygame.Surface | None:
        """Fetches the Pygame graphic of the tile"""
        if self.tileset is None:
            return None
        return self.tileset.img.surface.subsurface(self.rect)

@PygameLoader.register
class Map(tmx.Map):
    """Extra Pygame-related functionality for the base Map class"""

    __slots__ = ()

    def render(self, in_rect: tuple[int, int, int, int] | None = None,
               to: pygame.Surface | None = None) -> pygame.Surface:
        """Render an image or subimage of the map"""
        if in_rect is None:
            in_rect = (0, 0, self.width * self.tilewidth, self.height * self.tileheight)
        rect = pygame.Rect(in_rect)
        if to is None:
            to = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
        for layer in self.layers:
            if isinstance(layer, TileLayer) and layer.visible:
                layer.render(cast(Any, tuple(rect)), to)
            if isinstance(layer, ObjectGroup) and layer.visible:
                layer.render(cast(Any, tuple(rect)), to)
        return to

@PygameLoader.register
class ObjectGroup(tmx.ObjectGroup):
    """Extra Pygame-related functionality for the base ObjectGroup class"""

    __slots__ = ()

    def render(self, in_rect: tuple[int, int, int, int] | None = None,
               to: pygame.Surface | None = None) -> pygame.Surface:
        """Render an image or subimage of the layer"""
        if to is None:
            raise ValueError("ObjectGroup.render requires a target")
        assert in_rect is not None
        rect = pygame.Rect(in_rect)
        for obj in sorted(self.objects, key=lambda obj: -obj.y):  # TODO: Don't sort literally everything every time this is called
            if obj.has_tile and obj.tile.surface:
                to.blit(obj.tile.surface, (obj.x - rect.x, obj.y - obj.tile.surface.get_height() - rect.y))
        return to

@PygameLoader.register
class TileLayer(tmx.TileLayer):
    """Extra Pygame-related functionality for the base TileLayer class"""

    __slots__ = ()

    def render(self, in_rect: tuple[int, int, int, int] | None = None,
               to: pygame.Surface | None = None) -> pygame.Surface:
        # pylint: disable=no-member
        # pylint dead convinced that self.map is a Field instance at all times
        """Render an image or subimage of the layer"""
        if in_rect is None:
            in_rect = (0, 0, self.width * self.map.tilewidth, self.height * self.map.tileheight)
        rect = pygame.Rect(in_rect)
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
