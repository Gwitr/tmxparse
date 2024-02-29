"""Contains most classes regarding the format"""

from __future__ import annotations

import os
import bisect
import warnings
from dataclasses import dataclass
import xml.etree.ElementTree as ET
from typing import Callable, Any, Type, ClassVar, Generator

class TypeSpecializable:
    """Mixin that allows a type to be specialized at load time based on an XML attribute"""

    OBJECT_TYPES: ClassVar[dict[str, Type[TypeSpecializable]] | None] = None
    OBJECT_BASE: ClassVar[Type[TypeSpecializable] | None] = None
    INHERIT_BASE: ClassVar[Type[TypeSpecializable] | None] = None
    STRICT: ClassVar[bool] = False

    def __init_subclass__(cls, tiled_class: str | None = None, base: bool = False,
                          attrib: str | None = None, strict: bool | None = None, **kwargs):
        super().__init_subclass__(**kwargs)
        if attrib:
            cls.ATTRIB = attrib
        if strict:
            cls.STRICT = strict
        if TypeSpecializable in cls.__bases__:
            cls.INHERIT_BASE = cls
            data_base = [i for i in cls.__bases__ if issubclass(i, Data)][0]
            if cls.__mro__.index(TypeSpecializable) > cls.__mro__.index(data_base):
                raise TypeError("TypeSpecializable must be resolved before tmxparse.Data subclass")
        if base:
            cls.OBJECT_TYPES = {}
            cls.OBJECT_BASE = cls
        if tiled_class is not None:
            cls.TILED_CLASS = tiled_class
            cls.OBJECT_TYPES[tiled_class] = cls  # pylint: disable=unsupported-assignment-operation

    @classmethod
    def _from_et(cls, et: ET.Element, path: str, parent: Data | None, loader: BaseLoader,
                 loaded_memo: list[Data]) -> Data:
        # pylint: disable=no-member,unsubscriptable-object,protected-access
        if cls is cls.OBJECT_BASE:
            stype = et.attrib.get(cls.ATTRIB)
            if stype is None or stype not in cls.OBJECT_TYPES:  # pylint: disable=unsupported-membership-test
                return super(TypeSpecializable, cls)._from_et(et, path, parent, loader, loaded_memo)
            return cls.OBJECT_TYPES[stype]._from_et(et, path, parent, loader, loaded_memo)
        return super(TypeSpecializable, cls)._from_et(et, path, parent, loader, loaded_memo)

class BaseLoader:
    """The base loader class. If you want to use your own data classes, you'll need to inherit from
    this type, and register them under the child class."""

    _TAG_PARSERS = {}
    _STRICT = False

    def load(self, path: str):
        """Load a TMX file present at the given path"""
        loaded_memo = []
        result = self.load_internal(ET.parse(path).getroot(), path, None, loaded_memo)
        for obj in loaded_memo:
            obj.post_load()
        return result

    def load_image(self, _path: str) -> Any:
        """Load an image at the given path. Invoked by the loader when encountering images"""
        return None

    def load_font(self, _family: str, _size: float) -> Any:
        """Load a font of a given family and size. Invoked by the loader when loading text"""
        return None

    def load_internal(self, et: ET.Element, path: str, parent: Data | None,
                      loaded_memo: list[Data]) -> Data:
        """Load the correct Data subclass for a given Element and loading metadata"""
        if et.tag not in self._TAG_PARSERS:
            if self._STRICT:
                raise ValueError(f"unknown tag {et.tag}")
            warnings.warn(UserWarning(f"unknown tag {et.tag}"))
        cls2 = self._TAG_PARSERS.get(et.tag, Data)
        return cls2._from_et(et, path, parent, self, loaded_memo)  # pylint: disable=protected-access

    @classmethod
    def register(cls, cls2: Type[Data]) -> Type[Data]:
        """Attach a Data subclass to this loader. Use this when creating custom loaders"""
        cls._TAG_PARSERS[cls2.TAG] = cls2  # pylint: disable=protected-access
        return cls2

    def __init_subclass__(cls, *args, strict=False, use_defaults=True, **kwargs):
        super().__init_subclass__(*args, **kwargs)
        if use_defaults:
            cls._TAG_PARSERS = cls._TAG_PARSERS.copy()
        else:
            cls._TAG_PARSERS = {}
        cls._STRICT = strict

@dataclass
class coerce[T]:  # pylint: disable=invalid-name
    """Descriptor that converts a value to the valid type when first assigned."""

    func: Callable[[Any], T]
    _name: str | None = None

    def __set_name__(self, _owner: Any, name: str) -> None:
        self._name = name

    def __get__(self, obj: Any, _objtype: Any = None) -> T:
        return getattr(obj, "_" + self._name)

    def __set__(self, obj: Any, value: Any) -> None:
        if hasattr(obj, "_" + self._name):
            return setattr(obj, "_" + self._name, value)
        return setattr(obj, "_" + self._name, self.func(value))

    def __delete__(self, obj: Any) -> None:
        return delattr(obj, "_" + self._name)

class Data:
    """The base class for every XML element present in a TMX file."""

    TAG: ClassVar[str]
    data_children: list[Data]

    def __init_subclass__(cls, *args, tag=None, **kwargs):
        super().__init_subclass__(*args, **kwargs)
        if tag is not None:
            cls.TAG = tag

    @classmethod
    def _from_et(cls, et, path, _parent, loader, loaded_memo):
        # pylint: disable=attribute-defined-outside-init
        obj = cls()
        for k, v in et.attrib.items():
            setattr(obj, k, v)
        obj.data_children = [loader.load_internal(i, path, obj, loaded_memo) for i in et]
        loaded_memo.append(obj)
        return obj

    def post_load(self):
        """Method called when the TMX file is fully loaded (calls ran in depth-first order)"""

class TileCollection:
    """A helper class that lets you fetch a tile by its GID"""

    tilesets: list[Tileset]

    def __init__(self, tilesets: list[Tileset]):
        self.tilesets = sorted(tilesets, key=lambda x: x.firstgid)

    def __getitem__(self, gid: int) -> Tile:
        if gid == 0:
            return Tile(None, 0, None)
        tileset_idx = bisect.bisect_left(self.tilesets, gid, key=lambda x: x.firstgid)
        if len(self.tilesets) == tileset_idx or self.tilesets[tileset_idx].firstgid != gid:
            tileset_idx -= 1
        tileset = self.tilesets[tileset_idx]
        return tileset[gid - tileset.firstgid]

@BaseLoader.register
class Map(TypeSpecializable, Data, tag="map", base=True, attrib="class"):
    """A TMX map"""

    type: str
    source: str
    width: int = coerce(int)
    height: int = coerce(int)
    tilewidth: int = coerce(int)
    tileheight: int = coerce(int)
    infinite: int = coerce(lambda x: bool(int(x)))
    nextlayerid: int = coerce(int)
    nextobjectid: int = coerce(int)

    tilesets: list[Tileset]
    tiles: TileCollection
    layers: list[LayerBase]
    imgs: list[Image]

    def __repr__(self):
        return f"<Map {os.path.basename(self.source)!r} {self.width}x{self.height}>"

    @classmethod
    def _from_et(cls, et: ET.Element, path: str, parent: Data | None, loader: BaseLoader,
                 loaded_memo: list[Data]) -> Data:
        # pylint: disable=attribute-defined-outside-init
        obj = super()._from_et(et, path, parent, loader, loaded_memo)
        obj.source = path
        obj.tilesets = [i for i in obj.data_children if isinstance(i, Tileset)]
        obj.tiles = TileCollection(obj.tilesets)
        obj.layers = [i for i in obj.data_children if isinstance(i, LayerBase)]
        # FIXME: Also crawl properties to find images
        obj.imgs = [i.img for i in obj.tilesets if i.img is not None]
        obj.imgs.extend([i.img for i in obj.layers if isinstance(i, ImageLayer)])
        obj.type = et.attrib.get("class", None)
        try:
            delattr(obj, "class")
        except AttributeError:
            pass
        return obj

@BaseLoader.register
class Tileset(Data, tag="tileset"):
    """A TMX tileset"""

    tilewidth: int = coerce(int)
    tileheight: int = coerce(int)
    tilecount: int = coerce(int)
    columns: int = coerce(int)
    firstgid: int = coerce(int)
    tiledata: dict[int, Tile]

    def __repr__(self):
        return (
            f"<Tileset #{self.firstgid}-#{self.firstgid + self.tilecount}"
            f"(tile size {self.tilewidth}x{self.tileheight})>"
        )

    @classmethod
    def _from_et(cls, et: ET.Element, path: str, parent: Data | None, loader: BaseLoader,
                 loaded_memo: list[Data]) -> Data:
        if "source" in et.attrib:
            rsrc_path = os.path.join(os.path.dirname(path), et.attrib["source"])
            rsrc = ET.parse(rsrc_path).getroot()
            rsrc.attrib["firstgid"] = et.attrib["firstgid"]
            obj = loader.load_internal(rsrc, rsrc_path, parent, loaded_memo)
            return obj
        obj = super()._from_et(et, path, parent, loader, loaded_memo)
        obj.tiledata = {i.id: i for i in obj.data_children if isinstance(i, Tile)}
        obj.map = parent
        images = [i for i in obj.data_children if isinstance(i, Image)]
        if images:
            obj.img = images[0]
        else:
            obj.img = None
        return obj

    def __getitem__(self, tileid: int) -> Tile:
        if tileid < 0 or tileid >= self.tilecount:
            raise IndexError(f"no tile #{tileid}")
        if tileid in self.tiledata:
            return self.tiledata[tileid]
        return Tile(self, tileid, None)

@BaseLoader.register
class Grid(Data, tag="grid"):
    """A TMX grid object"""
    width: int = coerce(int)
    height: int = coerce(int)

@BaseLoader.register
class Text(Data, tag="text"):
    """A TMX text element"""
    fontfamily: str
    pixelsize: int = coerce(int)
    wrap: int = coerce(lambda x: bool(int(x)))

    @classmethod
    def _from_et(cls, et: ET.Element, path: str, parent: Data | None, loader: BaseLoader,
                 loaded_memo: list[Data]) -> Data:
        obj = super()._from_et(et, path, parent, loader, loaded_memo)
        obj.font = loader.load_font(obj.fontfamily, obj.pixelsize)  # pylint: disable=no-member
        obj.text = et.text
        return obj

@BaseLoader.register
class Image(Data, tag="image"):
    """A TMX image element"""
    width: int = coerce(int)
    height: int = coerce(int)
    source: str
    surface: Any

    def __repr__(self):
        return f"<Image {os.path.basename(self.source)!r} ({self.width}x{self.height})>"

    @classmethod
    def _from_et(cls, et: ET.Element, path: str, parent: Data | None, loader: BaseLoader,
                 loaded_memo: list[Data]) -> Data:
        obj = super()._from_et(et, path, parent, loader, loaded_memo)
        rsrc_path = os.path.join(os.path.dirname(path), et.attrib["source"])
        obj.surface = loader.load_image(rsrc_path)
        return obj

@BaseLoader.register
class Tile(Data, tag="tile"):
    """Information about a tile. Immutable"""
    id: int = coerce(int)
    tileset: Tileset
    properties: dict[str, Any] | None = coerce(lambda x: x)

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

    @classmethod
    def _from_et(cls, et: ET.Element, path: str, parent: Data | None, loader: BaseLoader,
                 loaded_memo: list[Data]) -> Data:
        # pylint: disable=attribute-defined-outside-init
        obj = cls()
        property_objs = [i for i in et if i.tag == "properties"]
        if property_objs:
            obj.properties = loader.load_internal(property_objs[0], path, et, loaded_memo)
            obj.properties.frozen = True
        else:
            obj.properties = None
        objectgroups = [i.tag == "objectgroup" for i in et]
        if objectgroups:
            warnings.warn(UserWarning("tile colliders not supported"))
        obj.tileset = parent
        obj.id = int(et.attrib["id"])  # setting id also freezes the object
        return obj

    def __setattr__(self, name: str, value: Any) -> None:
        if hasattr(self, "id"):
            raise AttributeError("Tile objects are immutable")
        return super().__setattr__(name, value)

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
class Properties(Data, dict, tag="properties"):
    """Properites dictionary for a TMX element"""

    frozen: bool

    def __init__(self):
        self.frozen = False

    @classmethod
    def _from_et(cls, et: ET.Element, path: str, parent: Data | None, loader: BaseLoader,
                 loaded_memo: list[Data]) -> Data:
        obj = super()._from_et(et, path, parent, loader, loaded_memo)
        for i in obj.data_children:
            obj[i.key] = i.value  # pylint: disable=unsupported-assignment-operation
        del obj.data_children
        return obj

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
class Property(Data, tag="property"):
    """A key-value pair representing a single property. Usually not too useful"""

    key: str
    value: str | int | float | bool

    def __repr__(self):
        return f"<Property {self.key}={self.value!r}>"

    @classmethod
    def _from_et(cls, et: ET.Element, path: str, _parent: Data | None, loader: BaseLoader,
                 loaded_memo: list[Data]) -> Data:
        # pylint: disable=attribute-defined-outside-init
        key = et.attrib["name"]
        value = et.attrib["value"]
        match et.attrib.get("type", "string"):
            case "bool":
                value = value == "true"
            case "int":
                value = int(value)
            case "string":
                pass
            case x:
                raise ValueError(f"unknown property type {x}")
        obj = cls()
        obj.key = key
        obj.value = value
        return obj

class LayerBase(Data):
    """Base class for all TMX layer types"""

@BaseLoader.register
class TileLayer(TypeSpecializable, LayerBase, tag="layer", base=True, attrib="class"):
    """A TMX tile layer"""

    id: int = coerce(int)
    width: int = coerce(int)
    height: int = coerce(int)
    offsetx: float = coerce(float)
    offsety: float = coerce(float)
    data: LayerData
    map: Map

    def __repr__(self):
        return f"<Layer {self.width}x{self.height}>"

    @classmethod
    def _from_et(cls, et: ET.Element, path: str, parent: Data | None, loader: BaseLoader,
                 loaded_memo: list[Data]) -> Data:
        obj = super()._from_et(et, path, parent, loader, loaded_memo)
        obj.map = parent
        property_objs = [i for i in obj.data_children if isinstance(i, Properties)]
        obj.properties = property_objs[0] if property_objs else None
        data_objs = [i for i in obj.data_children if isinstance(i, LayerData)]
        obj.data = data_objs[0] if data_objs else None
        if not hasattr(obj, "offsetx"):
            obj.offsetx = 0.0
        if not hasattr(obj, "offsety"):
            obj.offsety = 0.0
        return obj

    def __iter__(self) -> Generator[tuple[int, int, Tile], None, None]:
        for i, gid in enumerate(self.data):
            yield (i % self.width, i // self.width, self.map.tiles[gid])

@BaseLoader.register
class ImageLayer(TypeSpecializable, LayerBase, tag="imagelayer", base=True, attrib="class"):
    """A TMX image layer."""

    id: int = coerce(int)
    offsetx: float = coerce(float)
    offsety: float = coerce(float)
    img: Image | None

    def __repr__(self):
        return f"<ImageLayer {self.img!r}>"

    @classmethod
    def _from_et(cls, et: ET.Element, path: str, parent: Data | None, loader: BaseLoader,
                 loaded_memo: list[Data]) -> Data:
        obj = super()._from_et(et, path, parent, loader, loaded_memo)
        obj.map = parent
        obj.type = et.attrib.get("class", None)
        try:
            delattr(obj, "class")
        except AttributeError:
            pass
        obj.img = [i for i in obj.data_children if isinstance(i, Image)][0]
        if not hasattr(obj, "offsetx"):
            obj.offsetx = 0.0
        if not hasattr(obj, "offsety"):
            obj.offsety = 0.0
        return obj

@BaseLoader.register
class ObjectGroup(TypeSpecializable, LayerBase, tag="objectgroup", base=True, attrib="class"):
    """A TMX object group."""

    id: int = coerce(int)
    objects: list[Object]

    def __repr__(self):
        return f"<ObjectGroup {self.objects}>"

    @classmethod
    def _from_et(cls, et: ET.Element, path: str, parent: Data | None, loader: BaseLoader,
                 loaded_memo: list[Data]) -> Data:
        obj = super()._from_et(et, path, parent, loader, loaded_memo)
        if isinstance(parent, Map):
            obj.map = parent
        else:
            obj.map = None
        property_objs = [i for i in obj.data_children if isinstance(i, Properties)]
        obj.properties = property_objs[0] if property_objs else None
        obj.objects = []
        for i in obj.data_children:
            if isinstance(i, Object):
                obj.objects.append(i)
                i.parent = obj
        return obj

@BaseLoader.register
class Object(TypeSpecializable, Data, tag="object", attrib="type"):
    """A TMX object."""

    id: int = coerce(int)
    type: str
    name: str | None
    x: float = coerce(float)
    y: float = coerce(float)
    width: float = coerce(float)
    height: float = coerce(float)
    gid: int = coerce(int)
    text: Text
    img: Image

    def __repr__(self):
        return f"<Object {self.name!r} (type {self.type})>"

    @classmethod
    def _from_et(cls, et: ET.Element, path: str, parent: Data | None, loader: BaseLoader,
                 loaded_memo: list[Data]) -> Data:
        obj = super()._from_et(et, path, parent, loader, loaded_memo)
        text = [i for i in obj.data_children if isinstance(i, Text)]
        if text:
            obj.text = text[0]
        if not hasattr(obj, "name"):
            obj.name = None
        return obj

    @property
    def has_tile(self) -> bool:
        """Returns whether this Object has a tile associated with it. If it has, info about the tile
        will be accessible under the tile and gid attributes."""
        return hasattr(self, "gid")

    @property
    def has_text(self) -> bool:
        """Returns whether this Object has text associated with it. If it has, the text will be
        present under the text attribute."""
        return hasattr(self, "text")

    @property
    def tile(self) -> Tile:
        """Returns the tile associated with this object, if present."""
        try:
            return self.parent.map.tiles[self.gid]
        except AttributeError:
            raise TypeError("not a tile object") from None

@BaseLoader.register
class LayerData(Data, list, tag="data"):
    """A list of GIDs that represent the contents of a TileLayer. Supports indexing by (x,y) pair"""

    width: int = coerce(int)
    height: int = coerce(int)

    def __init__(self, data: list[int], width: int, height: int):
        self.extend(data)
        self.width = width
        self.height = height

    @classmethod
    def _from_et(cls, et: ET.Element, _path: str, parent: Data | None, _loader: BaseLoader,
                 loaded_memo: list[Data]) -> Data:
        dt = [int(i.strip()) for i in et.text.strip().replace("\n", "").split(",") if i is not None]
        obj = cls(dt, parent.width, parent.height)
        return obj

    def __setitem__(self, idx: tuple[int, int] | int, _value: int) -> None:
        # TODO: implement this
        raise NotImplementedError

    def __getitem__(self, idx: tuple[int, int] | int) -> int:
        if isinstance(idx, tuple):
            if len(idx) != 2:
                raise TypeError("can only index layer data with 2 coordinates or an index")
            return super().__getitem__(idx[1] * self.width + idx[0])
        return super().__getitem__(idx)
