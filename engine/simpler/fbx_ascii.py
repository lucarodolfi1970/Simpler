"""ASCII FBX -> binary FBX.

Blender only reads binary FBX, but many programs (Houdini, some 3ds Max/Maya settings, older exporters)
write the text flavour. We parse the text file into Blender's own FBX element tree (io_scene_fbx.encode_bin)
and write it back as binary; the regular importer then reads it as if it had always been binary.
"""
import os
import re

from .core import ApiError
from .i18n import tr

_TOKEN = re.compile(r'''
    (?P<comment>;[^\n]*)
  | (?P<key>[A-Za-z_][A-Za-z0-9_|\- ]*?)\s*:(?!:)
  | (?P<string>"(?:[^"\\]|\\.)*")
  | (?P<star>\*\d+)
  | (?P<number>[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)
  | (?P<lbrace>\{)
  | (?P<rbrace>\})
  | (?P<comma>,)
  | (?P<bare>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<ws>\s+)
''', re.VERBOSE)

INT_P_TYPES = {"int", "integer", "enum", "bool", "visibility inheritance", "intvalue"}
LONG_P_TYPES = {"ktime", "ulonglong", "longlong", "ktimestamp"}
FLOAT32_P_TYPES = {"float"}
FLOAT32_ARRAYS = {"KeyValueFloat", "KeyAttrDataFloat"}
INT64_ARRAYS = {"KeyTime"}
INT32_ARRAYS = {"PolygonVertexIndex", "Edges", "UVIndex", "NormalsIndex", "BinormalsIndex", "TangentsIndex",
                "ColorIndex", "Materials", "Indexes", "Smoothing", "KeyAttrFlags", "KeyAttrRefCount",
                "TextureId", "VisibilityIndex"}


def is_ascii_fbx(path):
    with open(path, "rb") as f:
        head = f.read(23)
    return not head.startswith(b"Kaydara FBX Binary")


class _Node:
    __slots__ = ("name", "values", "children", "array")

    def __init__(self, name):
        self.name, self.values, self.children, self.array = name, [], [], None


def _tokens(text):
    pos, n = 0, len(text)
    for m in _TOKEN.finditer(text):
        if m.start() != pos:
            bad = text[pos:pos + 40].replace("\n", " ")
            raise ApiError(tr("FBX di testo non leggibile vicino a: {0}", bad))
        pos = m.end()
        kind = m.lastgroup
        if kind in ("ws", "comment"):
            continue
        yield kind, m.group(kind)
    if pos != n:
        raise ApiError(tr("FBX di testo non leggibile (fine del file inattesa)"))


def parse(text):
    root = _Node("")
    stack = [root]
    toks = list(_tokens(text))
    i, n = 0, len(toks)
    while i < n:
        kind, val = toks[i]
        if kind == "rbrace":
            stack.pop()
            if not stack:
                raise ApiError(tr("FBX di testo non valido (parentesi)"))
            i += 1
            continue
        if kind != "key":
            raise ApiError(tr("FBX di testo non valido: atteso un nome, trovato {0}", repr(val)))
        node = _Node(val.strip())
        stack[-1].children.append(node)
        i += 1
        expect_value = True
        while i < n:
            kind, val = toks[i]
            if kind == "comma":
                expect_value = True
                i += 1
            elif expect_value and kind in ("string", "number", "bare", "star"):
                if kind == "star":
                    node.array = int(val[1:])
                else:
                    node.values.append((kind, val))
                expect_value = False
                i += 1
            elif kind == "lbrace":
                i += 1
                if node.array is not None:
                    # *N { a: v1,v2,... }
                    nums = []
                    if i < n and toks[i][0] == "key":
                        i += 1
                        while i < n and toks[i][0] in ("number", "comma"):
                            if toks[i][0] == "number":
                                nums.append(toks[i][1])
                            i += 1
                    if i >= n or toks[i][0] != "rbrace":
                        raise ApiError(tr("FBX di testo non valido (array)"))
                    i += 1
                    node.values = nums
                else:
                    stack.append(node)
                break
            else:
                break
    return root


def _unquote(s):
    s = s[1:-1]
    return s.replace("&quot;", '"').replace("&cr;", "\r").replace("&lf;", "\n")


_CLASS_NAME = re.compile(r"^([A-Za-z][A-Za-z0-9]*)::(.*)$", re.S)


def _to_elem(node, FBXElem, parent_name="", in_objects=False):
    e = FBXElem(node.name.encode("utf-8"))
    if node.array is not None:
        vals = node.values
        if node.name in FLOAT32_ARRAYS:
            import array
            e.add_float32_array(array.array("f", (float(v) for v in vals)))
        elif node.name in INT64_ARRAYS:
            import array
            e.add_int64_array(array.array("q", (int(float(v)) for v in vals)))
        elif node.name in INT32_ARRAYS or (vals and all(re.fullmatch(r"[-+]?\d+", v) for v in vals[:200])):
            import array
            ints = [int(v) for v in vals]
            if ints and (max(ints) > 2**31 - 1 or min(ints) < -2**31):
                e.add_int64_array(array.array("q", ints))
            else:
                e.add_int32_array(array.array("i", ints))
        else:
            import array
            e.add_float64_array(array.array("d", (float(v) for v in vals)))
        return e

    is_p = node.name == "P"
    p_type = ""
    for idx, (kind, raw) in enumerate(node.values):
        if kind == "string":
            s = _unquote(raw)
            if is_p and idx == 1:
                p_type = s.lower()
            if not is_p and (in_objects or node.name in ("SceneInfo", "Document")):
                m = _CLASS_NAME.match(s)
                if m:   # "Model::Cube" is stored as "Cube\x00\x01Model" in binary files
                    e.add_string(m.group(2).encode("utf-8") + b"\x00\x01" + m.group(1).encode("utf-8"))
                    continue
            e.add_string(s.encode("utf-8"))
        elif kind == "bare":
            # unquoted letters: a single 'T'/'Y' etc. are chars in some exporters; keep them as strings
            e.add_string(raw.encode("utf-8"))
        else:   # number
            is_int = re.fullmatch(r"[-+]?\d+", raw) is not None
            if is_p and idx >= 4:
                if p_type in LONG_P_TYPES:
                    e.add_int64(int(float(raw)))
                elif p_type in INT_P_TYPES:
                    e.add_int32(int(float(raw)))
                elif p_type in FLOAT32_P_TYPES:
                    e.add_float32(float(raw))
                else:
                    e.add_float64(float(raw))
            elif is_int:
                v = int(raw)
                # object ids and connection ids are 64-bit
                if (in_objects and idx == 0) or node.name in ("C", "Connect") or not (-2**31 <= v < 2**31):
                    e.add_int64(v)
                else:
                    e.add_int32(v)
            else:
                e.add_float64(float(raw))

    for child in node.children:
        e.elems.append(_to_elem(child, FBXElem, node.name, in_objects=(node.name == "Objects")))
    return e


def convert(src, dst):
    """Write a binary copy of the ASCII FBX `src` to `dst`."""
    try:
        from io_scene_fbx import encode_bin
    except ImportError as exc:
        raise ApiError(tr("Componente FBX di Blender non disponibile")) from exc
    with open(src, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    tree = parse(text)
    version = 7400
    m = re.search(r"FBXVersion:\s*(\d+)", text)
    if m:
        version = max(7100, min(int(m.group(1)), 7400))   # 7400 layout: 32-bit offsets, read by every importer
    root = encode_bin.FBXElem(b"")
    for child in tree.children:
        root.elems.append(_to_elem(child, encode_bin.FBXElem))
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    encode_bin.write(dst, root, version)
    return dst
