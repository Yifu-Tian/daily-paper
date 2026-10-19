"""Validation, deduplication and rendering for the source-grounded research radar."""
from __future__ import annotations
from datetime import datetime
import html
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
ROOT = Path(__file__).resolve().parent

def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))

def write_json(path: Path, value: Any) -> None:
    """Replace a small state file atomically; preserve completed issue artifacts."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)

def now(config: dict[str, Any]) -> datetime:
    return datetime.now(ZoneInfo(config["timezone"]))

def canonical_id(value: str) -> str:
    value = value.strip().lower()
    match = re.search(r"(?:arxiv:|arxiv.org/(?:abs|pdf)/)?(\d{4}\.\d{4,5})(?:v\d+)?", value)
    if match:
        return "arxiv:" + match.group(1)
    return value.removeprefix("https://doi.org/").removeprefix("doi:")

def seen_papers(config: dict[str, Any]) -> list[dict[str, str]]:
    seen = list(config["already_read"])
    for receipt in sorted((ROOT / "archive").glob("*/receipt.json")):
        if read_json(receipt).get("status") not in {"published", "already_published"}:
            continue
        issue = receipt.parent / "digest.json"
        if issue.is_file():
            seen.extend({"id": p["id"], "title": p["title"], "version_date": p["version_date"]}
                        for p in read_json(issue)["papers"])
    return seen

def seen_resources(config: dict[str, Any]) -> list[dict[str, str]]:
    seen = list(config.get("already_read_resources", []))
    for receipt in sorted((ROOT / "archive").glob("*/receipt.json")):
        if read_json(receipt).get("status") not in {"published", "already_published"}:
            continue
        issue = receipt.parent / "digest.json"
        if issue.is_file():
            seen.extend({key: resource[key] for key in ("id", "title", "access_url", "published_at")}
                        for resource in read_json(issue).get("resources", []))
    return seen

def validate_digest(data: dict[str, Any], config: dict[str, Any], issue_date: str) -> None:
    if data["date"] != issue_date:
        raise ValueError("Digest date does not match issue date")
    papers = data["papers"]
    if len(papers) > config["max_papers"]:
        raise ValueError("Too many papers")
    if sum(paper["category"] == "foundational" for paper in papers) > 1:
        raise ValueError("At most one older foundational paper is allowed per digest")
    if not data["overview"].strip() or not data["search_queries"]:
        raise ValueError("Missing overview or search provenance")
    previous = {canonical_id(p["id"]) for p in seen_papers(config)}
    previous_titles = {re.sub(r"\W", "", p["title"].lower()) for p in seen_papers(config)}
    current: set[str] = set()
    for paper in papers:
        key = canonical_id(paper["id"])
        duplicate_title = re.sub(r"\W", "", paper["title"].lower()) in previous_titles
        if key in current or ((key in previous or duplicate_title) and paper["category"] != "update" and not config.get("allow_reissue")):
            raise ValueError(f"Duplicate paper: {key}")
        current.add(key)
        for field in ("title", "authors", "formulation", "sensing_and_actions", "training", "analysis", "openarm_relevance"):
            if not paper[field].strip():
                raise ValueError(f"Missing required paper field {field}: {key}")
        if not paper["institutions"] or any(not item.strip() for item in paper["institutions"]):
            raise ValueError(f"Missing institutions: {key}")
        if any(not paper["reviewer"][field].strip() for field in ("contribution", "strength", "evidence_gap", "comparison", "judgement")):
            raise ValueError(f"Incomplete reviewer judgment: {key}")
        for module in paper["pipeline"]:
            if any(not module[field].strip() for field in ("stage", "method", "input_output")):
                raise ValueError(f"Incomplete pipeline module: {key}")
        figures = paper.get("figures", [])
        if len(figures) < config.get("required_paper_figures", 0) and not paper.get("figures_unavailable_reason", "").strip():
            raise ValueError(f"Missing original pipeline/experiment figures: {key}")
        if paper["reading_level"] != "full_text" or not paper["pipeline"] or not paper["results"]:
            raise ValueError(f"Missing full-text evidence: {key}")
        if not paper["sources"] or not paper["pdf_url"]:
            raise ValueError(f"Missing primary links: {key}")
        for field in ("arxiv_url", "pdf_url", "project_url", "code_url"):
            url = paper[field]
            if url and urlparse(url).scheme != "https":
                raise ValueError(f"Invalid {field}: {key}")
        if paper["arxiv_url"] and canonical_id(paper["arxiv_url"]) != key:
            raise ValueError(f"arXiv link and identifier differ: {key}")
        for result in paper["results"]:
            if not result["evidence"].strip() or not result["source_anchor"].strip():
                raise ValueError(f"Missing result provenance: {key}")
        for source in paper["sources"]:
            match = re.fullmatch(r"\[[^\]]+\]\((https://[^\s)]+)\)", source)
            url = match.group(1) if match else source
            if urlparse(url).scheme != "https":
                raise ValueError(f"Invalid primary source: {key}")
    for entry in papers + data.get("resources", []):
        roles = [figure["role"] for figure in entry.get("figures", [])]
        if len(roles) != len(set(roles)) or any(role not in {"pipeline", "experiment", "context"} for role in roles):
            raise ValueError("Duplicate or invalid figure roles")
        for figure in entry.get("figures", []):
            if not figure["caption"].strip() or not figure["figure_label"].strip():
                raise ValueError("Figure needs an explanatory caption and exact source label")
            if urlparse(figure["source_url"]).scheme != "https":
                raise ValueError("Missing original figure source")
            if figure["image_url"]:
                if urlparse(figure["image_url"]).scheme != "https":
                    raise ValueError("Invalid figure image URL")
            else:
                box = figure["bbox"]
                if figure["pdf_page"] < 1 or len(box) != 4 or not (0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1):
                    raise ValueError("Invalid source PDF region")
    previous_resources = {resource["id"] for resource in seen_resources(config)}
    current_resources: set[str] = set()
    for resource in data.get("resources", []):
        key = resource["id"]
        if not key or key in previous_resources or key in current_resources:
            raise ValueError(f"Duplicate resource: {key}")
        current_resources.add(key)
        if urlparse(resource["access_url"]).scheme != "https":
            raise ValueError(f"Invalid resource access URL: {key}")
        if resource["related_paper_url"] and urlparse(resource["related_paper_url"]).scheme != "https":
            raise ValueError(f"Invalid related paper URL: {key}")
        if not resource["sources"] or any(urlparse(url).scheme != "https" for url in resource["sources"]):
            raise ValueError(f"Missing or invalid resource provenance: {key}")
        for field in ("summary", "research_relevance", "judgement", "source_level", "access_notes"):
            if not resource[field].strip():
                raise ValueError(f"Missing resource {field}: {key}")

def rich_text(value: str) -> str:
    """Escape model text; support only safe HTTPS Markdown links and line breaks."""
    pattern = re.compile(r"\[([^\]]+)\]\((https://[^\s)]+)\)")
    chunks: list[str] = []
    start = 0
    for match in pattern.finditer(value):
        chunks.append(html.escape(value[start:match.start()]))
        chunks.append(f'<a href="{html.escape(match.group(2), quote=True)}">{html.escape(match.group(1))}</a>')
        start = match.end()
    chunks.append(html.escape(value[start:]))
    return "".join(chunks).replace("\n", "<br>")

def render(data: dict[str, Any], config: dict[str, Any], assets: list[dict[str, Any]] | None = None, preview: bool = False) -> str:
    def paragraph(label: str, value: str) -> str:
        return f"<p><strong>{label}</strong> {rich_text(value)}</p>"

    def figures(owner_id: str, role: str) -> str:
        blocks = []
        for asset in assets or []:
            if asset["owner_id"] != owner_id or asset["role"] != role:
                continue
            src = asset.get("preview_src", asset["path"]) if preview else "cid:" + asset["content_id"]
            width = min(asset["width"], 760)
            blocks.append(f"<div style='margin:18px 0;padding:12px;border:1px solid #d5dee8;background:#fff'>"
                          f"<img src='{html.escape(src, quote=True)}' alt='{html.escape(asset['figure_label'], quote=True)}' "
                          f"width='{width}' style='display:block;max-width:100%;height:auto;margin:auto'>"
                          f"<p style='font-size:14px;margin:10px 0 0'><strong>{html.escape(asset['figure_label'])}</strong> "
                          f"{rich_text(asset['caption'])}</p>"
                          f"<p style='font-size:12px;margin:4px 0 0'><a href='{html.escape(asset['source_url'], quote=True)}'>原图及出处</a></p></div>")
        return "\n".join(blocks)

    chunks = ["<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'></head>"
              "<body style='font-family:Arial,Microsoft YaHei,sans-serif;line-height:1.75;color:#18212b'>"
              "<main style='max-width:860px;margin:auto;padding:20px'>",
              f"<h1 style='font-size:24px'>Ego Catching Research Radar · {html.escape(data['date'])}</h1>",
              paragraph("本期导读", data["overview"])]
    kinds = {"tweet": "推文", "thread": "Thread", "talk": "Talk", "video": "视频", "blog": "技术博客",
             "code": "代码 / Release", "dataset": "数据集", "demo": "Demo / 项目", "slides": "Slides",
             "podcast": "播客", "paper_link": "论文线索", "other": "其他"}
    levels = {"full_text": "全文", "transcript": "演讲文字稿", "video_reviewed": "已查看视频",
              "post_text": "已读原帖", "release_notes": "更新说明", "metadata_only": "仅元信息", "partial": "部分材料"}
    resource_chunks = []
    if data.get("resources"):
        resource_chunks.append("<hr><h2 style='font-size:21px'>补充研究资源：推文 / Talk / 代码 / Demo</h2>")
        for resource in data["resources"]:
            resource_chunks.append(f"<h3 style='font-size:17px'>[{kinds.get(resource['kind'], resource['kind'])}] {html.escape(resource['title'])}</h3>")
            resource_chunks.append(paragraph("来自", f"{resource['creator']}；{resource['affiliation']}；{resource['published_at']}"))
            resource_chunks.append(figures(resource["id"], "context"))
            resource_chunks.append(paragraph("讲什么", resource["summary"]))
            resource_chunks.append(paragraph("对你的研究有什么用", resource["research_relevance"]))
            resource_chunks.append(paragraph("证据与判断", levels.get(resource["source_level"], resource["source_level"]) + "；" + resource["judgement"]))
            access = f"[原始入口]({resource['access_url']})；{resource['access_notes']}"
            if resource["related_paper_url"]:
                access += f"；[关联论文]({resource['related_paper_url']})"
            resource_chunks.append(paragraph("哪里看", access))
            if resource["sources"]:
                resource_chunks.append(paragraph("相关入口", " · ".join(f"[来源 {i}]({url})" for i, url in enumerate(resource["sources"], 1))))
    labels = {"core": "核心方向", "adjacent": "相邻方法", "foundational": "基础补读", "update": "版本更新"}
    if data["papers"]:
        chunks.append("<h2 style='font-size:21px'>本期完整论文精读</h2><ol>")
        for paper in data["papers"]:
            chunks.append(f"<li>{html.escape(paper['title'])} — {labels[paper['category']]}</li>")
        chunks.append("</ol>")
    for index, paper in enumerate(data["papers"], 1):
        chunks.append(f"<hr><h2 style='font-size:20px'>{index}. {html.escape(paper['title'])}</h2>")
        chunks.append(paragraph("作者 / 单位", paper["authors"] + " / " + "; ".join(paper["institutions"])))
        chunks.append(paragraph("状态 / 日期", f"{paper['publication']}；首发 {paper['first_posted']}；版本 {paper['version_date']}"))
        links = []
        for key, label in (("arxiv_url", "arXiv"), ("pdf_url", "PDF 下载"), ("project_url", "Project"), ("code_url", "Code")):
            links.append(f'<a href="{html.escape(paper[key], quote=True)}">{label}</a>' if paper[key] else f"{label}：未核实到公开链接")
        chunks.append("<p>" + " · ".join(links) + "</p>")
        chunks.append(paragraph("阅读与相关性", "全文；" + labels[paper["category"]]))
        chunks.append(paragraph("1. Problem formulation", paper["formulation"]))
        chunks.append(paragraph("传感器、机器人与动作", paper["sensing_and_actions"]))
        chunks.append(f"<p id='paper-{index}-pipeline'><strong>2. Pipeline 与重点方法</strong></p>")
        chunks.append(figures(paper["id"], "pipeline"))
        chunks.append("<table style='width:100%;border-collapse:collapse;font-size:14px'>"
                      "<tr style='background:#eaf0f6'><th style='padding:9px;text-align:left'>模块</th>"
                      "<th style='padding:9px;text-align:left'>输入 → 输出</th><th style='padding:9px;text-align:left'>重点方法</th></tr>")
        for module in paper["pipeline"]:
            chunks.append(f"<tr><td style='padding:9px;border:1px solid #d5dee8;vertical-align:top'><strong>{html.escape(module['stage'])}</strong></td>"
                          f"<td style='padding:9px;border:1px solid #d5dee8;vertical-align:top'>{rich_text(module['input_output'])}</td>"
                          f"<td style='padding:9px;border:1px solid #d5dee8;vertical-align:top'>{rich_text(module['method'])}</td></tr>")
        chunks.append("</table>" + paragraph("训练与部署", paper["training"]))
        chunks.append(f"<p id='paper-{index}-experiments'><strong>3. 实验结果（作者报告）</strong></p>")
        chunks.append(figures(paper["id"], "experiment"))
        chunks.append("<ul>")
        for result in paper["results"]:
            chunks.append(f"<li>{rich_text(result['evidence'])}<br><small>{rich_text(result['source_anchor'])}</small></li>")
        chunks.append("</ul>" + paragraph("结果分析", paper["analysis"]))
        chunks.append("<div style='background:#f1f5f9;padding:14px;border-left:4px solid #41677f'>"
                      "<strong>4. Robotics reviewer judgment（客观研究分析）</strong>")
        for key, label in (("contribution", "实际贡献"), ("strength", "最强证据"), ("evidence_gap", "关键证据缺口"), ("comparison", "比较公平性"), ("judgement", "综合判断")):
            chunks.append(paragraph(label, paper["reviewer"][key]))
        chunks.append("</div>" + paragraph("对 OpenArm 的启发与最小实验", paper["openarm_relevance"]))
        source_links = [source if source.startswith("[") else f"[来源 {i}]({source})"
                        for i, source in enumerate(paper["sources"], 1)]
        chunks.append(paragraph("核验来源", "\n".join(source_links)))
        if paper.get("figures_unavailable_reason"):
            chunks.append(paragraph("配图访问说明", paper["figures_unavailable_reason"]))
    if not data["papers"]:
        chunks.append("<p>本期没有新增论文精读；相关推文、talk、代码或其他资源见后文（若有）。</p>")
    chunks.extend(resource_chunks)
    chunks.append("<hr>" + paragraph("检索说明", data["search_notes"]))
    chunks.append(f"<p style='font-size:12px;color:#64748b'>每天 {html.escape(config['send_at'])}，"
                  f"{html.escape(config['timezone'])}。判断依据公开论文及项目材料，未复现实验不表述为本地验证。"
                  "由用户授权的 GitHub Actions 工作流生成。</p></main></body></html>")
    return "\n".join(chunks)
