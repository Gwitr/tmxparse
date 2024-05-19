"""Contains most base classes used by the parser"""

from __future__ import annotations

import os
import abc
import sys
import json
import types

from typing import TypeVar, Any, Callable, Union, ClassVar, get_origin, get_args

import xml.etree.ElementTree as ET

T = TypeVar("T")
U = TypeVar("U")

def iopen(path, mode="r", **kwargs):
    """case-insensitive open(...) wrapper"""
    path = os.path.abspath(path)
    name = os.path.basename(path).lower()
    dirname = os.path.dirname(path)
    files = {i.lower(): i for i in os.listdir(dirname)}
    if name in files:
        return open(os.path.join(dirname, files[name]), mode, **kwargs)  # pylint: disable=unspecified-encoding
    raise FileNotFoundError(path)

class SpecializableMixin:
    """Mixin that allows a type to be specialized at load time based on an XML attribute"""

    __slots__ = ()

    OBJECT_TYPES: ClassVar[dict[str, type[SpecializableMixin]]]
    OBJECT_BASE: ClassVar[type[SpecializableMixin] | None] = None
    INHERIT_BASE: ClassVar[type[SpecializableMixin] | None] = None
    STRICT: ClassVar[bool] = False

    def __init_subclass__(cls, tiled_class: str | None = None, base: bool = False,
                          attrib: str | None = None, **kwargs):
        super().__init_subclass__(**kwargs)
        if attrib:
            cls.ATTRIB = attrib
        if SpecializableMixin in cls.__bases__:
            cls.INHERIT_BASE = cls
            data_base = [i for i in cls.__bases__ if issubclass(i, Entry)][0]
            if cls.__mro__.index(SpecializableMixin) > cls.__mro__.index(data_base):
                raise TypeError("SpecializableMixin must be resolved before tmxparse.Entry subclass")
        if base:
            cls.OBJECT_TYPES = {}
            cls.OBJECT_BASE = cls
        if tiled_class is not None:
            cls.TILED_CLASS = tiled_class
            cls.OBJECT_TYPES[tiled_class] = cls  # pylint: disable=unsupported-assignment-operation

    @classmethod
    def _load(cls, data: T, parent: Entry | None, ctx: LoaderContext) -> Entry:
        if cls is not cls.OBJECT_BASE:
            return super(SpecializableMixin, cls)._load(data, parent, ctx)  # pylint: disable=no-member

        stype = data.attrib.get(cls.ATTRIB) if isinstance(data, ET.Element) else data.get(cls.ATTRIB)
        if stype is None or stype not in cls.OBJECT_TYPES:
            return super(SpecializableMixin, cls)._load(data, parent, ctx)  # pylint: disable=no-member

        return cls.OBJECT_TYPES[stype]._load(data, parent, ctx)  # pylint: disable=protected-access

class BaseLoader:
    """The base loader class. If you want to use your own data classes, you'll need to inherit from
    this type, and register them under the child class."""

    __slots__ = ()

    PARSERS: dict[str, type[Entry]] = {}
    STRICT: bool = False

    def load(self, path: str):
        """Load a TMX file present at the given path"""

        if path.lower().endswith((".tmx", ".xml")):
            data = ET.parse(path).getroot()
        else:
            with iopen(path, "r", encoding="utf-8") as f:
                data = json.loads(f.read())

        ctx = LoaderContext(self, path)
        result = ctx.load(self.PARSERS["map"], data, None)

        for obj in ctx.loaded_entries_memo:
            obj.post_load()

        return result

    def load_image(self, _path: str) -> Any:
        """Load an image at the given path. Invoked by the loader when encountering images"""
        return None

    def load_font(self, _family: str, _size: float) -> Any:
        """Load a font of a given family and size. Invoked by the loader when loading text"""
        return None

    @classmethod
    def register(cls, cls2: type[Entry]) -> type[Entry]:
        """Attach a Data subclass to this loader. Use this when creating custom loaders"""
        cls.PARSERS[cls2.TAG] = cls2  # pylint: disable=protected-access
        return cls2

    def __init_subclass__(cls, *args, strict=False, use_defaults=True, **kwargs):
        super().__init_subclass__(*args, **kwargs)
        if use_defaults:
            cls.PARSERS = cls.PARSERS.copy()
        else:
            cls.PARSERS = {}
        cls.STRICT = strict

class LoaderContext:
    """Context for a currently ongoing load"""

    def __init__(self, loader, path):
        self.path = path
        self.loader = loader
        self.loaded_entries_memo = []
        self.entry_data_map = {}

    def load(self, cls: type | None, data: T, parent: Entry | None):
        """Loads a JSON or XML datum, attempting to turn it into an instance of the given
        class (whose parent, if possible, will be set to the parameter passed)"""
        if cls is None:
            if isinstance(data, ET.Element):
                cls = self.loader.LOADERS[data.tag]
            else:
                raise ValueError("cannot guess class for JSON object")

        if issubclass(cls, Entry):
            obj = cls._load(data, parent, self)  # pylint: disable=protected-access
            self.loaded_entries_memo.append(obj)
            self.entry_data_map[id(obj)] = data
            return obj
        elif issubclass(cls, (int, float, str)):
            return cls(data)
        elif issubclass(cls, bool):
            return (isinstance(data, bool) and data) or (isinstance(data, str) and data.lower() != "false")
        else:
            raise TypeError(f"can't load {cls}")

    def copy(self, path=None, loader=None, loaded_entries_memo=None):
        """Copies this LoaderContext, optionally with modified properties"""
        ctx = LoaderContext(loader or self.loader, path or self.path)
        ctx.loaded_entries_memo = loaded_entries_memo or self.loaded_entries_memo[:]
        ctx.entry_data_map = self.entry_data_map.copy()
        return ctx

class Field:
    """Information about a field of an Entry"""

    _type_info: tuple[type, bool, bool]

    dst_name: str | None
    owner: type[Entry] | None

    alias: str | None
    default: Any
    xml_child: bool
    xml_text: bool
    loader: Callable[[], ] | None
    xml_rename_from: str | None
    json_rename_from: str | None

    def __init__(self, alias=None, default=None, xml_child=False, xml_text=False, loader=None,
                 xml_rename_from=None, json_rename_from=None, rename_from=None):
        self._type_info = None
        self.dst_name = None
        self.owner = None

        self.alias = alias
        self.default = default
        self.xml_child = xml_child
        self.xml_text = xml_text
        self.loader = loader

        self.xml_rename_from = self.json_rename_from = rename_from
        if xml_rename_from is not None:
            self.xml_rename_from = xml_rename_from
        if json_rename_from is not None:
            self.json_rename_from = json_rename_from

    @property
    def type_info(self):  # pylint: disable=missing-function-docstring
        if self._type_info is None:
            # pylint: disable=eval-used
            if self.loader:
                self._type_info = None, None, None
            else:
                gvars = sys.modules[self.owner.__module__].__dict__
                annotation = eval(self.owner.__annotations__[self.dst_name], gvars, gvars)
                is_list = False
                optional = False
                if get_origin(annotation) in (Union, types.UnionType):
                    optional = True
                    possible_types = list(get_args(annotation))
                    possible_types.remove(Field)
                    if len(possible_types) == 1:
                        optional = False
                    else:
                        if len(possible_types) != 2 or type(None) not in possible_types:
                            raise ValueError("union isn't type")
                        possible_types.remove(type(None))
                    annotation = possible_types[0]
                if get_origin(annotation) is list:
                    is_list = True
                    annotation = get_args(annotation)[0]
                if annotation is None:
                    annotation = type(None)
                if self.default is not None:
                    optional = True
                self._type_info = annotation, is_list, optional
                if is_list and not self.xml_child:
                    raise ValueError("array field must have xml_child set")
        return self._type_info

    def bind(self, name: str, owner: type[Entry]):  # used to be __set_name__ but metaclass magic forced me to abandon that
        """Binds this field to an Entry type"""
        self.dst_name = name
        self.owner = owner

    def load(self, instance: Entry, instance_data: T, parent: Entry | None, ctx: LoaderContext):
        """Loads this field from XML or JSON"""
        loader_class, is_array, optional = self.type_info

        if self.alias is not None:
            try:
                return getattr(instance, self.alias)
            except AttributeError:
                field = instance.FIELDS[self.alias]
                value = field.load(instance, instance_data, parent, ctx)
                setattr(instance, field.dst_name, value)
                return value

        if self.loader:
            return self.loader(instance, instance_data, parent, ctx)

        if isinstance(instance_data, ET.Element):
            src_name = self.dst_name or self.xml_rename_from
            if self.xml_child:
                all_tags = {k: v for k, v in ctx.loader.PARSERS.items() if issubclass(v, loader_class)}
                element_data = [(all_tags[i.tag], i) for i in instance_data if i.tag in all_tags]
                if not is_array:
                    if not element_data:
                        if optional:
                            return self.default
                        raise ValueError(f"no instances of child {loader_class.__qualname__} when 1 expected")
                    if len(element_data) != 1:
                        raise ValueError(f"multiple instances of child {loader_class.__qualname__} when 1 expected")
                    element_data = element_data[0]
            elif self.xml_text:
                return instance_data.text
            else:
                try:
                    element_data = loader_class, instance_data.attrib[src_name]
                except KeyError:
                    if optional:
                        return self.default
                    raise ValueError(f"missing attribute {src_name} on {type(instance).__qualname__}") from None

        else:
            if issubclass(loader_class, Entry) and loader_class.JSON_NO_AUTOLOAD:
                element_data = [[loader_class, None]] if is_array else [loader_class, None]
            else:
                src_name = self.dst_name or self.json_rename_from
                try:
                    elems = [instance_data[src_name]] if not is_array else instance_data[src_name]
                except KeyError:
                    if optional:
                        return self.default
                    raise ValueError(f"missing key {src_name} on {type(instance).__qualname__}") from None

                all_tags = {}
                for v in ctx.loader.PARSERS.values():
                    if issubclass(v, loader_class):
                        all_tags.setdefault(v.JSON_TYPE, []).append(v)

                element_data = []
                for child in elems:
                    if issubclass(loader_class, Entry):
                        possible_types = all_tags[child["type"] if isinstance(child, dict) and "type" in child else EntryMeta.NO_TYPE]
                        if len(possible_types) > 1:
                            ts = ', '.join(i.__qualname__ for i in possible_types.values())
                            raise ValueError(f"ambiguous type for field {self.dst_name} of {instance.__class__.__qualname__}: could be one of {ts}")
                        if len(possible_types) == 0:
                            raise ValueError(f"no fitting type for field {self.dst_name} of {instance.__class__.__qualname__}")
                        value_type = possible_types[0]
                    else:
                        value_type = loader_class
                    element_data.append([value_type, child])

                if not is_array:
                    element_data = element_data[0]

        return [ctx.load(c, i, instance) for c, i in element_data] if is_array else ctx.load(*element_data, instance)

class EntryMeta(abc.ABCMeta):
    """Metaclass of Entry types"""

    class _NO_TYPE:
        pass
    NO_TYPE = _NO_TYPE()

    def __new__(mcs: type[type], name: str, bases: tuple[type, ...], fields: dict[str, Any],
                json_use_parent: bool | None = None, tag: str | None = None, json_type: str | _NO_TYPE = NO_TYPE,
                **kwargs: Any) -> type[Entry]:
        # pylint: disable=invalid-name
        # cursed code thank you __slots__ for being annoying
        for base in bases:
            if hasattr(base, "FIELDS") and "FIELDS" not in fields:
                fields["FIELDS"] = getattr(base, "FIELDS").copy()
                if "__annotations__" not in fields:
                    fields["__annotations__"] = {}
                fields["__annotations__"].update(getattr(base, "__annotations__", {}))
                break

        if "FIELDS" not in fields:
            fields["FIELDS"] = {}
        fields["FIELDS"].update({k: v for k, v in fields.items() if isinstance(v, Field)})
        fields = {k: v for k, v in fields.items() if k not in fields["FIELDS"]}
        fields["__slots__"] = tuple({*fields.get("__slots__", ()), *fields["FIELDS"].keys()})
        cls: type = super().__new__(mcs, name, bases, fields, **kwargs)
        if json_use_parent is not None:
            cls.JSON_USE_PARENT = json_use_parent
        if tag is not None:
            cls.TAG = tag
        if json_type is not EntryMeta.NO_TYPE:
            cls.JSON_TYPE = json_type
        for k, v in cls.FIELDS.items():
            v.bind(k, cls)
        return cls

class Entry(metaclass=EntryMeta):
    """The base class for every element present in a TMX file."""

    JSON_NO_AUTOLOAD = False

    FIELDS: ClassVar[dict[str, Field]]
    TAG: ClassVar[str] = "[unspecified tag]"
    ALLOW_REMOTE: ClassVar[bool] = False
    JSON_USE_PARENT: ClassVar[bool] = False
    JSON_TYPE: ClassVar[str | EntryMeta._NO_TYPE | None] = EntryMeta.NO_TYPE

    __slots__ = "parent",
    parent: Entry | None

    @classmethod
    def _load(cls: type[U], data: T, parent: Entry | None, ctx: LoaderContext) -> U:
        instance = cls()
        instance._fill(data, parent, ctx)
        return instance

    def _fill(self, data: T, parent: Entry | None, ctx: LoaderContext) -> None:
        if isinstance(data, dict) and self.JSON_USE_PARENT:
            data = ctx.entry_data_map[parent]
        self.parent = parent
        for field in self.FIELDS.values():
            setattr(self, field.dst_name, field.load(self, data, parent, ctx))

    @property
    def filename(self):
        """Gets the filename of the root Entry this belongs to"""
        parent = self
        while parent.parent is not None:
            parent = parent.parent
        return parent.source

    @property
    def source(self):
        """Gets the filename of the nearest RemoteEntry this belongs to"""
        parent = self
        while True:
            if isinstance(parent, RemoteEntry) and hasattr(parent, "_source"):
                return parent._source
            parent = parent.parent
            if parent is None:
                raise ValueError("no valid source for this node")

    def post_load(self):
        """Method called when the TMX file is fully loaded (calls ran in depth-first order)"""

class RemoteEntry(Entry):
    """Entry subclass that allows it to be present in a different file from which it is referenced."""

    __slots__ = "_source",
    _source: str

    @classmethod
    def _load(cls: type[U], data: T, parent: Entry | None, ctx: LoaderContext) -> U:
        orig_data = data
        if isinstance(data, dict) and cls.JSON_USE_PARENT:
            data = ctx.entry_data_map[parent]

        rsrc = rsrc_path = None

        if isinstance(data, ET.Element) and "source" in data.attrib:
            src = data.attrib["source"]
            rsrc_path = os.path.join(os.path.dirname(ctx.path), src)
            rsrc = ET.parse(rsrc_path).getroot()
            for k, v in data.attrib.items():
                rsrc.attrib[k] = v
            del rsrc.attrib["source"]

        elif isinstance(data, dict) and "source" in data:
            src = data["source"]
            rsrc_path = os.path.join(os.path.dirname(ctx.path), src)
            with iopen(rsrc_path, "r", encoding="utf-8") as f:
                rsrc = json.loads(f.read())
            for k, v in data.items():
                rsrc[k] = v
            del rsrc["source"]

        if rsrc:
            obj = ctx.copy(path=rsrc_path).load(cls, rsrc, parent)
            obj._source = src
            return obj

        return super()._load(orig_data, parent, ctx)

    def _fill(self, data: T, parent: Entry | None, ctx: LoaderContext) -> None:
        self._source = ctx.path
        super()._fill(data, parent, ctx)
