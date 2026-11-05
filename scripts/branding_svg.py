"""Accept only standalone, inert SVG icons from optional private branding.

Custom SVGs become publicly accessible files. Reject active content, external
resources and non-graphic elements rather than serving them without review.
The original bytes remain unchanged when accepted to preserve the author's art.
"""
from __future__ import annotations

import re
from xml.etree import ElementTree as ET

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
MAX_ICON_BYTES = 256 * 1024
# Common vector shapes, fills, gradients and filters used by optimized icons.
GRAPHICS = {
    "svg", "g", "defs", "title", "desc", "path", "rect", "circle", "ellipse",
    "line", "polyline", "polygon", "linearGradient", "radialGradient", "stop",
    "clipPath", "mask", "symbol", "use", "pattern", "filter", "feGaussianBlur",
    "feColorMatrix", "feOffset", "feBlend", "feComposite", "feFlood",
    "feMerge", "feMergeNode", "feDropShadow", "feComponentTransfer", "feFuncR",
    "feFuncG", "feFuncB", "feFuncA", "feTurbulence", "feDisplacementMap",
    "feMorphology", "feConvolveMatrix", "feDiffuseLighting", "feSpecularLighting",
    "feDistantLight", "fePointLight", "feSpotLight",
    "text", "tspan", "textPath", "style",
}
# References may only resolve to definitions in the same SVG.
LOCAL_URL = re.compile(r"url\(\s*['\"]?#[a-zA-Z0-9_.:-]+['\"]?\s*\)", re.I)
ANY_URL = re.compile(r"url\(.*?\)", re.I | re.S)
CSS_DANGERS = re.compile(r"@import|@namespace|expression\s*\(|-moz-binding|behavior\s*:|javascript:|data:|https?://", re.I)


def validate_svg(data: bytes, filename: str) -> None:
    """Raise ValueError for markup that isn't a self-contained static SVG."""
    if not data or len(data) > MAX_ICON_BYTES:
        raise ValueError(f"{filename} must be a nonempty SVG of at most 256 KiB")
    lowered = data.lower()
    # The XML declaration is harmless, but other processing instructions
    # (including xml-stylesheet) can request external resources.
    without_declaration = re.sub(rb'^\s*<\?xml\s+[^?]*\?>', b'', lowered, count=1)
    if b'<?' in without_declaration:
        raise ValueError(f"{filename} contains an unsupported XML processing instruction")
    if b'<!doctype' in lowered or b'<!entity' in lowered:
        raise ValueError(f"{filename} cannot contain DTD or entity declarations")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ValueError(f"{filename} is not valid SVG XML: {exc}") from exc
    if root.tag != f"{{{SVG_NS}}}svg":
        raise ValueError(f"{filename} must contain an SVG root element")
    for node in root.iter():
        # Forbid scripts, foreignObject, embedded images, animation, hyperlinks,
        # metadata with unexpected namespaces, and active elements.
        if not isinstance(node.tag, str) or not node.tag.startswith(f"{{{SVG_NS}}}"):
            raise ValueError(f"{filename} contains a foreign SVG element")
        tag = node.tag.rsplit('}', 1)[-1]
        if tag not in GRAPHICS:
            raise ValueError(f"{filename} contains unsupported SVG element: {tag}")
        if tag == 'style' and node.text:
            css = node.text
            if CSS_DANGERS.search(css) or ANY_URL.sub('', css) != LOCAL_URL.sub('', css):
                raise ValueError(f"{filename} has external or unsafe CSS")
        for name, val in node.attrib.items():
            if name.startswith('{'):
                ns, _, bare = name[1:].partition('}')
                if ns not in (SVG_NS, XLINK_NS):
                    raise ValueError(f"{filename} contains a foreign SVG attribute")
            else:
                bare = name
            key = bare.lower()
            value = val.strip()
            if key.startswith('on') or key in ('externalresourcesrequired', 'base', 'src'):
                raise ValueError(f"{filename} contains an unsafe SVG attribute: {bare}")
            if key == 'href':
                if not re.fullmatch(r'#[a-zA-Z0-9_.:-]+', value):
                    raise ValueError(f"{filename} has a nonlocal SVG reference")
            if CSS_DANGERS.search(value):
                raise ValueError(f"{filename} contains an unsafe SVG value")
            if 'url(' in value.lower():
                if ANY_URL.sub('', value) != LOCAL_URL.sub('', value):
                    raise ValueError(f"{filename} has a nonlocal SVG URL")
