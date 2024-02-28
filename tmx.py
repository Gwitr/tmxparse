from __future__ import annotations

import os
import bisect
import warnings
from dataclasses import dataclass
import xml.etree.ElementTree as ET
from typing import Callable, Any, cast

import pygame
import pygame.freetype as ft

class TypeSpecializable:
    OBJECT_TYPES = None
    BASE = None
    STRICT = False

    def __init_subclass__(cls, tiled_class=None, base=False, attrib=None, strict=None, **kwargs):
        super().__init_subclass__(**kwargs)
        if base:
            cls.OBJECT_TYPES = {}
            cls.BASE = cls
            cls.TMX_BASE = [i for i in cls.__bases__ if issubclass(i, Data)][0]
            if attrib:
                cls.ATTRIB = attrib
            if strict:
                cls.STRICT = strict
            if cls.__mro__.index(TypeSpecializable) > cls.__mro__.index(cls.TMX_BASE):
                raise TypeError("TypeSpecializable must be resolved before tmx.Data subclass")
        if tiled_class is not None:
            cls.TILED_CLASS = tiled_class
            cls.OBJECT_TYPES[tiled_class] = cls  # pylint: disable=unsupported-assignment-operation

    @classmethod
    def _from_et(cls, et, path, parent, loader, loaded_memo):
        # pylint: disable=protected-access,unsubscriptable-object,unnecessary-dunder-call,unsupported-membership-test
        # i don't know whether super(...) allows you to explore bases in a mixin and i was too sleepy to find out when writing tihs
        if cls is cls.BASE:
            stype = et.attrib.get(cls.ATTRIB)
            if stype is None or stype not in cls.OBJECT_TYPES:
                return cls.TMX_BASE._from_et.__get__(cls, cls)(et, path, parent, loader, loaded_memo)
            return cls.OBJECT_TYPES[stype]._from_et(et, path, parent, loader, loaded_memo)
        return cls.TMX_BASE._from_et.__get__(cls, cls)(et, path, parent, loader, loaded_memo)

class BaseLoader:
    _TAG_PARSERS = {}
    _STRICT = False

    def __init__(self, convert_alpha=True):
        self.convert_alpha = convert_alpha

    def load(self, path):
        # pylint: disable=protected-access
        loaded_memo = []
        result = self.load_internal(ET.parse(path).getroot(), path, None, loaded_memo)
        for obj in loaded_memo:
            obj.post_load()
        return result

    def load_image(self, path):
        img = pygame.image.load(path)
        if self.convert_alpha:
            return img.convert_alpha()
        return img

    def load_font(self, family, size):
        font = ft.SysFont(family, size, bold=True)
        font.strength = 0
        font.antialiased = False
        return font

    def load_internal(self, et, path, parent, loaded_memo):
        if et.tag not in self._TAG_PARSERS:
            if self._STRICT:
                raise ValueError(f"unknown tag {et.tag}")
            warnings.warn(UserWarning(f"unknown tag {et.tag}"))
        cls2 = self._TAG_PARSERS.get(et.tag, Data)
        return cls2._from_et(et, path, parent, self, loaded_memo)  # pylint: disable=protected-access

    # This is a separate method to facilitate custom loaders
    @classmethod
    def register(cls, cls2):
        cls._TAG_PARSERS[cls2._TAG] = cls2  # pylint: disable=protected-access
        return cls2

    def __init_subclass__(cls, *args, strict=False, use_defaults=True, **kwargs):
        if use_defaults:
            cls._TAG_PARSERS = cls._TAG_PARSERS.copy()
        else:
            cls._TAG_PARSERS = {}
        cls._STRICT = strict

@dataclass
class coerce_custom[T]:  # pylint: disable=invalid-name
    func: Callable[[Any], T]
    _name: str | None = None

    def __set_name__(self, _owner, name):
        self._name = name

    def __get__(self, obj: Any, _objtype: Any = None) -> T:
        return self.func(getattr(obj, "_" + self._name))

    def __set__(self, obj: Any, value: Any) -> None:
        setattr(obj, "_" + self._name, self.func(value))

class Data:

    # def __getattr__(self, obj):
        # pylint will complain about all the dynamic attribute assignment without this
        # raise AttributeError(obj)

    def __init_subclass__(cls, *args, **kwargs):
        # if you're making classes out of untrusted input, that's your problem
        # pylint: disable=eval-used
        if "tag" in kwargs:
            cls._TAG = kwargs["tag"]
        annotations = {}
        for k in cls.__annotations__.keys():
            v = cls.__dict__.get(k, None)
            if not isinstance(v, coerce_custom):
                # don't coerce by default
                v = coerce_custom(lambda x: x)
            annotations[k] = v
        if hasattr(cls, "_TYPES"):
            cls._TYPES.update(annotations)
        else:
            cls._TYPES = annotations

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
        pass

class TileCollection:

    def __init__(self, tilesets):
        self.tilesets = sorted(tilesets, key=lambda x: x.firstgid)

    def __getitem__(self, gid):
        if gid == 0:
            return Tile(None, 0, None)
        tileset_idx = bisect.bisect_left(self.tilesets, gid, key=lambda x: x.firstgid)
        if len(self.tilesets) == tileset_idx or self.tilesets[tileset_idx].firstgid != gid:
            tileset_idx -= 1
        tileset = self.tilesets[tileset_idx]
        return tileset[gid - tileset.firstgid]

@BaseLoader.register
class Map(TypeSpecializable, Data, tag="map", base=True, attrib="class"):
    width: int
    height: int
    tilewidth: int
    tileheight: int
    infinite: int = coerce_custom(lambda x: bool(int(x)))
    nextlayerid: int
    nextobjectid: int
    source: str

    def __repr__(self):
        return f"<Map {os.path.basename(self.source)!r} {self.width}x{self.height}>"

    @classmethod
    def _from_et(cls, et, path, parent, loader, loaded_memo):
        # pylint: disable=attribute-defined-outside-init
        obj = super()._from_et(et, path, parent, loader, loaded_memo)
        obj.source = path
        obj.tilesets = [i for i in obj.data_children if isinstance(i, Tileset)]
        obj.tiles = TileCollection(obj.tilesets)
        obj.layers = [i for i in obj.data_children if isinstance(i, (TileLayer, ObjectGroup, ImageLayer))]
        obj.imgs = [i.img for i in obj.tilesets if i.img is not None]
        obj.imgs.extend([j.img for i in obj.layers if isinstance(i, ObjectGroup) for j in i.objects if j.has_image and j.img is not None])
        obj.imgs.extend([i.img for i in obj.layers if isinstance(i, ImageLayer)])
        return obj

@BaseLoader.register
class Tileset(Data, tag="tileset"):
    tilewidth: int
    tileheight: int
    tilecount: int
    columns: int
    firstgid: int
    tiledata: dict[int, Tile]

    def __repr__(self):
        return f"<Tileset #{self.firstgid}-#{self.firstgid + self.tilecount} (tile size {self.tilewidth}x{self.tileheight})>"

    @classmethod
    def _from_et(cls, et, path, parent, loader, loaded_memo):
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

    def __getitem__(self, tileid):
        if tileid < 0 or tileid >= self.tilecount:
            raise IndexError(f"no tile #{tileid}")
        if tileid in self.tiledata:
            return self.tiledata[tileid]
        return Tile(self, tileid, None)

@BaseLoader.register
class Grid(Data, tag="grid"):
    width: int
    height: int

@BaseLoader.register
class Text(Data, tag="text"):
    fontfamily: str
    pixelsize: int
    wrap: int = coerce_custom(lambda x: bool(int(x)))

    @classmethod
    def _from_et(cls, et, path, parent, loader, loaded_memo):
        obj = super()._from_et(et, path, parent, loader, loaded_memo)
        obj.font = loader.load_font(obj.fontfamily, obj.pixelsize)  # pylint: disable=no-member
        obj.text = et.text
        return obj

@BaseLoader.register
class Image(Data, tag="image"):
    width: int
    height: int
    source: str

    def __repr__(self):
        return f"<Image {os.path.basename(self.source)!r} ({self.width}x{self.height})>"

    @classmethod
    def _from_et(cls, et, path, parent, loader, loaded_memo):
        obj = super()._from_et(et, path, parent, loader, loaded_memo)
        rsrc_path = os.path.join(os.path.dirname(path), et.attrib["source"])
        obj.surface = loader.load_image(rsrc_path)
        return obj

@BaseLoader.register
class Tile(Data, tag="tile"):
    tileset: Tileset
    properties: dict[str, Any] | None = coerce_custom(lambda x: x)
    id: int

    def __repr__(self):
        props = "" if self.properties is None else f" (properties {self.properties})"
        return f"<Tile #{self.gid}{props}>"

    def __init__(self, tileset=None, id_=None, properties=None):
        if id_ is None:
            if tileset is None:
                return
            raise ValueError("__init__ takes 0, 2, or 3 arguments, 1 given")
        self.tileset = tileset
        self.properties = properties
        self.id = id_

    @classmethod
    def _from_et(cls, et, path, parent, loader, loaded_memo):
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

    def __setattr__(self, name, value):
        if hasattr(self, "id"):
            raise AttributeError("Tile objects are immutable")
        return super().__setattr__(name, value)

    def __hash__(self):
        return hash(tuple((self.gid, self.properties)))

    def __eq__(self, other):
        if not isinstance(other, Tile):
            return NotImplemented
        return self.gid == other.gid and self.properties == other.properties

    @property
    def surface(self):
        if self.tileset is None:
            return None
        return self.tileset.img.surface.subsurface(self.rect)

    @property
    def rect(self):
        if self.tileset is None:
            return None
        offsx = (self.id % self.tileset.columns) * self.tileset.tilewidth
        offsy = (self.id // self.tileset.columns) * self.tileset.tileheight
        return pygame.Rect((offsx, offsy, self.tileset.tilewidth, self.tileset.tileheight))

    @property
    def gid(self):
        if self.tileset is None:
            return 0
        return self.tileset.firstgid + self.id

@BaseLoader.register
class Properties(Data, dict, tag="properties"):

    def __init__(self):
        self.frozen = False

    @classmethod
    def _from_et(cls, et, path, parent, loader, loaded_memo):
        obj = super()._from_et(et, path, parent, loader, loaded_memo)
        for i in obj.data_children:
            obj[i.key] = i.value  # pylint: disable=unsupported-assignment-operation
        del obj.data_children
        return obj

    def __hash__(self):
        if not self.frozen:
            raise ValueError("cannot hash unfrozen Properties")
        return hash(tuple(self.items()))

    def __setitem__(self, key, value):
        if self.frozen:
            raise ValueError("frozen object")
        return super().__setitem__(key, value)

    def pop(self, key, default):
        if self.frozen:
            raise ValueError("frozen object")
        return super().pop(key, default)

    def update(self, other):
        if self.frozen:
            raise ValueError("frozen object")
        return super().update(other)

    def clear(self):
        if self.frozen:
            raise ValueError("frozen object")
        return super().clear()

@BaseLoader.register
class Property(Data, tag="property"):

    def __repr__(self):
        return f"<Property {self.key}={self.value!r}>"

    @classmethod
    def _from_et(cls, et, _path, _parent, _loader, loaded_memo):
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
    # For isinstance
    pass

@BaseLoader.register
class TileLayer(TypeSpecializable, LayerBase, tag="layer", base=True, attrib="class"):
    id: int
    width: int
    height: int
    offsetx: float
    offsety: float
    data: LayerData
    map: Map

    def __repr__(self):
        return f"<Layer {self.width}x{self.height}>"

    @classmethod
    def _from_et(cls, et, path, parent, loader, loaded_memo):
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

    def __iter__(self):
        for i, gid in enumerate(self.data):
            yield (i % self.width, i // self.width, self.map.tiles[gid])

@BaseLoader.register
class ImageLayer(TypeSpecializable, LayerBase, tag="imagelayer", base=True, attrib="class"):
    id: int
    offsetx: float
    offsety: float
    img: Image | None

    def __repr__(self):
        return f"<ImageLayer {self.img!r}>"

    @classmethod
    def _from_et(cls, et, path, parent, loader, loaded_memo):
        obj = super()._from_et(et, path, parent, loader, loaded_memo)
        obj.map = parent
        obj.type = getattr(obj, "class")
        delattr(obj, "class")
        obj.img = [i for i in obj.data_children if isinstance(i, Image)][0]
        if not hasattr(obj, "offsetx"):
            obj.offsetx = 0.0
        if not hasattr(obj, "offsety"):
            obj.offsety = 0.0
        return obj

@BaseLoader.register
class ObjectGroup(TypeSpecializable, LayerBase, tag="objectgroup", base=True, attrib="class"):
    id: int
    objects: list[Object]

    def __repr__(self):
        return f"<ObjectGroup {self.objects}>"

    @classmethod
    def _from_et(cls, et, path, parent, loader, loaded_memo):
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
class Object(TypeSpecializable, Data, tag="object", base=True, attrib="type"):
    id: int
    name: str | None
    x: float
    y: float
    width: float
    height: float
    gid: int | None
    text: Text | None
    img: Image | None
    type: str

    def __repr__(self):
        return f"<Object {self.name!r} (type {self.type})>"

    @classmethod
    def _from_et(cls, et, path, parent, loader, loaded_memo):
        obj = super()._from_et(et, path, parent, loader, loaded_memo)
        text = [i for i in obj.data_children if isinstance(i, Text)]
        if text:
            obj.text = text[0]
        if not hasattr(obj, "name"):
            obj.name = None
        return obj

    @property
    def has_tile(self):
        return hasattr(self, "gid")

    @property
    def has_text(self):
        return hasattr(self, "text")

    @property
    def has_image(self):
        return hasattr(self, "img")

    @property
    def tile(self):
        try:
            return self.parent.map.tiles[self.gid]
        except AttributeError:
            raise TypeError("not a tile object") from None

@BaseLoader.register
class LayerData(Data, list, tag="data"):
    width: int
    height: int

    def __init__(self, data, width, height):
        self.extend(data)
        self.width = width
        self.height = height

    @classmethod
    def _from_et(cls, et, _path, parent, _loader, loaded_memo):
        obj = cls([int(i.strip()) for i in et.text.strip().replace("\n", "").split(",") if i is not None], parent.width, parent.height)
        return obj

    def __setitem__(self, *args):
        raise NotImplementedError

    def __getitem__(self, idx):
        if isinstance(idx, tuple):
            if len(idx) != 2:
                raise TypeError("can only index layer data with 2 coordinates or an index")
            return super().__getitem__(idx[1] * self.width + idx[0])
        return super().__getitem__(idx)

if __name__ == "__main__":
    pygame.init()
    tmap = BaseLoader(False).load("/home/gwitr/Dokumenty/tiled/help/test map.tmx")
    print(tmap.layers)
