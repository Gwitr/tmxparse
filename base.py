"""Contains most base classes used by the parser"""

from __future__ import annotations

import os
import sys
import json
import types
import warnings
import xml.etree.ElementTree as ET
from typing import Callable, Any, Type, ClassVar, Union, get_origin, get_args

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
        # pylint: disable=protected-access
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

    xml_child: bool
    xml_text: bool

    json_use_parent_obj: bool
    json_rename_from: str | None

    default: Any
    loader: Callable[[Any], T] | None
    rename_from: str | None
    temporary: bool

    owner: type[Any] | None
    name: str | None
    true_name: str | None

    def __init__(self, rename_from: str | None = None, loader: Callable[[Any], T] | None = None,
                       xml_text: bool = False, xml_child: bool = False, default: Any = None,
                       json_use_parent_obj: bool | None = None, json_rename_from: str | None = None,
                       temporary: bool = False):
        if (loader is not None, bool(xml_text)).count(True) > 1:
            raise ValueError(
                "Only one of loader or xml_text can be set at one time")

        self.rename_from = rename_from
        self.loader = loader
        self.xml_child = bool(xml_child)
        self.xml_text = bool(xml_text)
        self.json_use_parent_obj = bool(json_use_parent_obj)
        self.json_rename_from = json_rename_from
        self.default = default
        self.temporary = temporary

        self.name = None
        self.true_name = None

    def __set_name__(self, owner: type[Any], name: str) -> None:
        self.owner = owner
        self.name = name
        self.true_name = f"_dfield_{name}"

    def type_info(self):
        # pylint: disable=eval-used
        if self.loader:
            return None, None, None
        gvars = sys.modules[self.owner.__module__].__dict__
        annotation = eval(self.owner.__annotations__[self.name], gvars, gvars)
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
        if self.default is not None:
            optional = True
        return annotation, is_list, optional

    def __get__(self, obj, _objtype=None) -> T:
        if obj is None:
            return self
        return getattr(obj, self.true_name)

    def __set__(self, obj, value: T) -> None:
        return setattr(obj, self.true_name, value)

    def __delete__(self, obj) -> None:
        return delattr(obj, self.true_name)

    def load_json_element(self, instance, element, path, _parent, loader, loaded_memo):
        # pylint: disable=unnecessary-dunder-call,protected-access,unnecessary-lambda-assignment
        if self.loader is not None:
            return self.__set__(instance, self.loader(instance, loader))

        annotation, is_list, optional = self.type_info()
        if issubclass(annotation, Data):
            if hasattr(annotation, "TAG"):
                annotation = loader.TAG_PARSERS[annotation.TAG]
            else:
                annotation = tuple(i for i in annotation.collect_subclasses())

        src_name = self.json_rename_from if self.json_rename_from else self.rename_from if self.rename_from else self.name
        try:
            src = element if self.json_use_parent_obj else element[src_name]
        except KeyError:
            if optional:
                return self.__set__(instance, self.default)
            raise ValueError(f"required attribute {self.name} not found") from None

        load = lambda t, x: t._load(x, path, instance, loader, loaded_memo) if issubclass(t, Data) else t(x)
        if is_list:
            if isinstance(annotation, tuple):
                return self.__set__(instance, [load(next(loader.TAG_PARSERS[j.TAG] for j in annotation if j.JSON_MATCH(i)), i) for i in src])
            return self.__set__(instance, [load(annotation, i) for i in src])
        if isinstance(annotation, tuple):
            return self.__set__(instance, load(next(loader.TAG_PARSERS[i.TAG] for i in annotation if i.JSON_MATCH(src)), src))
        return self.__set__(instance, load(annotation, src))

    def load_xml_element(self, instance: Data, loader: BaseLoader, element: ET.Element) -> None:
        # pylint: disable=eval-used,unnecessary-dunder-call
        if self.loader is not None:
            return self.__set__(instance, self.loader(instance, loader))

        if self.xml_text:
            return self.__set__(instance, element.text)

        annotation, is_list, optional = self.type_info()
        if issubclass(annotation, Data):
            if hasattr(annotation, "TAG"):
                annotation = loader.TAG_PARSERS[annotation.TAG]
            else:
                annotation = tuple(annotation.collect_subclasses())

        if self.xml_child:
            children = [i for i in instance.data_children if isinstance(i, annotation)]
            if is_list:
                return self.__set__(instance, children)
            try:
                return self.__set__(instance, children[0])
            except IndexError:
                if optional:
                    return self.__set__(instance, self.default)
                raise ValueError(f"required attribute {self.name} not found") from None

        try:
            return self.__set__(instance, coerce(annotation, element.attrib[self.rename_from if self.rename_from else self.name]))
        except KeyError:
            if optional:
                return self.__set__(instance, self.default)
            raise ValueError(f"required attribute {self.name} not found") from None

class Data:
    """The base class for every element present in a TMX file."""

    TAG: ClassVar[str]
    MAYBE_REMOTE: ClassVar[bool] = False
    CODE: ClassVar[str]
    XML_IGNORE: ClassVar[list[str]]
    LOAD_LIST: ClassVar[list[dfield]]
    DELETE_LIST: ClassVar[list[str]]
    JSON_MATCH: ClassVar[Callable[[Any], bool]]

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
                          xml_child_ignore=None, json_match=None, **kwargs):
        # pylint: disable=exec-used

        super().__init_subclass__(*args, **kwargs)
        if tag is not None:
            if hasattr(cls, "LOAD_LIST"):
                raise ValueError("reserved parameter 'tag'")
            cls.TAG = tag
        if maybe_remote is not None:
            if hasattr(cls, "LOAD_LIST"):
                raise ValueError("reserved parameter 'maybe_remote'")
            cls.MAYBE_REMOTE = maybe_remote
        if json_match is not None:
            if hasattr(cls, "LOAD_LIST"):
                raise ValueError("reserved parameter 'json_match'")
            cls.JSON_MATCH = json_match
        if xml_child_ignore is not None:
            if hasattr(cls, "LOAD_LIST"):
                raise ValueError("reserved parameter 'xml_child_ignore'")
            if not hasattr(cls, "XML_IGNORE"):
                cls.XML_IGNORE = []
            cls.XML_IGNORE.extend(xml_child_ignore)
        if data_base:
            if hasattr(cls, "LOAD_LIST"):
                raise ValueError("reserved parameter 'data_base'")
            load_list_start = []
            load_list_end = []
            delete_list = []
            for name in cls.__annotations__:
                # NOTE: `ClassVar`s have no special handling
                if name not in cls.__dict__:
                    continue
                descriptor = cls.__dict__[name]
                if not isinstance(descriptor, dfield):
                    continue
                if descriptor.loader:
                    load_list_end.append(descriptor)
                else:
                    load_list_start.append(descriptor)
                if descriptor.temporary:
                    delete_list.append(name)
            cls.LOAD_LIST = load_list_start + load_list_end
            cls.DELETE_LIST = delete_list

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
            if cls is Data:
                warnings.warn(UserWarning(f"unknown tag {data_obj.tag}"))
            else:
                for descriptor in cls.LOAD_LIST:
                    descriptor.load_xml_element(obj, loader, data_obj)
            obj.load_xml(loader, data_obj)
        else:
            obj.data_children = None
            for descriptor in cls.LOAD_LIST:
                descriptor.load_json_element(obj, data_obj, path, parent, loader, loaded_memo)
            obj.load_json(data_obj, path, parent, loader, loaded_memo)

        if cls is not Data:
            for name in cls.DELETE_LIST:
                delattr(obj, name)

        loaded_memo.append(obj)
        return obj

    def load_xml(self, _loader: BaseLoader, _element: ET.Element) -> None:
        """Dummy method"""

    def load_json(self, _element: Any, path: str, parent: Data | None, loader: BaseLoader, loaded_memo: list[Data]) -> None:
        """Dummy method"""

    def post_load(self):
        """Method called when the TMX file is fully loaded (calls ran in depth-first order)"""
