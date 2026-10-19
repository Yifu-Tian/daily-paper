#!/usr/bin/env python3
"""Prepare illustrated research digests and publish through the GitHub bot."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import cloud
import core
from formatting import avoid_unrequested_mentions, markdown
from media import write_bundle


def bundle(data: dict[str, Any], folder: Path, config: dict[str, Any]) -> None:
    assets = write_bundle(data, folder, config, core.render)
    (folder / "digest.md").write_text(markdown(data, assets), encoding="utf-8")
    core.write_json(folder / "digest.json", data)
    core.write_json(folder / "prepared.json", {"date": data["date"], "papers": len(data["papers"]),
                                               "resources": len(data.get("resources", [])),
                                               "images": len(assets), "prepared_at": core.now(config).isoformat()})


def prepare(folder: Path, config: dict[str, Any], issue_date: str, sample: bool = False) -> None:
    if (folder / "prepared.json").is_file():
        print(f"Preserving prepared issue: {folder}")
        return
    folder.mkdir(parents=True, exist_ok=True)
    if sample:
        source = core.ROOT / "examples/illustrated"
        data = core.read_json(source / "digest.json")
        source_date = data["date"]
        data["date"] = issue_date
        data["overview"] = f"【测试样刊，选材与核读日期为 {source_date}】" + data["overview"]
        shutil.copytree(source / "media", folder / "media", dirs_exist_ok=True)
        assets = core.read_json(source / "media.json")
        core.write_json(folder / "media.json", assets)
        (folder / "digest.md").write_text(markdown(data, assets), encoding="utf-8")
        core.write_json(folder / "digest.json", data)
        core.write_json(folder / "prepared.json", {"date": issue_date, "sample": True, "papers": len(data["papers"]),
                                                   "resources": len(data["resources"]), "images": len(assets)})
    else:
        data = cloud.prepare(folder, config, issue_date)
        bundle(data, folder, config)


def github(path: str, method: str = "GET", payload: dict[str, Any] | None = None) -> Any:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise RuntimeError("Publishing requires the Actions GITHUB_TOKEN")
    request = Request("https://api.github.com/" + path, method=method,
                      data=json.dumps(payload).encode() if payload is not None else None,
                      headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
                               "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=45) as handle:
            return json.load(handle)
    except HTTPError as exc:
        message = json.loads(exc.read()).get("message", "GitHub API request failed")
        raise RuntimeError(f"GitHub HTTP {exc.code}: {message}") from None


def commit(folder: Path, message: str) -> None:
    """Stage only the selected issue's public summaries, crops and delivery record."""
    relative = str(folder.relative_to(core.ROOT))
    subprocess.run(["git", "add", "--", relative], cwd=core.ROOT, check=True)
    changed = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=core.ROOT).returncode
    if changed:
        subprocess.run(["git", "-c", "user.name=github-actions[bot]", "-c",
                        "user.email=41898282+github-actions[bot]@users.noreply.github.com",
                        "commit", "-m", message], cwd=core.ROOT, check=True)
        subprocess.run(["git", "push", "origin", "HEAD:main"], cwd=core.ROOT, check=True)


def publish(folder: Path, config: dict[str, Any], issue_date: str, sample: bool = False) -> None:
    receipt = folder / "receipt.json"
    if receipt.is_file():
        print("Already published:", core.read_json(receipt)["url"])
        return
    if not (folder / "prepared.json").is_file():
        raise RuntimeError("No completed issue for today; inspect the prepare workflow, not a fabricated digest")
    repository = config["repository"]
    marker = f"<!-- ego-catching-digest:{folder.name} -->"
    # Reconcile a prior successful API request interrupted before receipt creation.
    existing = github(f"repos/{repository}/issues?state=all&per_page=100&creator=github-actions%5Bbot%5D")
    found = next((item for item in existing if marker in (item.get("body") or "")), None)
    if found is None:
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=core.ROOT, text=True).strip()
        body = (folder / "digest.md").read_text()
        for asset in core.read_json(folder / "media.json"):
            url = f"https://raw.githubusercontent.com/{repository}/{sha}/archive/{folder.name}/{asset['path']}"
            body = body.replace("(" + asset["path"] + ")", "(" + url + ")")
        body = marker + f"\n\n@{config['assignee']} 今天的图文研究日报。\n\n" + avoid_unrequested_mentions(body)
        if len(body) > 65000:
            raise ValueError("Issue body too long; preserve the archive instead of silently truncating paper fields")
        title = ("[测试] " if sample else "") + f"Ego Catching Research Radar · {issue_date}"
        found = github(f"repos/{repository}/issues", "POST", {"title": title, "body": body,
                                                             "assignees": [config["assignee"]]})
    check = github(f"repos/{repository}/issues/{found['number']}")
    if check["user"]["login"] != "github-actions[bot]" or marker not in check["body"]:
        raise RuntimeError("Published issue identity/body verification failed")
    if config["assignee"] not in [user["login"] for user in check["assignees"]]:
        raise RuntimeError("GitHub did not retain the requested assignee")
    core.write_json(receipt, {"status": "published", "number": check["number"], "url": check["html_url"],
                              "publisher": check["user"]["login"], "assignee": config["assignee"],
                              "published_at": check["created_at"], "email_delivery_verified": False})
    print("Published and independently read back:", check["html_url"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["prepare", "publish", "full", "sample"])
    parser.add_argument("--commit", action="store_true", help="Commit public artifacts from GitHub Actions")
    args = parser.parse_args()
    config = core.read_json(core.ROOT / "config.json")
    issue_date = core.now(config).date().isoformat()
    sample = args.mode == "sample"
    folder = core.ROOT / "archive" / (issue_date.replace("-", "") + ("_sample" if sample else ""))
    if args.mode in {"prepare", "full", "sample"}:
        prepare(folder, config, issue_date, sample)
        if args.commit:
            commit(folder, f"Archive research digest for {folder.name}")
    if args.mode in {"publish", "full", "sample"}:
        publish(folder, config, issue_date, sample)
        if args.commit:
            commit(folder, f"Record published digest for {folder.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
