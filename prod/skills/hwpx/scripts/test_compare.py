"""Executable regression fixtures for the read-only HWPX comparison CLI."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import warnings
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

from _common import NS_HP, NS_HS

SCRIPT = Path(__file__).with_name("compare.py")


def paragraph(text="", pid="1000000001"):
    return f'<hp:p id="{pid}"><hp:run><hp:t>{escape(text)}</hp:t></hp:run></hp:p>'


def table(values, *, spans=None):
    rows = []
    for r, row in enumerate(values):
        cells = []
        for c, text in enumerate(row):
            rs, cs = (spans or {}).get((r, c), (1, 1))
            cells.append(
                f'<hp:tc><hp:subList>{paragraph(text, str(1000000100+r*10+c))}</hp:subList>'
                f'<hp:cellAddr rowAddr="{r}" colAddr="{c}"/>'
                f'<hp:cellSpan rowSpan="{rs}" colSpan="{cs}"/></hp:tc>'
            )
        rows.append('<hp:tr>' + ''.join(cells) + '</hp:tr>')
    cols = max(c + (spans or {}).get((r, c), (1, 1))[1]
               for r, row in enumerate(values) for c in range(len(row)))
    return f'<hp:tbl id="42" rowCnt="{len(values)}" colCnt="{cols}">' + ''.join(rows) + '</hp:tbl>'


def document(body):
    return f'<hs:sec xmlns:hs="{NS_HS}" xmlns:hp="{NS_HP}">{body}</hs:sec>'


class CompareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.a = self.root / 'original.hwpx'
        self.b = self.root / 'revised.hwpx'

    def write(self, path, body, extra=None, *, repack=False):
        members = {'mimetype': b'application/hwp+zip',
                   'Contents/header.xml': b'<header/>',
                   'Contents/section0.xml': document(body).encode()}
        members.update(extra or {})
        with ZipFile(path, 'w', compression=ZIP_DEFLATED if repack else ZIP_STORED) as z:
            for name, data in reversed(list(members.items())) if repack else members.items():
                info = ZipInfo(name, (2020, 1, 1, 1, 1, 0) if repack else (2000, 1, 1, 0, 0, 0))
                info.compress_type = ZIP_DEFLATED if repack else ZIP_STORED
                z.writestr(info, data)

    def run_cli(self, expected, *, text=False):
        before = {p: hashlib.sha256(p.read_bytes()).digest() for p in (self.a, self.b) if p.exists()}
        proc = subprocess.run([sys.executable, str(SCRIPT), str(self.a), str(self.b)]
                              + ([] if text else ['--json']), capture_output=True, text=True)
        self.assertEqual(proc.returncode, expected, proc.stdout + proc.stderr)
        for p, digest in before.items():
            self.assertEqual(hashlib.sha256(p.read_bytes()).digest(), digest)
        if text:
            return proc.stdout
        result = json.loads(proc.stdout)
        self.assertEqual(result['schema_version'], 1)
        self.assertEqual(result['change_count'], len(result['changes']))
        return result

    def pair(self, a, b, expected=1):
        self.write(self.a, a)
        self.write(self.b, b)
        return self.run_cli(expected)

    def test_repack_and_xml_serialization(self):
        body = paragraph(' A  B\tC\nD ').replace('<hp:run>', '<hp:run a="1" b="2">')
        self.write(self.a, body)
        revised = document(body).replace('hp:', 'p:').replace('xmlns:hp=', 'xmlns:p=')
        revised = revised.replace('<p:p id="1000000001">', "<p:p id='1000000001'>")
        revised = revised.replace('a="1" b="2"', 'b="2" a="1"')
        self.write(self.b, body, {'Contents/section0.xml': revised.encode()}, repack=True)
        result = self.run_cli(0)
        self.assertTrue(result['complete'])
        self.assertEqual(result['changes'], [])
        self.assertEqual(result['non_content_changes'], [])

    def test_equal_length_body_and_single_cell(self):
        a = paragraph('2026. 10. 15.') + paragraph('', '1000000002')
        b = a.replace('15.', '16.')
        result = self.pair(a, b)
        self.assertEqual(result['changes'][0]['before'], '2026. 10. 15.')
        self.assertIn('paragraph[1]', result['changes'][0]['original_location'])
        a = paragraph().replace('<hp:t></hp:t>', table([['label', '32,000,000원']]))
        result = self.pair(a, a.replace('32,000,000', '35,000,000'))
        self.assertEqual(result['change_count'], 1)
        change = result['changes'][0]
        self.assertEqual(change['kind'], 'cell')
        self.assertIn('row[1]/col[2]', change['original_location'])
        self.assertEqual(change['before'], '32,000,000원')
        self.assertEqual(change['after'], '35,000,000원')
        self.assertEqual(len(change['paragraphs']), 1)

    def test_empty_and_whitespace_controls(self):
        a = paragraph('', '1000000001') + paragraph(' A  B\tC\nD ', '1000000002')
        result = self.pair(a, a.replace(' A  B', ' A B'))
        self.assertIn('paragraph[2]', result['changes'][0]['original_location'])
        self.assertEqual(result['changes'][0]['before'], ' A  B\tC\nD ')
        a = paragraph().replace('<hp:t></hp:t>', '<hp:t>A<hp:tab/>B<hp:lineBreak/>C</hp:t>')
        result = self.pair(a, a.replace('B<', 'BB<'))
        self.assertEqual(result['changes'][0]['before'], 'A\tB\nC')

    def test_insert_delete_reorder_and_ambiguous(self):
        a = paragraph('A') + paragraph('B', '1000000002')
        for b in [paragraph('X', '1000000003') + a,
                  paragraph('A'),
                  paragraph('B', '1000000002') + paragraph('A'),
                  paragraph('B') + paragraph('A', '1000000002')]:
            with self.subTest(b=b):
                result = self.pair(a, b, 2)
                self.assertFalse(result['complete'])
                self.assertEqual(result['changes'], [])
                self.assertTrue(result['structural_changes'])
        a = paragraph('old', '0')
        result = self.pair(a, paragraph('new', '0'), 2)
        self.assertTrue(result['incomplete_scopes'])

    def test_repeated_labels_and_placeholder_ids(self):
        a = paragraph('anchor', '0') + paragraph('label', '0') + paragraph('label', '0')
        result = self.pair(a, a.replace('label', 'edit', 1), 2)
        self.assertEqual(result['changes'], [])
        a = paragraph().replace('<hp:t></hp:t>', table([['label', 'label']]))
        result = self.pair(a, a.replace('label', 'edit', 1))
        self.assertEqual(result['change_count'], 1)
        self.assertIn('col[1]', result['changes'][0]['original_location'])

    def test_row_insert_and_merge_change(self):
        a = paragraph().replace('<hp:t></hp:t>', table([['A'], ['B']]))
        b = paragraph().replace('<hp:t></hp:t>', table([['X'], ['A'], ['B']]))
        result = self.pair(a, b, 2)
        self.assertEqual(result['changes'], [])
        a = paragraph().replace('<hp:t></hp:t>', table([['A']], spans={(0, 0): (1, 2)}))
        result = self.pair(a, a.replace('>A<', '>B<'))
        self.assertEqual(result['changes'][0]['span'], {'rows': 1, 'columns': 2})
        result = self.pair(a, a.replace('colSpan="2"', 'colSpan="1"').replace('colCnt="2"', 'colCnt="1"'), 2)
        self.assertTrue(result['structural_changes'])

    def test_nested_and_unsupported(self):
        nested = table([['A']]).replace('>A<', '><')
        nested = nested.replace('<hp:t></hp:t>', table([['inner']]))
        a = paragraph().replace('<hp:t></hp:t>', nested)
        result = self.pair(a, a.replace('inner', 'other'), 2)
        self.assertTrue(result['exclusions'])
        self.assertEqual(result['changes'], [])
        a = paragraph('date') + paragraph('', '1000000002').replace('<hp:t></hp:t>', '<hp:pic id="4"/>')
        result = self.pair(a, a.replace('id="4"', 'id="5"'), 2)
        self.assertTrue(result['non_content_changes'])
        self.assertTrue(result['exclusions'])
        result = self.pair(a, a, 0)
        self.assertTrue(result['exclusions'])

    def test_assets_and_header(self):
        for name, old, new in [('BinData/image.png', b'a', b'b'),
                               ('Contents/header.xml', b'<header a="1"/>', b'<header a="2"/>')]:
            self.write(self.a, paragraph('text'), {name: old})
            self.write(self.b, paragraph('text'), {name: new})
            result = self.run_cli(2)
            self.assertEqual(result['change_count'], 0)
            self.assertTrue(result['non_content_changes'])

    def test_layout_cache_and_style_attributes(self):
        a = paragraph('text').replace('</hp:p>', '<hp:linesegarray><hp:lineseg textpos="0"/></hp:linesegarray></hp:p>')
        result = self.pair(a, a.replace('textpos="0"', 'textpos="1"'))
        self.assertEqual(result['change_count'], 0)
        self.assertEqual(result['non_content_changes'][0]['kind'], 'layout_cache')
        a = paragraph('text').replace('<hp:run>', '<hp:run charPrIDRef="1">')
        result = self.pair(a, a.replace('charPrIDRef="1"', 'charPrIDRef="2"'), 2)
        self.assertEqual(result['change_count'], 0)

    def test_mixed_changed_and_incomplete_and_text(self):
        a = paragraph('old') + paragraph('', '1000000002').replace('<hp:t></hp:t>', '<hp:pic id="4"/>')
        result = self.pair(a, a.replace('old', 'new').replace('id="4"', 'id="5"'), 2)
        self.assertEqual(result['change_count'], 1)
        self.assertFalse(result['complete'])
        output = self.run_cli(2, text=True)
        self.assertIn('incomplete', output)
        self.assertIn('old', output)
        self.assertIn('new', output)

    def test_errors(self):
        self.write(self.a, paragraph('text'))
        self.run_cli(3)
        self.b.write_bytes(b'broken')
        self.run_cli(3)
        for members in [{'Contents/section0.xml': b'<broken'},
                        {'Contents/header.xml': b'<broken'},
                        {'Contents/section0.xml': b'<wrong/>'},
                        {'Contents/section0.xml': b'<!DOCTYPE a [<!ENTITY x "boom">]><a>&x;</a>'}]:
            self.write(self.b, paragraph('text'), members)
            self.assertTrue(self.run_cli(3)['errors'])
        with ZipFile(self.b, 'w') as z:
            z.writestr('mimetype', 'application/hwp+zip')
        self.run_cli(3)
        self.write(self.b, paragraph('text'))
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with ZipFile(self.b, 'a') as z:
                z.writestr('mimetype', 'application/hwp+zip')
        self.run_cli(3)

    def test_invalid_cell_grid(self):
        a = paragraph().replace('<hp:t></hp:t>', table([['A', 'B']]))
        for b in [a.replace('colAddr="1"', 'colAddr="0"'),
                  a.replace('rowSpan="1"', 'rowSpan="0"'),
                  a.replace('colCnt="2"', 'colCnt="1"')]:
            self.write(self.a, a)
            self.write(self.b, b)
            result = self.run_cli(3)
            self.assertTrue(result['errors'])

    def test_anonymous_anchored_edit(self):
        a = paragraph('anchor', '0') + paragraph('old', '0') + paragraph('tail', '0')
        result = self.pair(a, a.replace('old', 'new'))
        self.assertEqual(result['change_count'], 1)

    def test_unbounded_anonymous_region_is_incomplete(self):
        a = paragraph('anchor', '0') + paragraph('A', '0') + paragraph('B', '0')
        b = paragraph('anchor', '0') + paragraph('B edited', '0') + paragraph('C', '0')
        result = self.pair(a, b, 2)
        self.assertEqual(result['changes'], [])
        a += paragraph('tail', '0')
        b += paragraph('tail', '0')
        self.assertEqual(self.pair(a, b, 2)['changes'], [])

    def test_clear_field_with_blank_spacer(self):
        a = paragraph('name: Kim') + paragraph('', '1000000002')
        result = self.pair(a, a.replace('name: Kim', ''))
        self.assertEqual(result['change_count'], 1)
        self.assertEqual(result['changes'][0]['after'], '')

    def test_text_redistributed_between_runs_or_objects(self):
        a = paragraph().replace('<hp:run><hp:t></hp:t></hp:run>',
            '<hp:run charPrIDRef="1"><hp:t>AB</hp:t></hp:run><hp:run charPrIDRef="2"><hp:t>C</hp:t></hp:run>')
        b = a.replace('>AB<', '>A<').replace('>C<', '>BC<')
        result = self.pair(a, b, 2)
        self.assertEqual(result['changes'], [])
        self.assertEqual(result['non_content_changes'][0]['kind'], 'text_placement')
        a = paragraph().replace('<hp:t></hp:t>', '<hp:t>AB<hp:fwSpace/>C</hp:t>')
        self.assertFalse(self.pair(a, a.replace('>AB<', '>A<').replace('/>C<', '/>BC<'), 2)['complete'])
        a = paragraph().replace('<hp:t></hp:t>', '<hp:t>AB</hp:t>' + table([['cell']]) + '<hp:t>C</hp:t>')
        self.assertFalse(self.pair(a, a.replace('>AB<', '>A<').replace('>C<', '>BC<'), 2)['complete'])

    def test_cell_paragraph_id_rebuilt_by_table_tool(self):
        a = paragraph().replace('<hp:t></hp:t>', table([['32,000,000원']]))
        b = a.replace('32,000,000', '35,000,000').replace('id="1000000100"', 'id="0"')
        result = self.pair(a, b, 2)
        self.assertEqual(result['change_count'], 1)
        self.assertEqual(result['changes'][0]['after'], '35,000,000원')

    def test_anonymous_table_host_with_stable_table_identity(self):
        a = paragraph('', '0').replace('<hp:t></hp:t>', table([['A']]))
        result = self.pair(a, a.replace('>A<', '>B<'))
        self.assertEqual(result['change_count'], 1)
        a += paragraph('', '0').replace('<hp:t></hp:t>', table([['C']]).replace('id="42"', 'id="43"'))
        result = self.pair(a, a.replace('>A<', '>B<').replace('>C<', '>D<'))
        self.assertEqual(result['change_count'], 2)

    def test_new_section_cache_kind(self):
        self.write(self.a, paragraph('A'))
        new = document(paragraph('B').replace('</hp:p>', '<hp:linesegarray/></hp:p>')).encode()
        self.write(self.b, paragraph('A'), {'Contents/section1.xml': new})
        result = self.run_cli(2)
        cache = [x for x in result['non_content_changes'] if x['location']=='Contents/section1.xml']
        self.assertEqual(cache[0]['kind'], 'layout_cache')

    def test_missing_grid_dimensions_and_minutes_template(self):
        a = paragraph().replace('<hp:t></hp:t>', table([['A', 'B']]))
        a = a.replace(' rowCnt="1" colCnt="2"', '')
        result = self.pair(a, a.replace('>B<', '>C<'))
        self.assertEqual(result['change_count'], 1)
        template = SCRIPT.parent.parent / 'templates' / 'minutes' / 'section0.xml'
        self.write(self.a, paragraph(), {'Contents/section0.xml': template.read_bytes()})
        self.write(self.b, paragraph(), {'Contents/section0.xml': template.read_bytes()})
        self.run_cli(0)

    def test_usage_and_missing_dependency_are_error_outcomes(self):
        for args in [[], ['missing.hwpx'], ['--bad-flag']]:
            r = subprocess.run([sys.executable, str(SCRIPT), *args, '--json'], capture_output=True, text=True)
            self.assertEqual(r.returncode, 3)
            self.assertEqual(json.loads(r.stdout)['status'], 'error')
        r = subprocess.run([sys.executable, '-S', str(SCRIPT), str(self.a), str(self.b), '--json'], capture_output=True, text=True)
        self.assertEqual(r.returncode, 3)
        self.assertIn('defusedxml', json.loads(r.stdout)['errors'][0])

    def test_known_editor_and_preview_caches(self):
        original = {
            'Preview/PrvText.txt': b'old text', 'Preview/PrvImage.png': b'old image',
            'settings.xml': b'<ha:HWPApplicationSetting xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app"><ha:CaretPosition pos="1"/></ha:HWPApplicationSetting>',
            'Contents/content.hpf': b'<opf:package xmlns:opf="http://www.idpf.org/2007/opf"><opf:metadata><opf:meta name="ModifiedDate">old</opf:meta><opf:title>title</opf:title></opf:metadata></opf:package>'}
        revised = {k: v.replace(b'old', b'new').replace(b'pos="1"', b'pos="2"') for k, v in original.items()}
        self.write(self.a, paragraph('old'), original)
        self.write(self.b, paragraph('new'), revised)
        result = self.run_cli(1)
        self.assertEqual(result['change_count'], 1)
        self.assertEqual(len(result['non_content_changes']), 4)
        self.assertTrue(all(x['kind']=='derived_cache' for x in result['non_content_changes']))
        revised['Contents/content.hpf'] = revised['Contents/content.hpf'].replace(b'>title<', b'>changed title<')
        self.write(self.b, paragraph('new'), revised)
        self.assertTrue(self.run_cli(2)['incomplete_scopes'])

    def test_independent_cell_and_body_scopes(self):
        a = paragraph('old') + paragraph('', '1000000002').replace('<hp:t></hp:t>', table([['A'], ['B']]))
        b = paragraph('new') + paragraph('', '1000000002').replace('<hp:t></hp:t>', table([['X'], ['A'], ['B']]))
        result = self.pair(a, b, 2)
        self.assertEqual(result['change_count'], 1)
        self.assertEqual(result['changes'][0]['after'], 'new')

    def test_multiple_cell_paragraphs_count_once(self):
        a = paragraph().replace('<hp:t></hp:t>', table([['A']]))
        a = a.replace('</hp:subList>', paragraph('B', '1000000900') + '</hp:subList>')
        result = self.pair(a, a.replace('>A<', '>AA<').replace('>B<', '>BB<'))
        self.assertEqual(result['change_count'], 1)
        self.assertEqual(len(result['changes'][0]['paragraphs']), 2)
        self.assertEqual(result['changes'][0]['before'], 'A\nB')

    def test_same_shape_tables_reordered_with_duplicate_ids(self):
        first, second = table([['A']]), table([['B']])
        a = paragraph().replace('<hp:t></hp:t>', first + second)
        b = paragraph().replace('<hp:t></hp:t>', second + first)
        result = self.pair(a, b, 2)
        self.assertEqual(result['changes'], [])
        self.assertTrue(result['structural_changes'])

    def test_same_grid_row_and_column_reorder(self):
        for values in [[['A'], ['B']], [['A', 'B']]]:
            a = paragraph().replace('<hp:t></hp:t>', table(values))
            b = a.replace('>A<', '>TEMP<').replace('>B<', '>A<').replace('>TEMP<', '>B<')
            result = self.pair(a, b, 2)
            self.assertEqual(result['changes'], [])
            self.assertTrue(result['structural_changes'])

    def test_changed_inline_attribute_is_not_silently_masked(self):
        a = paragraph().replace('<hp:t></hp:t>', '<hp:t>A<hp:tab width="10"/>B</hp:t>')
        result = self.pair(a, a.replace('width="10"', 'width="20"'), 2)
        self.assertEqual(result['changes'], [])
        self.assertTrue(result['non_content_changes'])

    def test_unsupported_leaf_whitespace_is_significant(self):
        a = paragraph('text') + paragraph('', '1000000002').replace(
            '<hp:t></hp:t>', '<hp:equation><hp:script> </hp:script></hp:equation>')
        result = self.pair(a, a.replace('<hp:script> </hp:script>', '<hp:script>  </hp:script>'), 2)
        self.assertTrue(result['non_content_changes'])
        self.assertEqual(result['changes'], [])
        a = a.replace('<hp:script> </hp:script>', '<hp:script> <hp:unknown/> </hp:script>')
        result = self.pair(a, a.replace('<hp:script> ', '<hp:script>  '), 2)
        self.assertTrue(result['non_content_changes'])
        result = self.pair(a, a.replace('<hp:unknown/> ', '<hp:unknown/>  '), 2)
        self.assertTrue(result['non_content_changes'])

    def test_template_roundtrip(self):
        base = SCRIPT.parent.parent / 'templates' / 'base'
        for path, repack in [(self.a, False), (self.b, True)]:
            with ZipFile(path, 'w', compression=ZIP_DEFLATED if repack else ZIP_STORED) as z:
                for member in sorted(base.rglob('*'), reverse=repack):
                    if member.is_file():
                        z.write(member, member.relative_to(base).as_posix())
        self.run_cli(0)


if __name__ == '__main__':
    unittest.main()
