"""Contains most classes regarding the format"""

from __future__ import annotations

import os
import array
import types
import bisect
from collections import UserDict
import xml.etree.ElementTree as ET
from typing import Generator, Any, Union, get_origin, get_args, cast

from base import BaseLoader, SpecializableMixin, Entry, Field, LoaderContext, RemoteEntry

class TileCollection:
    """A helper class that lets you fetch a tile by its GID"""

    tile_cls: type[Tile]
    tilesets: list[Tileset]

    def __init__(self, tile_cls: type[Tile], tilesets: list[Tileset]):
        self.tile_cls = tile_cls
        self.tilesets = sorted(tilesets, key=lambda x: x.firstgid)

    def __getitem__(self, gid: int) -> Tile:
        if gid == 0:
            return self.tile_cls(None, 0, None)
        tileset_idx = bisect.bisect_left(self.tilesets, gid, key=lambda x: x.firstgid)
        if len(self.tilesets) == tileset_idx or self.tilesets[tileset_idx].firstgid != gid:
            tileset_idx -= 1
        tileset = self.tilesets[tileset_idx]
        return tileset[gid - tileset.firstgid]

@BaseLoader.register
class Map(SpecializableMixin, RemoteEntry, tag="map", base=True, attrib="class"):
    """A TMX map"""

    version: str | Field = Field()
    tiledversion: str | None | Field = Field()
    type: str | None | Field = Field(rename_from="class")
    orientation: str | Field = Field()
    renderorder: str | Field = Field()
    compressionlevel: int | Field = Field(default=-1)
    width: int | Field = Field()
    height: int | Field = Field()
    tilewidth: int | Field = Field()
    tileheight: int | Field = Field()
    hexsidelength: int | None | Field = Field()
    staggeraxis: str | None | Field = Field()
    staggerindex: str | None | Field = Field()
    parallaxoriginx: int | Field = Field(default=0)
    parallaxoriginy: int | Field = Field(default=0)
    backgroundcolor: str | None | Field = Field()
    nextlayerid: int | None | Field = Field()
    nextobjectid: int | None | Field = Field()
    infinite: bool | Field = Field(default=False)

    tilesets: list[Tileset] | Field = Field(xml_child=True)
    layers: list[LayerBase] | Field = Field(xml_child=True)

    imgs: list[Image] | Field = Field(loader=lambda obj, _data, _parent, _ctx: (
        [i.img for i in obj.tilesets if i.img is not None] +
        [i.img for i in obj.layers if isinstance(i, ImageLayer)]
    ))
    tiles: TileCollection | Field = Field(loader=lambda obj, _data, _parent, ctx: TileCollection(ctx.loader.PARSERS["tile"], obj.tilesets))

    def __repr__(self):
        return f"<Map {os.path.basename(self.source)!r} {self.width}x{self.height}>"

@BaseLoader.register
class Tileset(RemoteEntry, tag="tileset"):
    """A TMX tileset"""

    __slots__ = ("tiledata",)

    tile_cls: type[Tile] | Field = Field(loader=lambda _obj, _data, _parent, ctx: ctx.loader.PARSERS["tile"])

    tilewidth: int | Field = Field()
    tileheight: int | Field = Field()
    tilecount: int | Field = Field()
    columns: int | Field = Field()
    firstgid: int | Field = Field()
    img: Image | None | Field = Field(xml_child=True, rename_from="image")

    tiledata: dict[int, Tile]

    map: Map | Field = Field(alias="parent")

    @classmethod
    def _load(cls, data: Any, parent: Entry | None, ctx: LoaderContext) -> Tileset:
        self = super()._load(data, parent, ctx)
        if isinstance(data, ET.Element):
            tiles = [i for i in data if isinstance(i, Tile)]
            self.tiledata = {i.id: i for i in tiles}
        else:
            self.tiledata = {int(k): ctx.load(ctx.loader.PARSERS["tile"], v, self) for k, v in data.get("tiles", {}).items()}
            for tileid, tile in self.tiledata.items():
                tile.id = tileid
        return self

    def __repr__(self):
        return (
            f"<Tileset #{self.firstgid}-#{self.firstgid + self.tilecount}"
            f"(tile size {self.tilewidth}x{self.tileheight})>"
        )

    def __getitem__(self, tileid: int) -> Tile:
        if tileid < 0 or tileid >= self.tilecount:
            raise IndexError(f"no tile #{tileid}")
        if tileid in self.tiledata:
            return self.tiledata[tileid]
        return self.tile_cls(self, tileid, None)  # pylint: disable=not-callable

@BaseLoader.register
class Grid(Entry, tag="grid"):
    """A TMX grid overlay information object"""
    width: int | Field = Field()
    height: int | Field = Field()

@BaseLoader.register
class Image(Entry, tag="image", json_use_parent=True):
    """A TMX image element"""
    width: int | None | Field = Field(json_rename_from="imagewidth")
    height: int | None | Field = Field(json_rename_from="imageheight")
    source: str | None | Field = Field(json_rename_from="image")
    surface: Any | Field = Field(loader=lambda obj, data, parent, ctx: ctx.loader.load_image(
        os.path.join(os.path.dirname(obj.filename), obj.source)))

    def __repr__(self):
        return f"<Image {os.path.basename(self.source)!r} ({self.width}x{self.height})>"

@BaseLoader.register
class Text(Entry, tag="text"):
    """A TMX text element"""

    fontfamily: str | Field = Field()
    pixelsize: int | Field = Field()
    wrap: bool | Field = Field()
    text: str | Field = Field(xml_text=True)
    color: str | Field = Field(default="#ffffff")

    font: Any | Field = Field(loader=lambda obj, data, parent, ctx: ctx.loader.load_font(obj.fontfamily, obj.pixelsize))

@BaseLoader.register
class Tile(Entry, tag="tile"):  # , xml_child_ignore=["objectgroup"]):
    # TODO: Add back immutability. Turns out a custom __setattr__ was not very fast
    """Information about a tile"""
    tileset: Tileset | Field = Field(alias="parent")
    id: int | None | Field = Field()  # Not optional, but loading from JSON will sometimes load this late
    properties: Properties | None | Field = Field(xml_child=True)

    def __repr__(self):
        props = "" if self.properties is None else f" (properties {self.properties})"
        return f"<Tile #{self.gid}{props}>"

    def __init__(self, tileset: Tileset | None = None, id_: int | None = None,
                 properties: Properties | None = None) -> None:
        if id_ is None:
            if tileset is None:
                return
            raise ValueError("__init__ takes 0, 2, or 3 arguments, 1 given")
        self.tileset = tileset
        self.properties = properties
        self.id = id_

    def __hash__(self) -> int:
        return hash(tuple((self.gid, self.properties)))

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, Tile):
            return NotImplemented
        return self.gid == other.gid and self.properties == other.properties

    @property
    def rect(self) -> tuple[int, int, int, int]:
        """Returns (x, y, w, h) location information for the tile within its tileset"""
        if self.tileset is None:
            return None
        offsx = (self.id % self.tileset.columns) * self.tileset.tilewidth
        offsy = (self.id // self.tileset.columns) * self.tileset.tileheight
        return (offsx, offsy, self.tileset.tilewidth, self.tileset.tileheight)

    @property
    def gid(self) -> int:
        """Returns the GID of the tile"""
        if self.tileset is None:
            return 0
        return self.tileset.firstgid + self.id

@BaseLoader.register
class Properties(Entry, UserDict, tag="properties", json_use_parent=True):
    """Properties dictionary for a TMX element"""

    __slots__ = ("frozen", "data", "types")

    frozen: bool

    def __init__(self, data=None, types=None):
        Entry.__init__(self)
        UserDict.__init__(self)
        self.frozen = False
        self.types = {}
        if data is not None:
            self.update(data)
            self.types.update(types)

    @classmethod
    def _load(cls, data: Any, parent: Entry | None, ctx: LoaderContext) -> Tileset:
        self = cls()
        if isinstance(data, ET.Element):
            for i in data:
                self.types[i.name] = i.type
                self[i.name] = i.value
        elif "properties" in data:
            for key in data["properties"].keys():
                # TODO: fix all of this
                prop = ctx.loader.PARSERS["property"]()
                prop.name = key
                prop._value1 = data["properties"][key]
                prop.type = data["propertytypes"][key]
                prop.value = Property.FIELDS["value"].loader(prop, data, parent, ctx)
                self.types[prop.name] = prop.type
                self[prop.name] = prop.value
        return self

    def __hash__(self) -> int:
        if not self.frozen:
            raise ValueError("cannot hash unfrozen Properties")
        return hash(tuple(self.items()))

    def __setitem__(self, key: Any, value: Any) -> None:
        if self.frozen:
            raise ValueError("frozen object")
        return super().__setitem__(key, value)

    def pop(self, key: Any, default: Any = None) -> Any:
        if self.frozen:
            raise ValueError("frozen object")
        return super().pop(key, default)

    def update(self, *args: Any, **kwargs: Any) -> None:
        if self.frozen:
            raise ValueError("frozen object")
        return super().update(*args, **kwargs)

    def clear(self) -> None:
        if self.frozen:
            raise ValueError("frozen object")
        return super().clear()

def coerce(annotation, value):
    """turn xml attrib to Python object"""

    if isinstance(annotation, tuple):
        raise ValueError(f"can't coerce to {' | '.join(annotation)}")

    if get_origin(annotation) in (Union, types.UnionType):
        possible_types = list(get_args(annotation))
        if len(possible_types) != 2 or type(None) not in possible_types:
            raise ValueError("union isn't type")
        possible_types.remove(type(None))
        annotation = possible_types[0]
    if get_origin(annotation) is list:
        annotation = get_args(annotation)[0]
    if get_origin(annotation) is list:
        raise ValueError("nested list")
    if get_origin(annotation) is not None:
        raise ValueError(f"can't coerce to {annotation}")
    if isinstance(annotation, bool):
        return annotation.lower() == "true" or (annotation.lower() != "false" and bool(int(value)))
    return annotation(value)

@BaseLoader.register
class Property(Entry, tag="property"):
    # pylint: disable=protected-access
    """A key-value pair representing a single property. Usually not too useful"""

    name: str | Field = Field()
    type: str | None | Field = Field()
    _value1: str | None | Field = Field(rename_from="value")
    _value2: str | None | Field = Field(xml_text=True)
    value: str | int | float | bool | Field = Field(loader=lambda obj, _data, _parent, _ctx: coerce({
        "bool": (lambda x: False if x.lower() == "false" else bool(x)), "string": str, "int": int, "number": float
    }.get(obj.type, str), obj._value1 if obj._value1 is not None else obj._value2))

    def __repr__(self):
        return f"<Property {self.name}={self.value!r}>"

class LayerBase(Entry, json_type=None):
    """Base class for all TMX layer types"""

@BaseLoader.register
class TileLayer(LayerBase, tag="layer", json_type="tilelayer"):
    """A TMX tile layer"""

    # TODO: Reintroduce SpecializableMixin here (mro magic broke it)
    id: int | Field = Field(default=0)
    name: str | Field = Field(default="")
    map: Map | Field = Field(alias="parent")
    width: int | Field = Field()
    height: int | Field = Field()
    opacity: float | Field = Field(default=1)
    visible: bool | Field = Field(default=True)
    tintcolor: str | None | Field = Field()
    offsetx: float | Field = Field(default=0.0)
    offsety: float | Field = Field(default=0.0)
    parallaxx: float | Field = Field(default=1.0)
    parallaxy: float | Field = Field(default=1.0)

    properties: Properties | None | Field = Field(xml_child=True)
    data: LayerData | None | Field = Field(xml_child=True)

    @classmethod
    def _load(cls, data: Any, parent: Entry | None, ctx: LoaderContext) -> TileLayer:
        asdf: TileLayer = cast(TileLayer, super()._load(data, parent, ctx))
        # pylint absolutely INSISTENT that asdf is an instance of Entry for some reason
        # pylint: disable=no-member
        if asdf.data is not None:
            asdf.data.width = asdf.width
            asdf.data.height = asdf.height
        return asdf

    def __repr__(self):
        return f"<Layer {self.width}x{self.height}>"

    def __iter__(self) -> Generator[tuple[int, int, Tile], None, None]:
        for i, gid in enumerate(self.data):
            yield (i % self.width, i // self.width, self.map.tiles[gid])  # pylint: disable=no-member

@BaseLoader.register
class ImageLayer(SpecializableMixin, LayerBase, tag="imagelayer", base=True, attrib="class", json_type="imagelayer"):
    """A TMX image layer."""

    id: int | Field = Field(default=0)
    map: Map | Field = Field(alias="parent")
    type: str | None | Field = Field(rename_from="class")
    offsetx: float | Field = Field(default=0.0)
    offsety: float | Field = Field(default=0.0)
    parallaxx: float | Field = Field(default=1.0)
    parallaxy: float | Field = Field(default=1.0)
    img: Image | Field = Field(xml_child=True)

    def __repr__(self):
        return f"<ImageLayer {self.img!r}>"

@BaseLoader.register
class ObjectGroup(SpecializableMixin, LayerBase, tag="objectgroup", base=True, attrib="class", json_type="objectgroup"):
    """A TMX object group."""

    map: Map | Field = Field(alias="parent")

    id: int | Field = Field(default=0)
    name: str | Field = Field(default="")
    color: str | None | Field = Field()
    opacity: float | Field = Field(default=1.0)
    visible: bool | Field = Field(default=True)
    tintcolor: str | None | Field = Field()
    offsetx: float | Field = Field(default=0.0)
    offsety: float | Field = Field(default=0.0)
    parallaxx: float | Field = Field(default=1.0)
    parallaxy: float | Field = Field(default=1.0)
    draworder: str | Field = Field(default="topdown")

    properties: Properties | None | Field = Field(xml_child=True)
    objects: list[Object] | Field = Field(xml_child=True)

    def __repr__(self):
        return f"<ObjectGroup {self.objects}>"

@BaseLoader.register
class Object(SpecializableMixin, Entry, tag="object", attrib="type"):
    """A TMX object."""

    id: int | Field = Field(default=0)
    name: str | None | Field = Field()
    type: str | None | Field = Field()
    x: float | Field = Field()
    y: float | Field = Field()
    width: float | None | Field = Field()
    height: float | None | Field = Field()
    rotation: float | Field = Field(default=0.0)
    gid: int | None | Field = Field()
    visible: bool | Field = Field(default=True)

    properties: Properties | None | Field = Field(xml_child=True)

    text: Text | None | Field = Field(xml_child=True)

    def __repr__(self):
        return f"<Object {self.name!r} (type {self.type})>"

    @property
    def has_tile(self) -> bool:
        """Returns whether this Object has a tile associated with it. If it has, info about the tile
        will be accessible under the tile and gid attributes."""
        return self.gid is not None

    @property
    def has_text(self) -> bool:
        """Returns whether this Object has text associated with it. If it has, the text will be
        present under the text attribute."""
        return self.text is not None

    @property
    def tile(self) -> Tile:
        """Returns the tile associated with this object, if present."""
        if self.gid is None:
            raise TypeError("not a tile object")
        return self.parent.map.tiles[self.gid]

@BaseLoader.register
class LayerData(Entry, tag="data"):
    """A list of GIDs that represent the contents of a TileLayer. Supports indexing by (x,y) pair"""

    __slots__ = ("width", "height", "data")

    width: int | None
    height: int | None

    def __init__(self, data: list[int] | None = None, width: int | None = None,
                 height: int | None = None):
        super().__init__()
        self.width = width
        self.height = height
        if data is None:
            if self.width is None or self.height is None:
                self.data = array.array("I")
            else:
                self.data = array.array("I", [0] * (self.width * self.height))
        else:
            self.data = array.array("I", data)

    # TODO: Types beyond csv

    @classmethod
    def _load(cls, data: Any, parent: Entry | None, ctx: LoaderContext) -> Tileset:
        self = super()._load(data, parent, ctx)
        # pylint: disable=no-member
        if isinstance(data, list):
            self.data.extend(data)
        else:
            self.data.extend(
                int(i.strip())
                for i in data.text.strip().replace("\n", "").split(",")
                if i is not None
            )
        return self

    def __setitem__(self, idx: tuple[int, int] | int, _value: int) -> None:
        self.data[idx[1] * self.width + idx[0]] = _value

    def __iter__(self):
        return iter(self.data)

    def __getitem__(self, idx: tuple[int, int] | int) -> int:
        try:
            return self.data[idx[1] * self.width + idx[0]]
        except (TypeError, IndexError):
            raise TypeError("can only index layer data with 2 coordinates") from None
