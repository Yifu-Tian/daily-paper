"""Render complete paper analyses and attributed figures as GitHub Markdown."""
from __future__ import annotations
import re
from typing import Any


def avoid_unrequested_mentions(text: str) -> str:
    """Keep source URLs intact while preventing copied social handles from pinging others."""
    pieces = re.split(r"(https://[^\s)]+)", text)
    return ''.join(piece if piece.startswith('https://') else
                   re.sub(r'(?<![\w/])@(?=[A-Za-z0-9])', '@\u200b', piece) for piece in pieces)


def markdown(data: dict[str, Any], assets: list[dict[str, Any]]) -> str:
    lines = [f"# Ego Catching Research Radar · {data['date']}", "", data["overview"], ""]
    for index, paper in enumerate(data["papers"], 1):
        lines += [f"## {index}. {paper['title']}", "", f"**作者：** {paper['authors']}",
                  f"**单位：** {'; '.join(paper['institutions'])}",
                  f"**发表与版本：** {paper['publication']} · {paper['version_date']}", ""]
        categories = {'core': '核心相关工作', 'adjacent': '相邻工作，需核对传感器与任务差异',
                      'foundational': '旧文补读', 'update': '已有论文的新版本'}
        lines += ["**选题定位：** " + categories[paper['category']], ""]
        lines += [" · ".join(f"[{label}]({paper[key]})" for key, label in
                            [("arxiv_url", "arXiv"), ("pdf_url", "PDF 下载"),
                             ("project_url", "Project"), ("code_url", "Code")] if paper[key]), "",
                  "### Problem formulation", "", paper["formulation"], "",
                  "**观测与动作／训练和部署的区别：** " + paper["sensing_and_actions"], "",
                  "### Pipeline 与关键方法", ""]
        own = [asset for asset in assets if asset["owner_id"] == paper["id"]]
        def figure(role):
            for asset in own:
                if asset["role"] == role:
                    lines.extend([f"![{asset['figure_label']}]({asset['path']})", "", asset["caption"],
                                  f"[原图来源：{asset['figure_label']}]({asset['source_url']})", ""])
        figure("pipeline")
        lines += ["| 模块 | 输入 → 输出 | 关键方法与作用 |", "|---|---|---|"]
        for stage in paper["pipeline"]:
            row = [stage[key].replace("|", "\\|").replace("\n", " ") for key in ("stage", "input_output", "method")]
            lines.append("| " + " | ".join(row) + " |")
        lines += ["", "**训练数据与监督：** " + paper["training"], "", "### 实验结果及分析", ""]
        figure("experiment")
        for result in paper["results"]:
            lines += ["- " + result["evidence"] + " " + result["source_anchor"]]
        lines += ["", paper["analysis"], "", "### Robotics reviewer judgment", ""]
        labels = {"contribution": "实际贡献", "strength": "最强证据", "evidence_gap": "证据缺口",
                  "comparison": "比较是否公平", "judgement": "总体判断"}
        lines += [f"- **{label}：** {paper['reviewer'][key]}" for key, label in labels.items()]
        lines += ["", "**对 OpenArm 的启发与最小实验：** " + paper["openarm_relevance"], ""]
        if paper["figures_unavailable_reason"]:
            lines += ["**配图访问说明：** " + paper["figures_unavailable_reason"], ""]
    if not data["papers"]:
        lines += ["本期没有符合条件的新论文精读。以下为补充资源。", ""]
    if data.get("resources"):
        lines += ["## 补充研究资源", ""]
    for resource in data.get("resources", []):
        lines += [f"### {resource['title']}", "", f"**形式：** {resource['kind']} · **访问层级：** {resource['source_level']}",
                  f"**作者／单位：** {resource['creator']} · {resource['affiliation']}",
                  f"**日期：** {resource['published_at']}", "", resource["summary"], "",
                  "**研究启发：** " + resource["research_relevance"], "",
                  "**中立判断：** " + resource["judgement"], "",
                  f"[Access]({resource['access_url']}) · {resource['access_notes']}", ""]
        if resource["related_paper_url"]:
            lines += [f"[相关论文]({resource['related_paper_url']})", ""]
    lines += ["---", "", "**检索覆盖与限制：** " + data["search_notes"], "",
              "判断依据公开原文；论文报告结果不等于独立复现。内容由定时工作流辅助整理。", ""]
    return "\n".join(lines)
