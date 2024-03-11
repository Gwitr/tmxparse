"""Contains most classes regarding the format"""

from __future__ import annotations

import os
import json
import types
import bisect
import warnings
import xml.etree.ElementTree as ET
from typing import Callable, Any, Type, ClassVar, Generator, Union, get_origin, get_args

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
    def _load(cls, data_obj, path: str, parent: Data | None, loader: BaseLoader,
              loaded_memo: list[Data]) -> Data:
        # pylint: disable=no-member,unsubscriptable-object,protected-access
        if isinstance(data_obj, ET.Element):
            if cls is cls.OBJECT_BASE:
                stype = data_obj.attrib.get(cls.ATTRIB)
                if stype is None or stype not in cls.OBJECT_TYPES:  # pylint: disable=unsupported-membership-test
                    return super(TypeSpecializable, cls)._load(
                        data_obj, path, parent, loader, loaded_memo)
                return cls.OBJECT_TYPES[stype]._load(data_obj, path, parent, loader, loaded_memo)
            return super(TypeSpecializable, cls)._load(data_obj, path, parent, loader, loaded_memo)
        else:
            if cls is cls.OBJECT_BASE:
                stype = data_obj.get(cls.ATTRIB)
                if stype is None or stype not in cls.OBJECT_TYPES:  # pylint: disable=unsupported-membership-test
                    return super(TypeSpecializable, cls)._load(
                        data_obj, path, parent, loader, loaded_memo)
                return cls.OBJECT_TYPES[stype]._load(data_obj, path, parent, loader, loaded_memo)
            return super(TypeSpecializable, cls)._load(data_obj, path, parent, loader, loaded_memo)

class BaseLoader:
    """The base loader class. If you want to use your own data classes, you'll need to inherit from
    this type, and register them under the child class."""

    TAG_PARSERS = {}
    _STRICT = False

    def load(self, path: str):
        """Load a TMX file present at the given path"""
        loaded_memo = []
        if path.lower().endswith((".tmx", ".xml")):
            result = self.load_xml(ET.parse(path).getroot(), path, None, loaded_memo)
        else:
            with open(path, "r", encoding="utf-8") as f:
                # element, path, parent, loader, loaded_memo
                result = self.TAG_PARSERS["map"]._load(json.loads(f.read()), path, None, self, loaded_memo)
        for obj in loaded_memo:
            obj.post_load()
        return result

    def load_image(self, _path: str) -> Any:
        """Load an image at the given path. Invoked by the loader when encountering images"""
        return None

    def load_font(self, _family: str, _size: float) -> Any:
        """Load a font of a given family and size. Invoked by the loader when loading text"""
        return None

    def load_xml(self, et: ET.Element, path: str, parent: Data | None,
                      loaded_memo: list[Data]) -> Data:
        """Load the correct Data subclass for a given Element and loading metadata"""
        if et.tag not in self.TAG_PARSERS:
            if self._STRICT:
                raise ValueError(f"unknown tag {et.tag}")
        cls2 = self.TAG_PARSERS.get(et.tag, Data)
        return cls2._load(et, path, parent, self, loaded_memo)  # pylint: disable=protected-access

    @classmethod
    def register(cls, cls2: Type[Data]) -> Type[Data]:
        """Attach a Data subclass to this loader. Use this when creating custom loaders"""
        cls.TAG_PARSERS[cls2.TAG] = cls2  # pylint: disable=protected-access
        return cls2

    def __init_subclass__(cls, *args, strict=False, use_defaults=True, **kwargs):
        super().__init_subclass__(*args, **kwargs)
        if use_defaults:
            cls.TAG_PARSERS = cls.TAG_PARSERS.copy()
        else:
            cls.TAG_PARSERS = {}
        cls._STRICT = strict

def coerce(to_type, value):
    """turn xml attrib to Python object"""

    try:
        to_type = base_annotation_type(to_type)
    except ValueError:
        raise ValueError(f"can't coerce to {to_type}") from None

    if isinstance(to_type, bool):
        return to_type(int(value))
    return to_type(value)

def base_annotation_type(annotation):
    """fetch type from annotations of the form X, X | None, list[X], list[X] | None"""

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
        raise ValueError(f"{annotation} isn't type")
    return annotation

class alias[T]:  # pylint: disable=invalid-name
    """Descriptor that aliases this property to another one"""

    def __init__(self, to):
        self.to = to

    def __get__(self, obj, _objtype=None) -> T:
        return getattr(obj, self.to)

    def __set__(self, obj, value: T) -> None:
        return setattr(obj, self.to, value)

    def __delete__(self, obj) -> None:
        return delattr(obj, self.to)

class dfield[T]:  # pylint: disable=invalid-name
    """Descriptor that describes a data field in a Tiled element"""

    xml_child_list: bool
    xml_child: bool
    xml_text: bool

    json_use_parent_obj: bool
    json_rename_from: str | None

    optional: bool
    default: Any
    loader: Callable[[Any], T] | None
    rename_from: str | None

    owner: type[Any] | None
    name: str | None
    true_name: str | None

    def __init__(self, rename_from: str | None = None, loader: Callable[[Any], T] | None = None,
                       xml_child_list: bool = False, xml_text: bool = False,
                       xml_child: bool = False, optional: bool = False, default: Any = None,
                       json_use_parent_obj: bool | None = None, json_rename_from: str | None = None):
        if (loader is not None, bool(xml_child_list), bool(xml_text)).count(True) > 1:
            raise ValueError(
                "Only one of loader, xml_child_list, or xml_text can be set at one time")

        self.rename_from = rename_from
        self.loader = loader
        self.xml_child_list = bool(xml_child_list)
        self.xml_child = bool(xml_child)
        self.xml_text = bool(xml_text)
        self.json_use_parent_obj = bool(json_use_parent_obj)
        self.json_rename_from = json_rename_from
        self.optional = bool(optional)
        self.default = default
        self.owner = None
        self.name = None
        self.true_name = None

    def __set_name__(self, owner: type[Any], name: str) -> None:
        self.owner = owner
        self.name = name
        self.true_name = f"_{name}"

    def __get__(self, obj, _objtype=None) -> T:
        if obj is None:
            return self
        return getattr(obj, self.true_name)

    def __set__(self, obj, value: T) -> None:
        return setattr(obj, self.true_name, value)

    def __delete__(self, obj) -> None:
        return delattr(obj, self.true_name)

    def generate_json_load_code(self):
        # pylint: disable=line-too-long
        """Generates a piece of code to slide into the _load_json for this class"""
        typename = self.owner.__annotations__[self.name]
        annotation = eval(typename, globals(), globals())
        is_list = False
        optional = False
        if get_origin(annotation) in (Union, types.UnionType):
            optional = True
            possible_types = list(get_args(annotation))
            if len(possible_types) != 2 or type(None) not in possible_types:
                raise ValueError("union isn't type")
            possible_types.remove(type(None))
            annotation = possible_types[0]
        if get_origin(annotation) is list:
            is_list = True
            annotation = get_args(annotation)[0]
        if annotation is None:
            annotation = type(None)
        typename = annotation.__name__
        if issubclass(annotation, Data) and hasattr(annotation, "TAG"):
            typename = f"loader.TAG_PARSERS[{annotation.TAG!r}]"

        result = ""
        if self.loader is not None:
            result += f"obj_{self.name} = self.__class__.{self.name}.loader(self, loader)\n"
            result += f"if obj_{self.name} is not NotImplemented:\n"
            result += f"    self.{self.name} = obj_{self.name}\n"
        else:
            if self.json_rename_from is not None:
                src_name = self.json_rename_from
            elif self.rename_from is not None:
                src_name = self.rename_from
            else:
                src_name = self.name
            if self.optional or optional:
                result += f"if {src_name!r} in element: "
            src = "element" if self.json_use_parent_obj else f"element[{src_name!r}]"
            if is_list:
                if issubclass(annotation, Data):
                    result += f"self.{self.name} = [{typename}._load(i, path, self, loader, loaded_memo) for i in {src}]\n"
                else:
                    result += f"self.{self.name} = [{typename}(i) for i in {src}]\n"
            else:
                if issubclass(annotation, Data):
                    result += f"self.{self.name} = {typename}._load({src}, path, self, loader, loaded_memo)\n"
                else:
                    result += f"self.{self.name} = {typename}({src})\n"
            if self.optional or optional:
                result += f"else: self.{self.name} = self.__class__.{self.name}.default\n"

        return result

    def load_xml_element(self, instance: Data, loader: BaseLoader, element: ET.Element) -> None:
        # pylint: disable=eval-used,unnecessary-dunder-call
        annotation = eval(self.owner.__annotations__[self.name], globals(), globals())
        isinstance_types = base_annotation_type(annotation).collect_subclasses()

        if self.loader is not None:
            return self.__set__(instance, self.loader(instance, loader))

        if self.xml_text:
            return self.__set__(instance, element.text)

        if self.xml_child:
            children = [i for i in instance.data_children if isinstance(i, isinstance_types)]
            try:
                return self.__set__(instance, children[0])
            except IndexError:
                if self.optional:
                    return self.default
                raise ValueError(f"required attribute {self.name} not found") from None

        if self.xml_child_list:
            return self.__set__(instance, [i for i in instance.data_children if isinstance(i, isinstance_types)])

        try:
            return self.__set__(instance, coerce(annotation,
                element.attrib[self.rename_from if self.rename_from is not None else self.name]
            ))
        except KeyError:
            if self.optional:
                return self.default
            raise ValueError(f"required attribute {self.name} not found") from None

    def generate_xml_load_code(self):
        # pylint: disable=line-too-long
        """Generates a piece of code to slide into the _load_xml for this class"""
        typename = self.owner.__annotations__[self.name]
        isinstance_types = f"base_annotation_type({typename}).collect_subclasses()"

        result = ""
        if self.loader is not None:
            result += f"obj_{self.name} = self.__class__.{self.name}.loader(self, loader)\n"
            result += f"if obj_{self.name} is not NotImplemented:\n"
            result += f"    self.{self.name} = obj_{self.name}\n"

        elif self.xml_text:
            result += f"self.{self.name} = element.text\n"

        elif self.xml_child:
            if self.optional:
                result += f"arr_{self.name} = [i for i in self.data_children if isinstance(i, {isinstance_types})]\n"
                result += f"self.{self.name} = arr_{self.name}[0] if arr_{self.name} else self.__class__.{self.name}.default\n"
            else:
                result +=  "try:\n"
                result += f"    self.{self.name} = [i for i in self.data_children if isinstance(i, {isinstance_types})][0]\n"
                result +=  "except IndexError:\n"
                result += f"    raise ValueError('required attribute {self.name} not found') from None\n"

        elif self.xml_child_list:
            result += f"self.{self.name} = [i for i in self.data_children if isinstance(i, {isinstance_types})]\n"

        else:
            if self.rename_from is not None:
                src_name = self.rename_from
            else:
                src_name = self.name
            if self.optional:
                result += f"if {src_name!r} in element.attrib:\n"
                result += f"    self.{self.name} = coerce({typename}, element.attrib[{src_name!r}])\n"
                result +=  "else:\n"
                result += f"    self.{self.name} = self.__class__.{self.name}.default\n"
            else:
                result += f"self.{self.name} = coerce({typename}, element.attrib[{src_name!r}])\n"

        return result

class Data:
    """The base class for every element present in a TMX file."""

    TAG: ClassVar[str]
    MAYBE_REMOTE: ClassVar[bool] = False
    CODE: ClassVar[str]
    XML_IGNORE: ClassVar[list[str]]
    _TO_INIT: ClassVar[list[type[Data]]] = []

    source: str | None
    parent: Data
    data_path: str
    data_children: list[Data] | None

    @classmethod
    def collect_subclasses(cls):
        """Finds all the subclasses that implement a TMX element"""
        if hasattr(cls, "TAG"):
            return (cls,)
        classes = set()
        for cls2 in cls.__subclasses__():
            if hasattr(cls2, "TAG"):
                classes.add(cls2)
            else:
                classes.update(cls2.collect_subclasses())
        return tuple(classes)

    def __init_subclass__(cls, *args, tag=None, maybe_remote=None, data_base=False,
                          xml_child_ignore=None, **kwargs):
        # pylint: disable=exec-used

        super().__init_subclass__(*args, **kwargs)
        if tag is not None:
            cls.TAG = tag
        if maybe_remote is not None:
            cls.MAYBE_REMOTE = maybe_remote
        if xml_child_ignore is not None:
            if not hasattr(cls, "XML_IGNORE"):
                cls.XML_IGNORE = []
            cls.XML_IGNORE.extend(xml_child_ignore)
        if data_base:
            cls._TO_INIT.append(cls)

    @staticmethod
    def _init_subclasses():
        for cls in Data._TO_INIT:
            xml_code_start = ""
            xml_code_end = ""
            json_code_start = ""
            json_code_end = ""
            for name in cls.__annotations__:
                # NOTE: `ClassVar`s have no special handling
                if name not in cls.__dict__:
                    continue
                descriptor = cls.__dict__[name]
                if not isinstance(descriptor, dfield):
                    continue
                code = descriptor.generate_xml_load_code()
                if descriptor.loader is None:
                    xml_code_start += code
                else:
                    xml_code_end += code
                code = descriptor.generate_json_load_code()
                if descriptor.loader is None:
                    json_code_start += code
                else:
                    json_code_end += code
            xml_code_end += "self.load_xml(loader, element)\n"
            json_code_end += "self.load_json(element, path, parent, loader, loaded_memo)\n"

            xml_code = f"def _load_xml(self, loader, element):\n{xml_code_start}{xml_code_end}"
            xml_code = xml_code.replace("\n", "\n    ")
            exec(xml_code, globals(), globals())
            cls._load_xml = globals()["_load_xml"]
            del globals()["_load_xml"]

            json_code = f"def _load_json(self, element, path, parent, loader, loaded_memo):\n{json_code_start}{json_code_end}"
            json_code = json_code.replace("\n", "\n    ")
            exec(json_code, globals(), globals())
            cls._load_json = globals()["_load_json"]
            cls.JSON_CODE = json_code
            del globals()["_load_json"]

        del Data._TO_INIT

    @classmethod
    def _load(cls, data_obj, path: str, parent: Data | None, loader: BaseLoader,
              loaded_memo: list[Data]) -> Data:
        # pylint: disable=attribute-defined-outside-init
        if cls.MAYBE_REMOTE:
            if isinstance(data_obj, ET.Element):
                if "source" in data_obj.attrib:
                    src = data_obj.attrib["source"]
                    rsrc_path = os.path.join(os.path.dirname(path), src)
                    rsrc = ET.parse(rsrc_path).getroot()
                    for k, v in data_obj.attrib.items():
                        rsrc.attrib[k] = v
                    del rsrc.attrib["source"]
                    obj = loader.load_xml(rsrc, rsrc_path, parent, loaded_memo)
                    obj.source = src
                    return obj
            else:
                if isinstance(data_obj, dict) and "source" in data_obj:
                    src = data_obj["source"]
                    rsrc_path = os.path.join(os.path.dirname(path), src)
                    with open(rsrc_path, "r", encoding="utf-8") as f:
                        rsrc = json.loads(f.read())
                    for k, v in data_obj.items():
                        rsrc[k] = v
                    del rsrc["source"]
                    obj = cls._load(rsrc, rsrc_path, parent, loader, loaded_memo)
                    obj.source = src
                    return obj

        obj = cls()
        obj.parent = parent

        obj.data_path = path
        if cls.MAYBE_REMOTE:
            obj.source = path
        if isinstance(data_obj, ET.Element):
            if hasattr(cls, "XML_IGNORE"):
                obj.data_children = [
                    loader.load_xml(i, path, obj, loaded_memo) for i in data_obj
                    if i.tag not in cls.XML_IGNORE]
            else:
                obj.data_children = [
                    loader.load_xml(i, path, obj, loaded_memo) for i in data_obj]
            obj._load_xml(loader, data_obj)  # pylint: disable=protected-access
        else:
            obj.data_children = None
            print(cls.__name__, parent.__class__.__name__, data_obj)
            if hasattr(obj, "JSON_CODE"):
                print(obj.JSON_CODE)
            obj._load_json(data_obj, path, parent, loader, loaded_memo)  # pylint: disable=protected-access
        loaded_memo.append(obj)
        return obj

    def _load_xml(self, _loader: BaseLoader, element: ET.Element) -> None:
        warnings.warn(UserWarning(f"unknown tag {element.tag}"))

    def _load_json(self, _loader: BaseLoader, element: ET.Element) -> None:
        raise RuntimeError(f"_load_json not defined on loaded Data subclass {self.__class__.__name__}")

    def load_xml(self, _loader: BaseLoader, _element: ET.Element) -> None:
        """Dummy method"""

    def load_json(self, _element: Any, path: str, parent: Data | None, loader: BaseLoader, loaded_memo: list[Data]) -> None:
        """Dummy method"""

    def post_load(self):
        """Method called when the TMX file is fully loaded (calls ran in depth-first order)"""

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

    type: str = dfield(rename_from="class", optional=True)
    width: int = dfield()
    height: int = dfield()
    tilewidth: int = dfield()
    tileheight: int = dfield()
    infinite: bool = dfield()
    nextlayerid: int = dfield()
    nextobjectid: int = dfield()

    tilesets: list[Tileset] = dfield(xml_child_list=True)
    layers: list[LayerBase] = dfield(xml_child_list=True)

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

    _tiles: list[Tile] | None = dfield(xml_child_list=True, rename_from="tiles", optional=True, default=[])
    tiledata: dict[int, Tile] = dfield(loader=lambda obj, _loader: {i.id: i for i in obj._tiles})  # pylint: disable=protected-access

    map: Map = alias("parent")

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
    """A TMX grid object"""
    width: int = dfield()
    height: int = dfield()

@BaseLoader.register
class Text(Data, tag="text", data_base=True):
    """A TMX text element"""

    fontfamily: str = dfield()
    pixelsize: int = dfield()
    wrap: bool = dfield()
    text: str = dfield(xml_text=True)
    color: str = dfield(optional=True, default="#ffffff")

    font: Any = dfield(loader=lambda obj, loader: loader.load_font(obj.fontfamily, obj.pixelsize))

@BaseLoader.register
class Image(Data, tag="image", data_base=True):
    """A TMX image element"""
    width: int | None = dfield(json_rename_from="imagewidth")
    height: int | None = dfield(json_rename_from="imageheight")
    source: str | None = dfield(optional=True, json_rename_from="image")
    surface: Any = dfield(loader=lambda obj, loader: loader.load_image(
        os.path.join(os.path.dirname(obj.data_path), obj.source)))

    def __repr__(self):
        return f"<Image {os.path.basename(self.source)!r} ({self.width}x{self.height})>"

@BaseLoader.register
class Tile(Data, tag="tile", data_base=True, xml_child_ignore=["objectgroup"]):
    """Information about a tile. Immutable"""
    tileset: Tileset = alias("parent")
    id: int = dfield()
    properties: Properties | None = dfield(xml_child=True, optional=True)
    frozen: None = dfield(loader=lambda *_: None)  # loads last

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
        self.frozen = None

    def __setattr__(self, name: str, value: Any) -> None:
        if hasattr(self, "frozen"):
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
class Properties(Data, dict, tag="properties", data_base=True):
    """Properties dictionary for a TMX element"""

    frozen: bool

    def __init__(self):
        self.frozen = False

    def load_xml(self, _loader: BaseLoader, _element: ET.Element) -> None:
        for i in self.data_children:
            self[i.name] = i.value
        del self.data_children

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
    """A key-value pair representing a single property. Usually not too useful"""

    name: str = dfield()
    type: str | None = dfield(optional=True)
    value: str | int | float | bool

    def load_xml(self, _loader: BaseLoader, element: ET.Element) -> None:
        match (self.type or "string"):
            case "bool":
                self.value = element.attrib["value"] == "true"
            case "int":
                self.value = int(element.attrib["value"])
            case "string":
                self.value = element.attrib["value"]
            case x:
                raise ValueError(f"unknown property type {x}")

    def __repr__(self):
        return f"<Property {self.name}={self.value!r}>"

class LayerBase(Data):
    """Base class for all TMX layer types"""

    @classmethod
    def _load(cls, data_obj, path, parent, loader, loaded_memo):
        # TODO: Don't hardcode this like that. Maybe reuse TypeSpecializable?
        if cls is LayerBase and not isinstance(data_obj, ET.Element):
            if data_obj["type"] == "tilelayer":
                return loader.TAG_PARSERS["layer"]._load(data_obj, path, parent, loader, loaded_memo)
            return loader.TAG_PARSERS[data_obj["type"]]._load(data_obj, path, parent, loader, loaded_memo)
        return super()._load(data_obj, path, parent, loader, loaded_memo)

@BaseLoader.register
class TileLayer(LayerBase, tag="layer", data_base=True):
    """A TMX tile layer"""

    # TODO: Reintroduce TypeSpecializable here (mro magic broke it)
    id: int = dfield()
    map: Map = alias("parent")
    width: int = dfield()
    height: int = dfield()
    offsetx: float = dfield(optional=True, default=0.0)
    offsety: float = dfield(optional=True, default=0.0)
    properties: Properties | None = dfield(xml_child=True, optional=True)
    data: LayerData | None = dfield(xml_child=True, optional=True)

    def __repr__(self):
        return f"<Layer {self.width}x{self.height}>"

    def __iter__(self) -> Generator[tuple[int, int, Tile], None, None]:
        for i, gid in enumerate(self.data):
            yield (i % self.width, i // self.width, self.map.tiles[gid])

@BaseLoader.register
class ImageLayer(TypeSpecializable, LayerBase, tag="imagelayer", data_base=True,
                 base=True, attrib="class"):
    """A TMX image layer."""

    id: int = dfield()
    map: Map = alias("parent")
    type: str | None = dfield(rename_from="class", optional=True)
    offsetx: float = dfield(optional=True, default=0.0)
    offsety: float = dfield(optional=True, default=0.0)
    img: Image = dfield(xml_child=True, json_use_parent_obj=True)

    def __repr__(self):
        return f"<ImageLayer {self.img!r}>"

@BaseLoader.register
class ObjectGroup(TypeSpecializable, LayerBase, tag="objectgroup", data_base=True,
                  base=True, attrib="class"):
    """A TMX object group."""

    id: int = dfield()
    map: Map = alias("parent")
    properties: Properties | None = dfield(xml_child=True, optional=True)
    objects: list[Object] = dfield(xml_child_list=True)

    def __repr__(self):
        return f"<ObjectGroup {self.objects}>"

    def load_xml(self, _loader, _element):
        for i in self.objects:
            i.parent = self

@BaseLoader.register
class Object(TypeSpecializable, Data, tag="object", data_base=True, attrib="type"):
    """A TMX object."""

    id: int = dfield()
    type: str = dfield(optional=True)
    name: str | None = dfield(optional=True)
    x: float = dfield()
    y: float = dfield()
    width: float = dfield()
    height: float = dfield()
    gid: int | None = dfield(optional=True)
    text: Text | None = dfield(xml_child=True, optional=True)

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
        try:
            return self.parent.map.tiles[self.gid]
        except AttributeError:
            raise TypeError("not a tile object") from None

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

Data._init_subclasses()
