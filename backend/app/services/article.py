import asyncio
import re
from collections import OrderedDict
from urllib.parse import urljoin, urlparse

import httpx
import nh3
from lxml import html as lxml_html

from app.core import NotFound, Upstream

SOURCES = ("https://arxiv.org/html/{id}", "https://ar5iv.labs.arxiv.org/html/{id}")
NEW_ID = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$")
OLD_ID = re.compile(r"^[a-z\-]+(\.[A-Z]{2})?/\d{7}(v\d+)?$")
MAX_BYTES = 6_000_000
CACHE_SIZE = 48

DROP_CLASSES = (
    "ltx_title_document",
    "ltx_dates",
    "ltx_page_logo",
    "ltx_pagination",
    "ltx_page_footer",
    "ltx_role_creationdate",
    "package-alerts",
    "ltx_leqno",
)

MATH = {
    "math", "semantics", "annotation", "mrow", "mi", "mn", "mo", "mtext", "mspace", "ms",
    "msub", "msup", "msubsup", "munder", "mover", "munderover", "mfrac", "msqrt", "mroot",
    "mfenced", "mtable", "mtr", "mtd", "mlabeledtr", "mstyle", "mpadded", "mphantom",
    "menclose", "merror", "mmultiscripts", "mprescripts", "none", "maligngroup", "malignmark",
}
TAGS = {
    "article", "section", "div", "span", "p", "br", "hr", "a", "em", "strong", "b", "i", "u", "sub", "sup",
    "small", "code", "pre", "blockquote", "ul", "ol", "li", "dl", "dt", "dd", "figure", "figcaption", "img",
    "table", "thead", "tbody", "tfoot", "tr", "td", "th", "caption", "colgroup", "col", "h1", "h2", "h3", "h4",
    "h5", "h6", "cite", "abbr", "time", "mark", "del", "ins", "s", "q", "var", "kbd", "samp", "tt",
} | MATH
MATH_ATTRS = {
    "display", "displaystyle", "scriptlevel", "mathvariant", "mathsize", "mathcolor", "mathbackground", "stretchy",
    "fence", "separator", "accent", "accentunder", "movablelimits", "largeop", "symmetric", "lspace", "rspace",
    "minsize", "maxsize", "linethickness", "columnalign", "rowalign", "columnspacing", "rowspacing", "columnlines",
    "rowlines", "frame", "equalrows", "equalcolumns", "width", "height", "depth", "voffset", "notation", "form",
    "alttext", "encoding", "open", "close", "separators", "href",
}
GENERIC = {"class", "id", "title", "lang", "dir", "colspan", "rowspan", "headers", "scope"}
ATTRS = {tag: set(MATH_ATTRS) if tag in MATH else set() for tag in TAGS}
ATTRS["a"] |= {"href"}
ATTRS["img"] |= {"src", "alt", "width", "height", "loading"}
ATTRS["td"] |= {"align", "valign"}
ATTRS["th"] |= {"align", "valign"}
ATTRS["col"] |= {"span"}
for tag in TAGS:
    ATTRS[tag] |= GENERIC


class ArticleService:
    def __init__(self):
        self.cache: OrderedDict[str, dict] = OrderedDict()
        self.locks: dict[str, asyncio.Lock] = {}

    async def article(self, arxiv_id: str) -> dict:
        key = re.sub(r"v\d+$", "", arxiv_id)
        if not (NEW_ID.match(arxiv_id) or OLD_ID.match(arxiv_id)):
            raise NotFound("this paper has no web version")
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        lock = self.locks.setdefault(key, asyncio.Lock())
        async with lock:
            if key in self.cache:
                return self.cache[key]
            body = await self._build(key)
            self.cache[key] = body
            while len(self.cache) > CACHE_SIZE:
                self.cache.popitem(last=False)
            self.locks.pop(key, None)
            return body

    async def _build(self, arxiv_id: str) -> dict:
        last = ""
        async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": "FrontierReader/1.0"}) as client:
            for template in SOURCES:
                url = template.format(id=arxiv_id)
                try:
                    res = await client.get(url)
                except httpx.HTTPError as exc:
                    last = type(exc).__name__
                    continue
                if res.status_code != 200 or len(res.content) > MAX_BYTES:
                    last = str(res.status_code)
                    continue
                try:
                    result = await asyncio.to_thread(self._clean, res.content, str(res.url))
                except Exception as exc:
                    last = type(exc).__name__
                    continue
                if result:
                    result["source"] = urlparse(url).netloc
                    return result
        if last in ("404", ""):
            raise NotFound("this paper has no web version")
        raise Upstream("the web version could not be read", last)

    def _clean(self, raw: bytes, base: str) -> dict | None:
        doc = lxml_html.fromstring(raw)
        nodes = doc.xpath("//article[contains(concat(' ', normalize-space(@class), ' '), ' ltx_document ')]")
        if not nodes:
            return None
        root = nodes[0]
        for bad in root.xpath(".//script|.//style|.//nav|.//button|.//form|.//iframe|.//object|.//embed|.//svg"):
            bad.getparent().remove(bad)
        for name in DROP_CLASSES:
            for bad in root.xpath(f".//*[contains(concat(' ', normalize-space(@class), ' '), ' {name} ')]"):
                if bad.getparent() is not None:
                    bad.getparent().remove(bad)
        for img in root.xpath(".//img"):
            src = img.get("src") or ""
            if not src or src.startswith("data:"):
                img.getparent().remove(img)
                continue
            full = urljoin(base, src)
            if urlparse(full).scheme not in ("http", "https"):
                img.getparent().remove(img)
                continue
            img.set("src", full)
            img.set("loading", "lazy")
        for node in root.xpath(".//*[@id]"):
            node.set("id", f"a-{node.get('id')}")
        for link in root.xpath(".//a[@href]"):
            href = link.get("href") or ""
            if href.startswith("#"):
                link.set("href", f"#a-{href[1:]}")
            else:
                full = urljoin(base, href)
                if urlparse(full).scheme in ("http", "https"):
                    link.set("href", full)
                else:
                    del link.attrib["href"]
        text = lxml_html.tostring(root, encoding="unicode")
        safe = nh3.clean(
            text,
            tags=TAGS,
            attributes=ATTRS,
            url_schemes={"http", "https"},
            link_rel="noopener noreferrer",
            strip_comments=True,
        )
        if len(safe) < 400:
            return None
        return {"html": safe, "base": base, "math": len(root.xpath(".//math")), "figures": len(root.xpath(".//figure"))}
