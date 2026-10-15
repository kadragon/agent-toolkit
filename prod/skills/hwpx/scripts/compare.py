#!/usr/bin/env python3
"""Read-only, conservative content comparison for same-form HWPX documents.

Exit codes: 0 complete/unchanged, 1 complete/changed, 2 incomplete, 3 error.
Locations use one-based ordinals and cellAddr grid coordinates, scoped by parents.
"""
from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
import zlib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from zipfile import BadZipFile, ZipFile

import defusedxml.ElementTree as DET
from defusedxml.common import DefusedXmlException

from _common import NS_HP, NS_HS, PLACEHOLDER_IDS, SECTION_RE, configure_io


def hp(name: str) -> str:
    return f"{{{NS_HP}}}{name}"


def canonical(el: ET.Element, *, mask_text=False, skip_cache=False) -> tuple:
    """Expanded names and sorted attributes remove serialization-only differences.

    Ignore indentation outside text elements, but preserve every character in hp:t.
    Only explicitly modeled text nodes are masked in a residual comparison.
    """
    if mask_text and el.tag == hp('t'):
        return (el.tag, tuple(sorted(el.attrib.items())))
    children = tuple(canonical(c, mask_text=mask_text, skip_cache=skip_cache)
                     for c in el if not (skip_cache and c.tag == hp('linesegarray')))
    text = el.text or ''
    tail = el.tail or ''
    return (el.tag, tuple(sorted(el.attrib.items())),
            text if text.strip() or el.tag == hp('t') else '',
            tail if tail.strip() else '', children)


@dataclass
class Node:
    kind: str
    location: str
    element: ET.Element
    text: str = ''
    children: list[Node] = field(default_factory=list)
    shape: tuple = ()
    span: dict = field(default_factory=dict)

    def signature(self) -> tuple:
        return (self.kind, self.shape)

    def content(self) -> tuple:
        return (self.text, tuple(c.content() for c in self.children))


@dataclass
class Document:
    sections: dict[str, Node]
    members: dict[str, bytes | tuple]
    residuals: dict[str, tuple]
    caches: dict[str, tuple]
    exclusions: list[dict]


class Reader:
    def __init__(self):
        self.exclusions: list[dict] = []

    def excluded(self, el: ET.Element, location: str, reason: str):
        self.exclusions.append({'location': location, 'reason': reason, 'tag': el.tag})

    def text(self, el: ET.Element, location: str) -> str:
        parts = [el.text or '']
        for child in el:
            if child.tag == hp('tab'):
                parts.append('\t')
            elif child.tag == hp('lineBreak'):
                parts.append('\n')
            else:
                self.excluded(child, location, 'unsupported inline text object')
            parts.append(child.tail or '')
        return ''.join(parts)

    def paragraph(self, el: ET.Element, location: str) -> Node:
        node = Node('paragraph', location, el)
        parts = []
        for child in el:
            if child.tag == hp('linesegarray'):
                continue
            if child.tag != hp('run'):
                self.excluded(child, location, 'unsupported paragraph child')
                continue
            for item in child:
                if item.tag == hp('t'):
                    parts.append(self.text(item, location))
                elif item.tag == hp('tbl'):
                    node.children.append(self.table(item, f'{location}/table[{len(node.children)+1}]'))
                elif item.tag not in {hp('secPr'), hp('colPr')}:
                    self.excluded(item, location, 'unsupported run object/control')
        node.text = ''.join(parts)
        return node

    def table(self, el: ET.Element, location: str) -> Node:
        if el.find('.//' + hp('tbl')) is not None:
            self.excluded(el, location, 'nested tables are unsupported in v1')
            return Node('unsupported_table', location, el)
        for child in el:
            if child.tag != hp('tr'):
                self.excluded(child, location, 'table metadata/object outside text coverage')
        try:
            rows, cols = int(el.attrib['rowCnt']), int(el.attrib['colCnt'])
            if rows <= 0 or cols <= 0:
                raise ValueError('non-positive grid dimensions')
            trs = el.findall(hp('tr'))
            if len(trs) != rows:
                raise ValueError('rowCnt does not match serialized rows')
            cells = []
            occupied = []
            for tr in trs:
                for child in tr:
                    if child.tag != hp('tc'):
                        self.excluded(child, location, 'unsupported table row child')
                for tc in tr.findall(hp('tc')):
                    addr, span = tc.find(hp('cellAddr')), tc.find(hp('cellSpan'))
                    if addr is None or span is None:
                        raise ValueError('cellAddr/cellSpan missing')
                    r, c = int(addr.attrib['rowAddr']), int(addr.attrib['colAddr'])
                    rs, cs = int(span.attrib['rowSpan']), int(span.attrib['colSpan'])
                    if min(r, c) < 0 or min(rs, cs) <= 0 or r+rs > rows or c+cs > cols:
                        raise ValueError('cell outside table grid')
                    if any(r < rr+rrs and rr < r+rs and c < cc+ccs and cc < c+cs
                           for rr, cc, rrs, ccs in occupied):
                        raise ValueError('overlapping cells')
                    occupied.append((r, c, rs, cs))
                    loc = f'{location}/row[{r+1}]/col[{c+1}]'
                    cell = Node('cell', loc, tc, shape=(r, c, rs, cs),
                                span={'rows': rs, 'columns': cs})
                    for child in tc:
                        if child.tag not in {hp('subList'), hp('cellAddr'), hp('cellSpan'),
                                            hp('cellSz'), hp('cellMargin')}:
                            self.excluded(child, loc, 'unsupported cell object')
                    sublists = tc.findall(hp('subList'))
                    if len(sublists) != 1:
                        raise ValueError('cell must have one subList')
                    for p in sublists[0]:
                        if p.tag == hp('p'):
                            cell.children.append(self.paragraph(p, f'{loc}/paragraph[{len(cell.children)+1}]'))
                        else:
                            self.excluded(p, loc, 'unsupported cell child')
                    cells.append(cell)
            if sum(rs*cs for _, _, rs, cs in occupied) != rows * cols:
                raise ValueError('table grid has uncovered positions')
        except (KeyError, ValueError) as exc:
            raise ValueError(f'{location}: invalid cell grid: {exc}') from exc
        return Node('table', location, el, children=sorted(cells, key=lambda n: n.shape), shape=(rows, cols))

    def section(self, root: ET.Element, name: str) -> Node:
        if root.tag != f'{{{NS_HS}}}sec':
            raise ValueError(f'{name}: expected hs:sec root')
        node = Node('section', name, root)
        for child in root:
            if child.tag == hp('p'):
                node.children.append(self.paragraph(child, f'{name}/paragraph[{len(node.children)+1}]'))
            else:
                self.excluded(child, name, 'unsupported section child')
        if not node.children:
            raise ValueError(f'{name}: section contains no body paragraphs')
        return node


def read_document(path: Path) -> Document:
    reader = Reader()
    sections, members, residuals, caches = {}, {}, {}, {}
    with ZipFile(path) as z:
        names = z.namelist()
        if len(names) != len(set(names)):
            raise ValueError('duplicate ZIP member names')
        required = {'mimetype', 'Contents/header.xml'}
        if not required.issubset(names):
            raise ValueError('missing required members: ' + ', '.join(sorted(required - set(names))))
        if z.read('mimetype') != b'application/hwp+zip':
            raise ValueError('invalid HWPX mimetype')
        section_names = sorted((n for n in names if SECTION_RE.fullmatch(n)),
                               key=lambda n: int(SECTION_RE.fullmatch(n).group(1)))
        if not section_names:
            raise ValueError('no document sections')
        for name in names:
            if name.endswith('/'):
                continue
            data = z.read(name)
            if name.lower().endswith(('.xml', '.hpf', '.rdf')):
                root = DET.fromstring(data)
                if name in section_names:
                    sections[name] = reader.section(root, name)
                    # Mask only supported text, not text inside excluded objects.
                    clone = DET.fromstring(data)
                    supported = {n.location for n in walk(sections[name]) if n.kind == 'paragraph'}
                    # Enumerate the same hierarchy on the clone to locate modeled paragraphs.
                    cloned_reader = Reader()
                    cloned = cloned_reader.section(clone, name)
                    for p in walk(cloned):
                        if p.kind == 'paragraph' and p.location in supported:
                            for run in p.element.findall(hp('run')):
                                for t in run.findall(hp('t')):
                                    # Unsupported inline children stay in the residual.
                                    t.text = None
                                    for child in list(t):
                                        if child.tag in {hp('tab'), hp('lineBreak')} and not child.attrib:
                                            t.remove(child)
                                        else:
                                            child.tail = None
                    residuals[name] = canonical(clone, skip_cache=True)
                    caches[name] = tuple(canonical(e) for e in root.iter(hp('linesegarray')))
                else:
                    members[name] = canonical(root)
                    reader.exclusions.append({'location': name, 'tag': root.tag,
                                              'reason': 'member XML semantics outside text coverage'})
            else:
                members[name] = data
                if name != 'mimetype':
                    reader.exclusions.append({'location': name, 'tag': 'package-member',
                                              'reason': 'binary/preview member semantics outside text coverage'})
        # Keep numeric section ordering even when archive member order differs.
        sections = {name: sections[name] for name in section_names}
    return Document(sections, members, residuals, caches, reader.exclusions)


def walk(node: Node):
    yield node
    for child in node.children:
        yield from walk(child)


def empty_report() -> dict:
    return {'schema_version': 1, 'status': 'unchanged', 'complete': True,
            'coverage': {'included': ['body paragraphs', 'non-nested table cell text'],
                         'excluded': ['semantic formatting', 'rendering', 'edit intent']},
            'change_count': 0, 'changes': [], 'structural_changes': [],
            'non_content_changes': [], 'exclusions': [], 'incomplete_scopes': [], 'errors': []}


class Comparison:
    def __init__(self, report: dict):
        self.report = report

    def incomplete(self, location: str, reason: str, *, structural=False):
        finding = {'location': location, 'reason': reason}
        self.report['incomplete_scopes'].append(finding)
        if structural:
            self.report['structural_changes'].append(finding)

    def aligned(self, a: Node, b: Node) -> bool:
        aa, bb = a.children, b.children
        if len(aa) != len(bb) or any(x.signature() != y.signature() for x, y in zip(aa, bb)):
            self.incomplete(a.location, 'structure changed; child positions are not aligned', structural=True)
            return False
        if a.kind in {'paragraph', 'table'}:
            # A verified paragraph identifies its table anchors; an unchanged table grid
            # identifies cells by their cellAddr rather than serialized order.
            return True
        if [n.content() for n in aa] == [n.content() for n in bb]:
            return True
        old_contents = [n.content() for n in aa]
        new_contents = [n.content() for n in bb]
        # A value found at a different old position is evidence of movement, even
        # when IDs stayed in position. Never turn it into a list of substitutions.
        if any(x != y and y in old_contents for x, y in zip(old_contents, new_contents)):
            self.incomplete(a.location, 'content moved or correspondence is ambiguous', structural=True)
            return False
        ids_a = [n.element.get('id', '') for n in aa]
        ids_b = [n.element.get('id', '') for n in bb]
        unique_a, unique_b = Counter(ids_a), Counter(ids_b)
        if ids_a != ids_b:
            self.incomplete(a.location, 'paragraph identity/order changed', structural=True)
            return False
        anchors = [i for i, (x, y) in enumerate(zip(aa, bb))
                   if x.content() == y.content() and old_contents.count(x.content()) == 1
                   and new_contents.count(y.content()) == 1]
        for i, (x, y) in enumerate(zip(aa, bb)):
            if x.content() == y.content():
                continue
            identity = ids_a[i]
            if identity and identity not in PLACEHOLDER_IDS and unique_a[identity] == unique_b[identity] == 1:
                continue
            # A cell grid plus a single paragraph gives a stable content container.
            if a.kind == 'cell' and len(aa) == 1:
                continue
            # Bound anonymous edits by unique unchanged anchors. Repeated old text
            # cannot establish a paragraph match, even inside an anchored range.
            if anchors and old_contents.count(x.content()) == new_contents.count(y.content()) == 1:
                continue
            self.incomplete(a.location, 'paragraph correspondence cannot be established')
            return False
        return True

    def compare_node(self, a: Node, b: Node):
        if a.kind == 'unsupported_table':
            if canonical(a.element) != canonical(b.element):
                self.incomplete(a.location, 'nested table changed; comparison unsupported')
            return
        if a.kind == 'paragraph' and a.text != b.text:
            self.report['changes'].append({'kind': 'paragraph', 'original_location': a.location,
                                           'revised_location': b.location, 'before': a.text, 'after': b.text})
        if not self.aligned(a, b):
            return
        if a.kind == 'cell':
            # Aggregate only changes that are unambiguously within this cell.
            start = len(self.report['changes'])
            for x, y in zip(a.children, b.children):
                self.compare_node(x, y)
            details = self.report['changes'][start:]
            if details:
                del self.report['changes'][start:]
                self.report['changes'].append({'kind': 'cell', 'original_location': a.location,
                                               'revised_location': b.location, 'span': a.span,
                                               'before': '\n'.join(n.text for n in a.children),
                                               'after': '\n'.join(n.text for n in b.children),
                                               'paragraphs': details})
            return
        for x, y in zip(a.children, b.children):
            self.compare_node(x, y)


def compare_documents(a: Document, b: Document) -> dict:
    report = empty_report()
    comparison = Comparison(report)
    report['exclusions'] = [{**e, 'input': side} for side, doc in [('original', a), ('revised', b)]
                            for e in doc.exclusions]
    if list(a.sections) != list(b.sections):
        comparison.incomplete('document', 'section list changed', structural=True)
    for name in a.sections:
        if name not in b.sections:
            continue
        comparison.compare_node(a.sections[name], b.sections[name])
        if a.residuals[name] != b.residuals[name]:
            report['non_content_changes'].append({'location': name, 'kind': 'uninterpreted_xml',
                                                  'reason': 'non-text structure, attributes or unsupported objects changed'})
            comparison.incomplete(name, 'changed XML outside supported text comparison')
        if a.caches[name] != b.caches[name]:
            report['non_content_changes'].append({'location': name, 'kind': 'layout_cache',
                                                  'reason': 'line layout cache changed; rendering not verified'})
    for name in sorted(a.members.keys() | b.members.keys()):
        if a.members.get(name) != b.members.get(name):
            report['non_content_changes'].append({'location': name, 'kind': 'package_member',
                                                  'reason': 'member added, removed or changed; semantics not compared'})
            comparison.incomplete(name, 'changed member outside supported content comparison')
    report['change_count'] = len(report['changes'])
    report['complete'] = not report['incomplete_scopes']
    report['status'] = ('incomplete' if not report['complete'] else
                        'changed' if report['changes'] or report['non_content_changes'] else 'unchanged')
    return report


def render_text(report: dict) -> str:
    lines = [f"{report['status']}: {report['change_count']} content location(s) changed",
             'Coverage: body paragraphs and non-nested table cells; formatting/rendering not verified.']
    for change in report['changes']:
        lines.append(f"- {change['original_location']}: {json.dumps(change['before'], ensure_ascii=False)}"
                     f" -> {json.dumps(change['after'], ensure_ascii=False)}")
    for key in ('structural_changes', 'non_content_changes', 'incomplete_scopes', 'exclusions'):
        for finding in report[key]:
            lines.append(f"- {key}: {finding['location']}: {finding['reason']}")
    for error in report['errors']:
        lines.append(f'- error: {error}')
    return '\n'.join(lines)


def main(argv=None) -> int:
    configure_io()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('original', type=Path)
    parser.add_argument('revised', type=Path)
    parser.add_argument('--json', action='store_true', help='emit schema-versioned JSON only')
    args = parser.parse_args(argv)
    try:
        report = compare_documents(read_document(args.original), read_document(args.revised))
    except (OSError, BadZipFile, ET.ParseError, DefusedXmlException, ValueError, KeyError, zlib.error,
            RuntimeError, EOFError, NotImplementedError) as exc:
        report = empty_report()
        report.update(status='error', complete=False, errors=[str(exc)])
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else render_text(report))
    return {'unchanged': 0, 'changed': 1, 'incomplete': 2, 'error': 3}[report['status']]


if __name__ == '__main__':
    sys.exit(main())
