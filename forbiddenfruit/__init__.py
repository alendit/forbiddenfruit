import ctypes
from functools import wraps
from collections import defaultdict

try:
    import __builtin__
except ImportError:
    # Python 3 support
    import builtins as __builtin__

__version__ = '0.1.0'

__all__ = 'curse', 'reverse'


Py_ssize_t = \
    hasattr(ctypes.pythonapi, 'Py_InitModule4_64') \
    and ctypes.c_int64 or ctypes.c_int


class PyObject(ctypes.Structure):
    pass


PyObject._fields_ = [
    ('ob_refcnt', Py_ssize_t),
    ('ob_type', ctypes.POINTER(PyObject)),
]


class PyIntObject(PyObject):
    pass


PyIntObject._fields_ = PyObject._fields_ + [
    ('ob_ival', ctypes.c_long),
]


class PyTypeObject(ctypes.Structure):
    pass


class FILE(ctypes.Structure):
    pass


class PyNumberMethods(ctypes.Structure):
    _fields_ = [
        ('nb_add',
         ctypes.CFUNCTYPE(
             ctypes.py_object,
             ctypes.py_object,
             ctypes.py_object)),
    ]


FILE_ptr = ctypes.POINTER(FILE)

PyFile_FromFile = ctypes.pythonapi.PyFile_FromFile
PyFile_FromFile.restype = ctypes.py_object
PyFile_FromFile.argtypes = [FILE_ptr,
                            ctypes.c_char_p,
                            ctypes.c_char_p,
                            ctypes.CFUNCTYPE(ctypes.c_int, FILE_ptr)]

PyFile_AsFile = ctypes.pythonapi.PyFile_AsFile
PyFile_AsFile.restype = FILE_ptr
PyFile_AsFile.argtypes = [ctypes.py_object]


PyTypeObject._fields_ = PyObject._fields_ + [
    ('ob_size', Py_ssize_t),
    ('tp_name', ctypes.c_char_p),
    ('tp_basicsize', Py_ssize_t),
    ('tp_itemsize', Py_ssize_t),
    ('tp_dealloc', ctypes.CFUNCTYPE(None, ctypes.POINTER(PyObject))),
    ('tp_print', ctypes.CFUNCTYPE(
        None,
        ctypes.py_object,
        ctypes.POINTER(FILE),
        ctypes.c_int)),
    ('tp_getattr', ctypes.CFUNCTYPE(
        ctypes.py_object,
        ctypes.py_object,
        ctypes.c_char_p)),
    ('tp_getattr', ctypes.CFUNCTYPE(
        ctypes.py_object,
        ctypes.py_object,
        ctypes.py_object)),
    ('tp_compare', ctypes.CFUNCTYPE(
        ctypes.c_int,
        ctypes.py_object,
        ctypes.py_object)),
    ('tp_repr', ctypes.CFUNCTYPE(
        ctypes.py_object,
        ctypes.py_object)),
    ('tp_as_number', ctypes.POINTER(PyNumberMethods)),
]


class SlotsProxy(PyObject):
    _fields_ = [('dict', ctypes.POINTER(PyObject))]


def get_slots(klass):
    # It's important to create variables here, we want those objects alive
    # within this whole scope.
    name = klass.__name__
    target = klass.__dict__

    # Hardcore introspection to find the `PyProxyDict` object that contains the
    # precious `dict` attribute.
    proxy_dict = SlotsProxy.from_address(id(target))
    namespace = {}

    # This is the way I found to `cast` this `proxy_dict.dict` into a python
    # object, cause the `from_address()` function returns the `py_object`
    # version
    ctypes.pythonapi.PyDict_SetItem(
        ctypes.py_object(namespace),
        ctypes.py_object(name),
        proxy_dict.dict,
    )
    return namespace[name]


__global_cache__ = defaultdict(list)


def get_magic_methods(klass, attr, value):
    c_type_inst = PyTypeObject.from_address(id(klass))

    func_class = ctypes.CFUNCTYPE(
        ctypes.py_object,
        ctypes.py_object,
        ctypes.py_object)

    func = func_class(value)
    __global_cache__['nb_add'].append(c_type_inst.tp_as_number.contents.nb_add)
    c_type_inst.tp_as_number.contents.nb_add = func


@wraps(__builtin__.dir)
def __filtered_dir__(obj=None):
    name = hasattr(obj, '__name__') and obj.__name__ or obj.__class__.__name__
    return sorted(set(__dir__(obj)).difference(__hidden_elements__[name]))

# Switching to the custom dir impl declared above
__hidden_elements__ = defaultdict(list)
__dir__ = dir
__builtin__.dir = __filtered_dir__


def curse(klass, attr, value, hide_from_dir=False):
    """Curse a built-in `klass` with `attr` set to `value`

    This function monkey-patches the built-in python object `attr` adding a new
    attribute to it. You can add any kind of argument to the `class`.

    It's possible to attach methods as class methods, just do the following:

      >>> def myclassmethod(cls):
      ...     return cls(1.5)
      >>> curse(float, "myclassmethod", classmethod(myclassmethod))
      >>> float.myclassmethod()
      1.5

    Methods will be automatically bound, so don't forget to add a self
    parameter to them, like this:

      >>> def hello(self):
      ...     return self * 2
      >>> curse(str, "hello", hello)
      >>> "yo".hello()
      "yoyo"
    """
    dikt = get_slots(klass)

    if klass == int and callable(value) and attr.startswith('__'):
        get_magic_methods(klass, attr, value)

    old_value = dikt.get(attr, None)
    old_name = '_c_%s' % attr   # do not use .format here, it breaks py2.{5,6}
    if old_value:
        dikt[old_name] = old_value

    if old_value:
        dikt[attr] = value

        try:
            dikt[attr].__name__ = old_value.__name__
        except (AttributeError, TypeError):  # py2.5 will raise `TypeError`
            pass
        try:
            dikt[attr].__qualname__ = old_value.__qualname__
        except AttributeError:
            pass
    else:
        dikt[attr] = value

    if hide_from_dir:
        __hidden_elements__[klass.__name__].append(attr)


def reverse(klass, attr):
    """Reverse a curse in a built-in object

    This function removes *new* attributes. It's actually possible to remove
    any kind of attribute from any built-in class, but just DON'T DO IT :)

    Good:

      >>> curse(str, "blah", "bleh")
      >>> assert "blah" in dir(str)
      >>> reverse(str, "blah")
      >>> assert "blah" not in dir(str)

    Bad:

      >>> reverse(str, "strip")
      >>> " blah ".strip()
      Traceback (most recent call last):
        File "<stdin>", line 1, in <module>
      AttributeError: 'str' object has no attribute 'strip'

    """
    dikt = get_slots(klass)
    del dikt[attr]
