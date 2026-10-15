"""Read Google's public Vertex batch catalogue; never infer support from an ID.

Model Garden does not expose output modalities and batch support together.
Use the Vertex batch guide's complete support section and each linked model
card. No credentials, AI Studio catalogue, prediction probes, or billable jobs.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timezone, timedelta
from html.parser import HTMLParser
from pathlib import Path
import copy
import re
import queue
import threading
import time
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from .files import read_json, write_json
from .model_parameters import PARAMETER_NAMES, parameter_name, unsupported_generation_parameters

BATCH_URL = "https://docs.cloud.google.com/vertex-ai/generative-ai/docs/multimodal/batch-prediction-gemini?hl=en"
MAX_AGE = timedelta(days=30)
TOTAL_TIMEOUT = 45
MODEL_ID = re.compile(r"gemini-[a-z0-9][a-z0-9.-]*\Z")


class CatalogueError(ValueError):
    pass


@dataclass
class Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)
    parent: object = None

    def text(self):
        return " ".join(" ".join(c.text() if isinstance(c, Node) else c
                                 for c in self.children).split())

    def walk(self, tag=None):
        if tag is None or self.tag == tag:
            yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk(tag)


class Document(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.current = self.root
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs), parent=self.current)
        self.current.children.append(node)
        if tag not in {"br", "img", "hr", "meta", "link", "input", "source", "wbr", "area", "base", "embed", "param", "col"}:
            self.current = node

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        node = self.current
        while node.parent is not None:
            if node.tag == tag:
                self.current = node.parent
                return
            node = node.parent

    def handle_data(self, data):
        if self.current.tag not in {"script", "style"}:
            self.current.children.append(data)


def official_url(url):
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in {"docs.cloud.google.com", "cloud.google.com"} or parts.port not in {None, 443}:
        raise CatalogueError("模型目录链接不是 Google Cloud 官方文档")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "hl=en", ""))


def batch_links(html, base=BATCH_URL):
    """Only links in the support section, never sidebar/navigation links.

    This authority is one HTML document, not a paginated model-list API.
    Follow *all* entries (including unfamiliar future names), with a size bound.
    """
    nodes = list(Document(html).root.walk())
    start = next((i for i, n in enumerate(nodes) if n.tag == "h2" and
                  n.text().lower() == "gemini models that support batch inference"), None)
    if start is None:
        raise CatalogueError("官方批量支持目录结构发生变化")
    links = []
    for node in nodes[start + 1:]:
        if node.tag == "h2":
            break
        if node.tag == "a" and "/models/gemini/" in node.attrs.get("href", ""):
            link = official_url(urljoin(base, node.attrs["href"]))
            if link not in links:
                links.append(link)
    if not links or len(links) > 100:
        raise CatalogueError("官方批量模型列表为空或超出安全上限")
    return links


def _row(root, label):
    return next((n for n in root.walk("tr") if any(
        c.tag in {"th", "td"} and c.text().lower() == label.lower()
        for c in n.children if isinstance(c, Node))), None)


def _feature(root, label):
    for node in root.walk("li"):
        if any(a.text().lower() == label.lower() for a in node.walk("a")):
            text = node.text().lower()
            if "not supported" in text or "unsupported" in text:
                return False
            if re.search(r"\bsupported\b", text):
                return True
    # Older Vertex cards use table cells rather than feature lists.
    row = _row(root, label)
    if row:
        text = row.text().lower()
        if "not supported" in text:
            return False
        if re.search(r"\bsupported\b", text):
            return True
    return None


def parse_card(html, url, location, today=None):
    root = Document(html).root
    document = root
    row = _row(root, "Model ID")
    if row is None:
        raise CatalogueError("官方模型能力页缺少 Model ID")
    ids = [c.text() for c in row.walk("code") if MODEL_ID.fullmatch(c.text())]
    if len(ids) != 1:
        raise CatalogueError("官方模型 ID 不明确")
    model_id = ids[0]
    table = row
    while table.parent is not None and table.tag != "table":
        table = table.parent
    if table.tag != "table":
        raise CatalogueError("官方模型能力表结构发生变化")
    root = table
    modalities = _row(root, "Modalities") or _row(root, "Supported data types")
    if modalities is None:
        raise CatalogueError("官方模型页缺少输入输出能力")
    # Current cards identify each modality independently. Image input is insufficient.
    modality_sections = [n for n in modalities.walk("section")
                         if "geap-modality-support" in n.attrs.get("class", "").split()]
    image_output = any("Image" in n.text() and "output" in n.text().lower()
                       and "not supported" not in n.text().lower()
                       for n in modality_sections)
    if not modality_sections:
        image_output = any(re.search(r"^Outputs?\b", n.text(), re.I) and "Image" in n.text()
                           for n in modalities.walk("li"))
    if not image_output:
        return None
    batch = _feature(root, "Batch inference")
    if batch is None:
        batch = _feature(root, "Batch prediction")
    generate = _feature(root, "GenerateContent API")
    if batch is None:
        raise CatalogueError("生图模型页缺少批量支持标记")
    # Some new cards omit the API section. The official Gemini batch support
    # list establishes its common contents/generationConfig request contract.
    # An explicit incompatible API marker still excludes the model.
    if not batch or generate is False:
        return None
    regions_row = _row(root, "Supported regions")
    if regions_row is None:
        raise CatalogueError("官方模型页缺少区域信息")
    regions = list(dict.fromkeys(c.text() for c in regions_row.walk("code")))
    if not regions:
        raise CatalogueError("无法确认模型区域")
    if location not in regions:
        return None
    # Read the current version's lifecycle, not another version or a navigation link.
    versions = _row(root, "Versions")
    current = next((n for n in versions.walk("li") if any(c.text() == model_id for c in n.walk("code"))), None) if versions else None
    lifecycle = current.text() if current else ""
    if current:
        # Google currently renders version details as a sibling <ul>, rather
        # than nesting them inside the version <li>.
        following = current.parent.children[current.parent.children.index(current) + 1:]
        for node in following:
            if isinstance(node, Node):
                if any(MODEL_ID.fullmatch(c.text()) for c in node.walk("code")):
                    break
                lifecycle += " " + node.text()
    if re.search(r"Launch stage\s*:\s*(Deprecated|Retired|Discontinued)", lifecycle, re.I):
        return None
    retired = re.search(r"Retirement date[^:]*:\s*([A-Za-z]+ \d{1,2}, \d{4})(?!\d)", lifecycle)
    retirement = None
    if retired and "or later" not in lifecycle[retired.end():retired.end() + 20]:
        retirement = datetime.strptime(retired.group(1), "%B %d, %Y").date()
        if retirement <= (today or datetime.now(timezone.utc).date()):
            return None
    title = next((n.text() for n in document.walk("h1")), model_id)
    title = title.split(" Stay organized")[0].strip()
    # Only an explicitly documented imageSize control may be sent to this model.
    supports_size = any("Supported resolutions:" in n.text() for n in root.walk("li"))
    ratios = next((re.findall(r"\b\d+:\d+\b", n.text()) for n in root.walk("li")
                   if "Supported aspect ratios:" in n.text()), [])
    max_refs = next((int(m.group(1)) for n in root.walk("li")
                     if (m := re.search(r"Maximum images per prompt:\s*(\d+)", n.text()))), None)
    parameters = next((n for n in root.walk("tr") if any(
        c.tag in {"th", "td"} and c.text().startswith("Parameter defaults")
        for c in n.children if isinstance(c, Node))), None)
    unsupported = set()
    if parameters:
        for entry in parameters.walk("li"):
            if "not supported" in entry.text().lower():
                unsupported.update(parameter_name(word) for word in re.findall(r"\b[A-Za-z_]+\b", entry.text())
                                   if word.replace("_", "").lower() in PARAMETER_NAMES)
    unsupported = unsupported_generation_parameters(model_id, {"unsupported_parameters": list(unsupported)})
    return {"id": model_id, "label": title, "regions": regions, "source_url": url,
            "supports_image_size": supports_size, "aspect_ratios": ratios,
            "max_references": max_refs, "batch_image_sizes": ["1K"],
            "retirement_date": retirement.isoformat() if retirement else None,
            "unsupported_parameters": sorted(unsupported)}


class OfficialCatalogue:
    def __init__(self, get=None):
        self.get = get or self._get

    @staticmethod
    def _get(url, timeout):
        # Bounded streaming, redirects validated before the next network request.
        end = time.monotonic() + timeout
        for _ in range(5):
            timeout = end - time.monotonic()
            if timeout <= 0:
                raise TimeoutError()
            url = official_url(url)
            with requests.get(url, timeout=(min(3, timeout), min(8, timeout)),
                              allow_redirects=False, stream=True) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers["Location"])
                    continue
                if response.status_code in {404, 410}:
                    return None
                response.raise_for_status()
                if "text/html" not in response.headers.get("Content-Type", ""):
                    raise CatalogueError("官方目录返回了非 HTML 内容")
                data = bytearray()
                for chunk in response.iter_content(65536):
                    data.extend(chunk)
                    if len(data) > 4 * 1024 * 1024 or time.monotonic() > end:
                        raise CatalogueError("官方目录下载超时或过大")
                return data.decode("utf-8")
        raise CatalogueError("官方目录重定向次数过多")

    def discover(self, settings):
        deadline = time.monotonic() + TOTAL_TIMEOUT
        html = self.get(BATCH_URL, TOTAL_TIMEOUT)
        if html is None:
            raise CatalogueError("官方批量支持目录不可用")
        links = batch_links(html)
        def read(url):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError()
            card = self.get(url, remaining)
            return parse_card(card, url, settings.location) if card else None
        pending = queue.Queue()
        results = queue.Queue()
        stopped = threading.Event()
        for url in links:
            pending.put(url)
        def worker():
            while not stopped.is_set():
                try:
                    url = pending.get_nowait()
                except queue.Empty:
                    return
                try:
                    results.put((read(url), None))
                except Exception as exc:
                    results.put((None, exc))
        # Daemon workers are bounded and cannot hold up desktop/process exit.
        for index in range(min(4, len(links))):
            threading.Thread(target=worker, name=f"vbs-model-card-{index}", daemon=True).start()
        models = []
        try:
            for _ in links:
                try:
                    value, error = results.get(timeout=max(.001, deadline - time.monotonic()))
                except queue.Empty:
                    raise TimeoutError() from None
                if error:
                    raise error
                if value:
                    models.append(value)
        finally:
            stopped.set()
        # A verified empty list is valid (e.g. unsupported region). No old-model merge.
        return sorted({m["id"]: m for m in models}.values(), key=lambda m: links.index(m["source_url"]))


class ModelCatalogue:
    def __init__(self, settings, source=None):
        self.settings = settings
        self.source = source or OfficialCatalogue()
        self._lock = threading.Lock()
        self._thread = None
        self._closed = False
        self._state = self._fallback()

    @property
    def scope(self):
        return {"project": self.settings.project, "location": self.settings.location}

    @property
    def path(self):
        import hashlib
        scope = self.settings.project + "\n" + self.settings.location
        return self.settings.data_dir / "model-catalog" / (hashlib.sha256(scope.encode()).hexdigest() + ".json")

    def _fallback(self):
        state = {"models": [], "source": "unavailable", "refreshing": False,
                 "fetched_at": None, "message": "尚未获取官方模型目录；当前配置模型未经验证"}
        try:
            cached = read_json(self.path)
            timestamp = datetime.fromisoformat(cached["fetched_at"])
            age = datetime.now(timezone.utc) - timestamp
            if cached["schema_version"] != 1 or cached["scope"] != self.scope or not timedelta(0) <= age <= MAX_AGE:
                return state
            models = cached["models"]
            if not isinstance(models, list) or any(not isinstance(m, dict) or not MODEL_ID.fullmatch(m.get("id", ""))
                or not isinstance(m.get("label"), str) or self.settings.location not in m.get("regions", [])
                or not isinstance(m.get("supports_image_size"), bool) or official_url(m["source_url"]) != m["source_url"]
                or m.get("batch_image_sizes") != ["1K"] or not isinstance(m.get("aspect_ratios"), list)
                or any(not isinstance(r, str) or not re.fullmatch(r"\d+:\d+", r) for r in m["aspect_ratios"])
                or m.get("max_references") is not None and (type(m["max_references"]) is not int or m["max_references"] < 1)
                or not isinstance(m.get("unsupported_parameters", []), list)
                or any(not isinstance(p, str) or p not in PARAMETER_NAMES.values() for p in m.get("unsupported_parameters", []))
                for m in models):
                return state
            models = [m for m in models if not m.get("retirement_date") or
                      date.fromisoformat(m["retirement_date"]) > datetime.now(timezone.utc).date()]
            state.update(models=models, source="cache", fetched_at=cached["fetched_at"],
                         message="使用上次成功缓存；模型可用性尚未重新确认")
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return state

    def snapshot(self):
        with self._lock:
            state = copy.deepcopy(self._state)
            state["models"] = [m for m in state["models"] if not m.get("retirement_date") or
                               date.fromisoformat(m["retirement_date"]) > datetime.now(timezone.utc).date()]
            for model in state["models"]:
                model["unsupported_parameters"] = sorted(unsupported_generation_parameters(model["id"], model))
            return state

    def validate(self, model):
        state = self.snapshot()
        if state["refreshing"] and state["source"] == "unavailable":
            raise ValueError("正在同步模型目录，请稍后再提交")
        if state["source"] != "unavailable" and model not in {m["id"] for m in state["models"]}:
            raise ValueError("当前模型已不在此区域的批量生图目录中，请选择可用模型")

    def refresh(self):
        with self._lock:
            if self._closed or self._state["refreshing"]:
                return
            self._state["refreshing"] = True
        def run():
            try:
                models = self.source.discover(self.settings)
                fetched = datetime.now(timezone.utc).isoformat()
                message = None
                try:
                    write_json(self.path, {"schema_version": 1, "scope": self.scope,
                                          "fetched_at": fetched, "models": models})
                except OSError:
                    message = "官方模型目录已更新，但缓存写入失败"
                with self._lock:
                    self._state.update(models=models, source="official", fetched_at=fetched, message=message)
            except Exception:
                # Never expose request details, proxy credentials or authentication errors.
                with self._lock:
                    previous = self._state
                    if previous["fetched_at"] and timedelta(0) <= datetime.now(timezone.utc) - datetime.fromisoformat(previous["fetched_at"]) <= MAX_AGE:
                        self._state = previous
                        self._state["source"] = "cache"
                    else:
                        self._state = self._fallback()
                    self._state["message"] = ("同步失败（网络、权限或官方目录变化）；" +
                        ("使用上次成功缓存" if self._state["source"] == "cache" else "当前配置模型未经验证"))
            finally:
                with self._lock:
                    self._state["refreshing"] = False
        self._thread = threading.Thread(target=run, name="vbs-model-catalog", daemon=True)
        self._thread.start()

    def close(self):
        with self._lock:
            self._closed = True
        # Discovery uses bounded HTTP calls; it must not delay desktop shutdown.


def restore_selection(settings):
    from dataclasses import replace
    try:
        value = read_json(settings.root / ".runtime/model-selection.json")
        if value["project"] == settings.project and value["location"] == settings.location and MODEL_ID.fullmatch(value["model"]):
            return replace(settings, model=value["model"])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return settings


def select_model(studio, model):
    from dataclasses import replace
    from .files import operation_lock
    with studio._inflight_lock, operation_lock(studio.settings.root / ".runtime/cloud-config.lock"):
        if studio._inflight:
            from .files import BusyError
            raise BusyError("当前批次操作尚未完成，请稍后再切换模型")
        # Submitted jobs retain manifest IDs; only future preparation uses this preference.
        available = studio.model_catalog.snapshot()["models"]
        if model not in {m["id"] for m in available}:
            raise ValueError("请选择目录中可用的批量生图模型")
        settings = studio.settings
        write_json(settings.root / ".runtime/model-selection.json", {
            "project": settings.project, "location": settings.location, "model": model})
        studio.settings = studio.repo.settings = replace(settings, model=model)
