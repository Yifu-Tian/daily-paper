"""Read public primary sources without a paid search API or a local browser."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
import json
import os
from typing import Any
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


class PageText(HTMLParser):
    def __init__(self, url: str):
        super().__init__()
        self.url = url
        self.hidden = 0
        self.text: list[str] = []
        self.links: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style', 'head', 'nav', 'footer'}:
            self.hidden += 1
        values = dict(attrs)
        link = values.get('href') if tag == 'a' else values.get('src') if tag == 'iframe' else None
        if link and not self.hidden:
            absolute = urljoin(self.url, link)
            if absolute.startswith('https://') and absolute not in self.links:
                self.links.append(absolute)

    def handle_endtag(self, tag):
        if tag in {'script', 'style', 'head', 'nav', 'footer'}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, text):
        if not self.hidden and text.strip():
            self.text.append(' '.join(text.split()))


def fetch(url: str) -> bytes:
    headers = {'User-Agent': 'EgoCatchingResearchRadar/1.0 (public-source research)'}
    token = os.environ.get('GITHUB_TOKEN')
    if token and url.startswith('https://api.github.com/'):
        headers['Authorization'] = 'Bearer ' + token
    with urlopen(Request(url, headers=headers), timeout=35) as response:
        content = response.read(1_000_001)
    if len(content) > 1_000_000:
        raise ValueError('Public source exceeded the one-megabyte retrieval bound')
    return content


def arxiv(query: str) -> dict[str, Any]:
    url = 'https://export.arxiv.org/api/query?' + urlencode({
        'search_query': query, 'start': 0, 'max_results': 60, 'sortBy': 'submittedDate', 'sortOrder': 'descending'})
    root = ET.fromstring(fetch(url))
    ns = {'a': 'http://www.w3.org/2005/Atom'}
    papers = []
    for entry in root.findall('a:entry', ns):
        identifier = entry.findtext('a:id', namespaces=ns).rsplit('/', 1)[-1]
        papers.append({
            'id': 'arxiv:' + identifier, 'title': ' '.join(entry.findtext('a:title', namespaces=ns).split()),
            'authors': [node.findtext('a:name', namespaces=ns) for node in entry.findall('a:author', ns)],
            'published': entry.findtext('a:published', namespaces=ns),
            'updated': entry.findtext('a:updated', namespaces=ns),
            'abstract': ' '.join(entry.findtext('a:summary', namespaces=ns).split()),
            'arxiv_url': 'https://arxiv.org/abs/' + identifier,
            'pdf_url': 'https://arxiv.org/pdf/' + identifier,
        })
    return {'url': url, 'kind': 'arxiv_search', 'papers': papers, 'reading_level': 'abstract_metadata'}


def page(url: str) -> dict[str, Any]:
    parser = PageText(url)
    parser.feed(fetch(url).decode('utf-8', errors='replace'))
    text = '\n'.join(parser.text)
    return {'url': url, 'kind': 'primary_page', 'text': text[:18000], 'links': parser.links[:100],
            'reading_level': 'full_text' if len(text) <= 18000 else 'partial'}


def repositories(query: str) -> dict[str, Any]:
    url = 'https://api.github.com/search/repositories?' + urlencode({'q': query, 'sort': 'updated', 'per_page': 10})
    response = json.loads(fetch(url))
    entries = [{key: item.get(key) for key in ['full_name', 'html_url', 'description', 'homepage', 'pushed_at', 'updated_at']}
               for item in response.get('items', [])]
    return {'url': url, 'kind': 'github_search', 'repositories': entries, 'reading_level': 'metadata_only'}


def collect(config: dict[str, Any]) -> dict[str, Any]:
    query = '(cat:cs.RO OR cat:cs.CV) AND (all:catching OR all:"dynamic grasping" OR all:"object interception")'
    github_queries = ['robot catching in:description', '"dynamic grasping" in:description']
    jobs = [('arXiv: ' + query, arxiv, query)]
    jobs += [('GitHub: ' + q, repositories, q) for q in github_queries]
    jobs += [('Primary source: ' + url, page, url) for url in config['primary_resource_pages']]
    sources, failures = [], []
    with ThreadPoolExecutor(max_workers=4) as pool:
        pending = {pool.submit(function, value): label for label, function, value in jobs}
        for future in as_completed(pending):
            label = pending[future]
            try:
                sources.append(future.result())
            except Exception as exc:
                failures.append({'source': label, 'error': str(exc)[:200]})
    if not sources:
        raise RuntimeError('All public-source retrievals failed; no research evidence is available')
    return {'queries': [label for label, _, _ in jobs], 'sources': sources, 'failures': failures}
