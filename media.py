"""Retrieve and crop attributed original paper figures with Poppler."""
from __future__ import annotations
import base64
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
from typing import Any
from urllib.request import Request, urlopen

def download(url: str, target: Path, limit: int = 20_000_000) -> bytes:
    if not url.startswith("https://"):
        raise ValueError("Figure and PDF sources must use HTTPS")
    if target.exists():
        return target.read_bytes()
    with urlopen(Request(url, headers={"User-Agent": "ResearchDigest/1.0"}), timeout=45) as response:
        data = response.read(limit + 1)
    if not data or len(data) > limit:
        raise ValueError("Empty or oversized figure source")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(target)
    return data

def image_info(data: bytes) -> tuple[str, int, int]:
    """Read PNG/JPEG dimensions without changing the source image."""
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        width, height = struct.unpack(">II", data[16:24])
        return "image/png", width, height
    if data.startswith(b"\xff\xd8"):
        position = 2
        while position + 4 <= len(data):
            if data[position] != 0xFF:
                position += 1
                continue
            while position < len(data) and data[position] == 0xFF:
                position += 1
            marker = data[position]
            position += 1
            if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
                continue
            length = int.from_bytes(data[position:position + 2], "big")
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                height, width = struct.unpack(">HH", data[position + 3:position + 7])
                return "image/jpeg", width, height
            if length < 2:
                break
            position += length
    raise ValueError("Expected a real PNG or JPEG, not HTML or an unsupported image")

def pdf_region(pdf: Path, page: int, bbox: list[float], target: Path, dpi: int = 180) -> None:
    """Extract a verified PDF region; bbox is normalized left/top/right/bottom."""
    if len(bbox) != 4 or not (0 <= bbox[0] < bbox[2] <= 1 and 0 <= bbox[1] < bbox[3] <= 1):
        raise ValueError("Invalid normalized PDF crop bounds")
    if page < 1:
        raise ValueError("PDF pages are numbered from one")
    info = subprocess.check_output(["pdfinfo", "-f", str(page), "-l", str(page), str(pdf)], text=True)
    match = re.search(r"(?:Page\s+\d+\s+size|Page size):\s*([\d.]+) x ([\d.]+) pts", info)
    if not match:
        raise ValueError("Cannot determine PDF page size")
    width, height = (float(value) * dpi / 72 for value in match.groups())
    x, y = round(bbox[0] * width), round(bbox[1] * height)
    w, h = round((bbox[2] - bbox[0]) * width), round((bbox[3] - bbox[1]) * height)
    subprocess.run(["pdftoppm", "-f", str(page), "-l", str(page), "-singlefile", "-r", str(dpi),
                    "-x", str(x), "-y", str(y), "-W", str(w), "-H", str(h), "-jpeg",
                    "-jpegopt", "quality=88", str(pdf), str(target.with_suffix(""))], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

def prepare_figures(data: dict[str, Any], folder: Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    directory = folder / "media"
    directory.mkdir(exist_ok=True)
    collections = [("paper", data["papers"]), ("resource", data.get("resources", []))]
    for kind, entries in collections:
        for index, entry in enumerate(entries, 1):
            maximum = config.get("max_figures_per_paper", 2) if kind == "paper" else 1
            for figure in entry.get("figures", [])[:maximum]:
                if len(assets) >= config.get("max_figures_per_issue", 8):
                    break
                stem = f"{kind}_{index:02d}_{figure['role']}"
                if figure["image_url"]:
                    provisional = directory / (stem + ".source")
                    payload = download(figure["image_url"], provisional, 8_000_000)
                    mime, width, height = image_info(payload)
                    target = directory / (stem + (".png" if mime == "image/png" else ".jpg"))
                    target.write_bytes(payload)
                else:
                    pdf = directory / f"{kind}_{index:02d}.pdf"
                    payload = download(entry.get("pdf_url") or figure["source_url"].split("#")[0], pdf)
                    if not payload.startswith(b"%PDF-"):
                        raise ValueError("Figure PDF source did not return a PDF")
                    target = directory / (stem + ".jpg")
                    pdf_region(pdf, figure["pdf_page"], figure["bbox"], target)
                    payload = target.read_bytes()
                    mime, width, height = image_info(payload)
                if min(width, height) < 40:
                    raise ValueError("Figure is too small to be useful")
                assets.append({"owner_id": entry["id"], "kind": kind, **figure,
                               "path": str(target.relative_to(folder)), "mime_type": mime,
                               "content_id": stem + "@ego-digest", "width": width, "height": height,
                               "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
    return assets

def write_bundle(data: dict[str, Any], folder: Path, config: dict[str, Any], renderer: Any) -> list[dict[str, Any]]:
    assets = prepare_figures(data, folder, config)
    (folder / "media.json").write_text(json.dumps(assets, ensure_ascii=False, indent=2) + "\n")
    (folder / "digest.html").write_text(renderer(data, config, assets=assets), encoding="utf-8")
    preview_assets = [{**asset, "preview_src": "data:" + asset["mime_type"] + ";base64," +
                       base64.b64encode((folder / asset["path"]).read_bytes()).decode("ascii")} for asset in assets]
    (folder / "preview.html").write_text(renderer(data, config, assets=preview_assets, preview=True), encoding="utf-8")
    return assets
