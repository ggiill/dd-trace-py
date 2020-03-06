import platform
import re
import sys
import textwrap

from ddtrace.vendor import six

__all__ = [
    'httplib',
    'iteritems',
    'PY2',
    'Queue',
    'stringify',
    'StringIO',
    'urlencode',
    'parse',
    'reraise',
]

PYTHON_VERSION_INFO = sys.version_info
PY2 = sys.version_info[0] == 2
PY3 = sys.version_info[0] == 3

# Infos about python passed to the trace agent through the header
PYTHON_VERSION = platform.python_version()
PYTHON_INTERPRETER = platform.python_implementation()

try:
    StringIO = six.moves.cStringIO
except ImportError:
    StringIO = six.StringIO

httplib = six.moves.http_client
urlencode = six.moves.urllib.parse.urlencode
parse = six.moves.urllib.parse
Queue = six.moves.queue.Queue
iteritems = six.iteritems
reraise = six.reraise
reload_module = six.moves.reload_module

stringify = six.text_type
string_type = six.string_types[0]
msgpack_type = six.binary_type
# DEV: `six` doesn't have `float` in `integer_types`
numeric_types = six.integer_types + (float, )

# Pattern class generated by `re.compile`
if PYTHON_VERSION_INFO >= (3, 7):
    pattern_type = re.Pattern
else:
    pattern_type = re._pattern_type


def is_integer(obj):
    """Helper to determine if the provided ``obj`` is an integer type or not"""
    # DEV: We have to make sure it is an integer and not a boolean
    # >>> type(True)
    # <class 'bool'>
    # >>> isinstance(True, int)
    # True
    return isinstance(obj, six.integer_types) and not isinstance(obj, bool)


try:
    from time import time_ns
except ImportError:
    from time import time as _time

    def time_ns():
        return int(_time() * 10e5) * 1000


if PYTHON_VERSION_INFO[0:2] >= (3, 4):
    from asyncio import iscoroutinefunction

    # Execute from a string to get around syntax errors from `yield from`
    # DEV: The idea to do this was stolen from `six`
    #   https://github.com/benjaminp/six/blob/15e31431af97e5e64b80af0a3f598d382bcdd49a/six.py#L719-L737
    six.exec_(textwrap.dedent("""
    import functools
    import asyncio


    def make_async_decorator(tracer, coro, *params, **kw_params):
        \"\"\"
        Decorator factory that creates an asynchronous wrapper that yields
        a coroutine result. This factory is required to handle Python 2
        compatibilities.

        :param object tracer: the tracer instance that is used
        :param function f: the coroutine that must be executed
        :param tuple params: arguments given to the Tracer.trace()
        :param dict kw_params: keyword arguments given to the Tracer.trace()
        \"\"\"
        @functools.wraps(coro)
        @asyncio.coroutine
        def func_wrapper(*args, **kwargs):
            with tracer.trace(*params, **kw_params):
                result = yield from coro(*args, **kwargs)  # noqa: E999
                return result

        return func_wrapper
    """))

else:
    # asyncio is missing so we can't have coroutines; these
    # functions are used only to ensure code executions in case
    # of an unexpected behavior
    def iscoroutinefunction(fn):
        return False

    def make_async_decorator(tracer, fn, *params, **kw_params):
        return fn

# static version of getattr backported from Python 3.7
try:
    from inspect import getattr_static
except ImportError:
    import types

    _sentinel = object()

    def _static_getmro(klass):
        return type.__dict__['__mro__'].__get__(klass)

    def _check_instance(obj, attr):
        instance_dict = {}
        try:
            instance_dict = object.__getattribute__(obj, "__dict__")
        except AttributeError:
            pass
        return dict.get(instance_dict, attr, _sentinel)

    def _check_class(klass, attr):
        for entry in _static_getmro(klass):
            if _shadowed_dict(type(entry)) is _sentinel:
                try:
                    return entry.__dict__[attr]
                except KeyError:
                    pass
        return _sentinel

    def _is_type(obj):
        try:
            _static_getmro(obj)
        except TypeError:
            return False
        return True

    def _shadowed_dict(klass):
        dict_attr = type.__dict__["__dict__"]
        for entry in _static_getmro(klass):
            try:
                class_dict = dict_attr.__get__(entry)["__dict__"]
            except KeyError:
                pass
            else:
                if not (type(class_dict) is types.GetSetDescriptorType and # noqa: E721,E261,W504
                        class_dict.__name__ == "__dict__" and # noqa: E261,W504
                        class_dict.__objclass__ is entry):
                    return class_dict
        return _sentinel

    def getattr_static(obj, attr, default=_sentinel):
        """Retrieve attributes without triggering dynamic lookup via the
        descriptor protocol,  __getattr__ or __getattribute__.

        Note: this function may not be able to retrieve all attributes
        that getattr can fetch (like dynamically created attributes)
        and may find attributes that getattr can't (like descriptors
        that raise AttributeError). It can also return descriptor objects
        instead of instance members in some cases. See the
        documentation for details.
        """
        instance_result = _sentinel
        if not _is_type(obj):
            klass = type(obj)
            dict_attr = _shadowed_dict(klass)
            if (dict_attr is _sentinel or # noqa: E261,E721,W504
                type(dict_attr) is types.MemberDescriptorType):
                instance_result = _check_instance(obj, attr)
        else:
            klass = obj

        klass_result = _check_class(klass, attr)

        if instance_result is not _sentinel and klass_result is not _sentinel:
            if (_check_class(type(klass_result), '__get__') is not _sentinel and # noqa: W504,E261,E721
                _check_class(type(klass_result), '__set__') is not _sentinel):
                return klass_result

        if instance_result is not _sentinel:
            return instance_result
        if klass_result is not _sentinel:
            return klass_result

        if obj is klass:
            # for types we check the metaclass too
            for entry in _static_getmro(type(klass)):
                if _shadowed_dict(type(entry)) is _sentinel:
                    try:
                        return entry.__dict__[attr]
                    except KeyError:
                        pass
        if default is not _sentinel:
            return default
        raise AttributeError(attr)


# DEV: There is `six.u()` which does something similar, but doesn't have the guard around `hasattr(s, 'decode')`
def to_unicode(s):
    """ Return a unicode string for the given bytes or string instance. """
    # No reason to decode if we already have the unicode compatible object we expect
    # DEV: `six.text_type` will be a `str` for python 3 and `unicode` for python 2
    # DEV: Double decoding a `unicode` can cause a `UnicodeEncodeError`
    #   e.g. `'\xc3\xbf'.decode('utf-8').decode('utf-8')`
    if isinstance(s, six.text_type):
        return s

    # If the object has a `decode` method, then decode into `utf-8`
    #   e.g. Python 2 `str`, Python 2/3 `bytearray`, etc
    if hasattr(s, 'decode'):
        return s.decode('utf-8')

    # Always try to coerce the object into the `six.text_type` object we expect
    #   e.g. `to_unicode(1)`, `to_unicode(dict(key='value'))`
    return six.text_type(s)


def get_connection_response(conn):
    """Returns the response for a connection.

    If using Python 2 enable buffering.

    Python 2 does not enable buffering by default resulting in many recv
    syscalls.

    See:
    https://bugs.python.org/issue4879
    https://github.com/python/cpython/commit/3c43fcba8b67ea0cec4a443c755ce5f25990a6cf
    """
    if PY2:
        return conn.getresponse(buffering=True)
    else:
        return conn.getresponse()
