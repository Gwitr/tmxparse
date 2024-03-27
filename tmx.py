"""Contains most classes regarding the format"""

from __future__ import annotations

import os
import bisect
from typing import Generator, Any
import xml.etree.ElementTree as ET

from .base import BaseLoader, TypeSpecializable, Data, dfield, alias, coerce

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
class Map(TypeSpecializable, Data, tag="map", maybe_remote=True, data_base=True,
          base=True, attrib="class"):
    """A TMX map"""

    version: str = dfield()
    tiledversion: str | None = dfield()
    type: str | None = dfield(rename_from="class")
    orientation: str = dfield(default="orthogonal")
    renderorder: str = dfield(default="right-down")
    compressionlevel: int = dfield(default=-1)
    width: int = dfield()
    height: int = dfield()
    tilewidth: int = dfield()
    tileheight: int = dfield()
    hexsidelength: int | None = dfield()
    staggeraxis: str | None = dfield()
    staggerindex: str | None = dfield()
    parallaxoriginx: int = dfield(default=0)
    parallaxoriginy: int = dfield(default=0)
    backgroundcolor: str | None = dfield()
    nextlayerid: int | None = dfield()
    nextobjectid: int | None = dfield()
    infinite: bool = dfield(default=False)

    tilesets: list[Tileset] = dfield(xml_child=True)
    layers: list[LayerBase] = dfield(xml_child=True)

    imgs: list[Image] = dfield(loader=lambda obj, _loader: (
        [i.img for i in obj.tilesets if i.img is not None] +
        [i.img for i in obj.layers if isinstance(i, ImageLayer)]
    ))
    tiles: TileCollection = dfield(loader=lambda obj, loader: TileCollection(loader.TAG_PARSERS["tile"], obj.tilesets))

    def __repr__(self):
        return f"<Map {os.path.basename(self.source)!r} {self.width}x{self.height}>"

@BaseLoader.register
class Tileset(Data, tag="tileset", maybe_remote=True, data_base=True):
    """A TMX tileset"""

    tile_cls: type[Tile] = dfield(loader=lambda _obj, loader: loader.TAG_PARSERS["tile"])

    tilewidth: int = dfield()
    tileheight: int = dfield()
    tilecount: int = dfield()
    columns: int = dfield()
    firstgid: int = dfield()
    img: Image | None = dfield(xml_child=True, rename_from="image", json_use_parent_obj=True)

    tiledata: dict[int, Tile]

    map: Map = alias("parent")

    def load_xml(self, _loader: BaseLoader, element: ET.Element) -> None:
        tiles = [i for i in element.data_children if isinstance(i, Tile)]
        self.tiledata = {i.id: i for i in tiles}

    def load_json(self, element: Any, path: str, _parent: Data | None, loader: BaseLoader, loaded_memo: list[Data]) -> None:
        self.tiledata = {int(k): Tile._load(v, path, self, loader, loaded_memo) for k, v in element.get("tiles", {}).items()}
        for tileid, tile in self.tiledata.items():
            tile.id = tileid

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
        return self.tile_cls(self, tileid, None)

@BaseLoader.register
class Grid(Data, tag="grid", data_base=True):
    """A TMX grid overlay information object"""
    width: int = dfield()
    height: int = dfield()

@BaseLoader.register
class Image(Data, tag="image", data_base=True):
    """A TMX image element"""
    width: int | None = dfield(json_rename_from="imagewidth")
    height: int | None = dfield(json_rename_from="imageheight")
    source: str | None = dfield(json_rename_from="image")
    surface: Any = dfield(loader=lambda obj, loader: loader.load_image(
        os.path.join(os.path.dirname(obj.data_path), obj.source)))

    def __repr__(self):
        return f"<Image {os.path.basename(self.source)!r} ({self.width}x{self.height})>"

@BaseLoader.register
class Text(Data, tag="text", data_base=True):
    """A TMX text element"""

    fontfamily: str = dfield()
    pixelsize: int = dfield()
    wrap: bool = dfield()
    text: str = dfield(xml_text=True)
    color: str = dfield(default="#ffffff")

    font: Any = dfield(loader=lambda obj, loader: loader.load_font(obj.fontfamily, obj.pixelsize))

@BaseLoader.register
class Tile(Data, tag="tile", data_base=True, xml_child_ignore=["objectgroup"]):
    # TODO: Add back immutability. Turns out, a custom __setattr__ was not very fast
    """Information about a tile"""
    tileset: Tileset = alias("parent")
    id: int | None = dfield()  # Not optional, but loading from JSON will sometimes load this late
    properties: Properties | None = dfield(xml_child=True, json_use_parent_obj=True)

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
class Properties(Data, dict, tag="properties", data_base=True):
    """Properties dictionary for a TMX element"""

    frozen: bool

    def __init__(self):
        self.frozen = False

    def load_xml(self, _loader: BaseLoader, _element: ET.Element) -> None:
        for i in self.data_children:
            self[i.name] = i.value
        del self.data_children

    def load_json(self, element: Any, path: str, parent: Data | None, loader: BaseLoader, loaded_memo: list[Data]) -> None:
        # pylint: disable=protected-access
        if "properties" not in element:
            return  # blank
        for key in element["properties"].keys():
            prop = loader.TAG_PARSERS["property"]()
            prop.name = key
            prop._value1 = element["properties"][key]
            prop.type = element["propertytypes"][key]
            prop.value = Property.value.loader(prop, loader)
            self[prop.name] = prop.value

    def __hash__(self) -> int:
        if not self.frozen:
            raise ValueError("cannot hash unfrozen Properties")
        return hash(tuple(self.items()))

    def __setitem__(self, key: Any, value: Any) -> None:
        if self.frozen:
            raise ValueError("frozen object")
        return super().__setitem__(key, value)

    def pop(self, key: Any, default: Any) -> Any:
        if self.frozen:
            raise ValueError("frozen object")
        return super().pop(key, default)

    def update(self, other: Any) -> None:
        if self.frozen:
            raise ValueError("frozen object")
        return super().update(other)

    def clear(self) -> None:
        if self.frozen:
            raise ValueError("frozen object")
        return super().clear()

@BaseLoader.register
class Property(Data, tag="property", data_base=True):
    # pylint: disable=protected-access
    """A key-value pair representing a single property. Usually not too useful"""

    name: str = dfield()
    type: str | None = dfield()
    _value1: str | None = dfield(rename_from="value", temporary=True)
    _value2: str | None = dfield(xml_text=True, temporary=True)
    value: str | int | float | bool = dfield(loader=lambda obj, _loader: coerce({
        "bool": bool, "string": str, "int": int, "number": float
    }.get(obj.type, str), obj._value1 if obj._value1 is not None else obj._value2))

    def __repr__(self):
        return f"<Property {self.name}={self.value!r}>"

class LayerBase(Data):
    """Base class for all TMX layer types"""

@BaseLoader.register
class TileLayer(LayerBase, tag="layer", json_match=(lambda x: x["type"] == "tilelayer"), data_base=True):
    """A TMX tile layer"""

    # TODO: Reintroduce TypeSpecializable here (mro magic broke it)
    id: int = dfield(default=0)
    name: str = dfield(default="")
    map: Map = alias("parent")
    width: int = dfield()
    height: int = dfield()
    opacity: float = dfield(default=1)
    visible: bool = dfield(default=True)
    tintcolor: str | None = dfield()
    offsetx: float = dfield(default=0.0)
    offsety: float = dfield(default=0.0)
    parallaxx: float = dfield(default=1.0)
    parallaxy: float = dfield(default=1.0)

    properties: Properties | None = dfield(xml_child=True, json_use_parent_obj=True)
    data: LayerData | None = dfield(xml_child=True)

    def load_json(self, *_):
        if self.data is not None:
            self.data.width = self.width
            self.data.height = self.height

    def load_xml(self, *_):
        if self.data is not None:
            self.data.width = self.width
            self.data.height = self.height

    def __repr__(self):
        return f"<Layer {self.width}x{self.height}>"

    def __iter__(self) -> Generator[tuple[int, int, Tile], None, None]:
        for i, gid in enumerate(self.data):
            yield (i % self.width, i // self.width, self.map.tiles[gid])

@BaseLoader.register
class ImageLayer(TypeSpecializable, LayerBase, tag="imagelayer", json_match=(lambda x: x["type"] == "imagelayer"), data_base=True,
                 base=True, attrib="class"):
    """A TMX image layer."""

    id: int = dfield(default=0)
    map: Map = alias("parent")
    type: str | None = dfield(rename_from="class")
    offsetx: float = dfield(default=0.0)
    offsety: float = dfield(default=0.0)
    img: Image = dfield(xml_child=True, json_use_parent_obj=True)

    def __repr__(self):
        return f"<ImageLayer {self.img!r}>"

@BaseLoader.register
class ObjectGroup(TypeSpecializable, LayerBase, tag="objectgroup", json_match=(lambda x: x["type"] == "objectgroup"), data_base=True,
                  base=True, attrib="class"):
    """A TMX object group."""

    map: Map = alias("parent")

    id: int = dfield(default=0)
    name: str = dfield(default="")
    color: str | None = dfield()
    opacity: float = dfield(default=1.0)
    visible: bool = dfield(default=True)
    tintcolor: str | None = dfield()
    offsetx: float = dfield(default=0.0)
    offsety: float = dfield(default=0.0)
    parallaxx: float = dfield(default=1.0)
    parallaxy: float = dfield(default=1.0)
    draworder: str = dfield(default="topdown")

    properties: Properties | None = dfield(xml_child=True, json_use_parent_obj=True)
    objects: list[Object] = dfield(xml_child=True)

    def __repr__(self):
        return f"<ObjectGroup {self.objects}>"

@BaseLoader.register
class Object(TypeSpecializable, Data, tag="object", data_base=True, attrib="type"):
    """A TMX object."""

    id: int = dfield(default=0)
    name: str | None = dfield()
    type: str | None = dfield()
    x: float = dfield()
    y: float = dfield()
    width: float = dfield()
    height: float = dfield()
    rotation: float = dfield(default=0.0)
    gid: int | None = dfield()
    visible: bool = dfield(default=True)

    text: Text | None = dfield(xml_child=True)

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
class LayerData(Data, list, tag="data", data_base=True):
    """A list of GIDs that represent the contents of a TileLayer. Supports indexing by (x,y) pair"""

    width: int | None
    height: int | None

    def __init__(self, data: list[int] | None = None, width: int | None = None,
                 height: int | None = None):
        if data is not None:
            self.extend(data)
        self.width = width
        self.height = height

    # TODO: Types beyond csv

    def load_json(self, data_obj, path, parent, loader, loaded_memo):
        self.extend(data_obj)

    def load_xml(self, _loader, element):
        self.extend(
            int(i.strip())
            for i in element.text.strip().replace("\n", "").split(",")
            if i is not None
        )

    def __setitem__(self, idx: tuple[int, int] | int, _value: int) -> None:
        # TODO: implement this
        raise NotImplementedError

    def __getitem__(self, idx: tuple[int, int] | int) -> int:
        if isinstance(idx, tuple):
            if len(idx) != 2:
                raise TypeError("can only index layer data with 2 coordinates or an index")
            return super().__getitem__(idx[1] * self.width + idx[0])
        return super().__getitem__(idx)
