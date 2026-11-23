from copy import deepcopy
from io import BytesIO
import json
from hashlib import sha256
from uuid import uuid4
from zipfile import ZipFile

from docx import Document
import pytest

from app.services.chunk_service import build_structure_chunk_bundle
from app.services.document_structure_service import enrich_document_structure, heading_level, reported_confidence
from app.services.mineru_adapter import read_mineru_bundle
from app.services.parse_service import parse_native_document_blocks, parse_document_blocks


def block(index, kind='paragraph', text='Body', page=1, **extras):
    return {'id': str(uuid4()), 'source_hash': f'hash-{index}', 'sequence_index': index,
            'block_type': kind, 'content_text': text, 'page_number': page,
            'metadata': {}, 'structured_data': {}, **extras}


def bundle(entries):
    stream = BytesIO()
    with ZipFile(stream, 'w') as archive:
        archive.writestr('fixture_content_list.json', json.dumps(entries))
    return stream.getvalue()


@pytest.mark.parametrize('value', [None, True, False, '0.9', -1, 1.1, float('nan'), float('inf'), 10**400])
def test_unreported_or_invalid_confidence_is_unknown(value):
    assert reported_confidence(value) is None


@pytest.mark.parametrize('value', [0, .4, 1])
def test_reported_numeric_confidence_is_preserved(value):
    assert reported_confidence(value) == value


@pytest.mark.parametrize('metadata,text,level,source', [
    ({'style': 'Heading 3'}, 'Title', 3, 'style'),
    ({'style': '标题 2'}, 'Title', 2, 'style'),
    ({}, '1.2.3 Attention', 3, 'numbering_rule'),
    ({}, '第二节 公式', 2, 'numbering_rule'),
    ({'headingLevel': 'bad'}, 'Title', 1, 'default'),
    ({'headingLevel': True}, 'Title', 1, 'default'),
    ({'headingLevel': 2.5}, 'Title', 1, 'default'),
])
def test_heading_levels_are_normalized_without_truncation(metadata, text, level, source):
    assert heading_level(block(0, 'heading', text, metadata=metadata)) == (level, source)


def test_hierarchy_parents_preserve_text_hash_order_and_input():
    rows = [block(0, 'heading', '1 Chapter'), block(1, text='Intro'),
            block(2, 'heading', '1.1 Detail'), block(3, text='Detail body'),
            block(4, 'heading', '2 Next')]
    original = deepcopy(rows)
    enriched, report = enrich_document_structure(list(reversed(rows)))
    annotation = enriched[2]['metadata']['documentStructure']
    assert annotation['headingPath'] == ['1 Chapter', '1.1 Detail']
    assert annotation['parentHeading']['sourceHash'] == 'hash-0'
    assert enriched[3]['metadata']['documentStructure']['headingPath'] == annotation['headingPath']
    assert enriched[4]['metadata']['documentStructure']['parentHeading'] is None
    assert report['headingCount'] == 3 and report['unknownConfidence'] == 5
    assert [(row['content_text'], row['source_hash'], row['sequence_index']) for row in enriched] == [(row['content_text'], row['source_hash'], row['sequence_index']) for row in rows]
    assert rows == original
    repeated, repeated_report = enrich_document_structure(enriched)
    assert repeated == enriched and repeated_report == report


@pytest.mark.parametrize('kind,caption', [('image', 'Figure 1. Architecture'), ('chart', '图 2 结果'), ('table', 'Table 3: Results')])
def test_unique_same_page_caption_is_bidirectionally_traceable(kind, caption):
    rows, summary = enrich_document_structure([block(0, kind), block(1, text=caption)])
    relation = rows[0]['metadata']['documentStructure']['relations'][0]
    assert relation['sourceHash'] == 'hash-1' and relation['kind'] == 'caption'
    assert rows[1]['metadata']['documentStructure']['relations'][0]['kind'] == 'caption_for'
    assert summary['adjacentCaptions'] == 1


def test_ambiguous_and_cross_page_captions_are_not_guessed():
    rows, summary = enrich_document_structure([block(0, 'image'), block(1, text='Fig. 1: Diagram'), block(2, 'chart')])
    assert rows[1]['metadata']['documentStructure']['captionReview'] == 'ambiguous'
    assert summary['ambiguousCaptions'] == 1
    assert not rows[0]['metadata']['documentStructure']['relations']
    rows, summary = enrich_document_structure([block(0, 'table'), block(1, text='Table 1 Results', page=2)])
    assert summary['unmatchedCaptions'] == 1 and summary['adjacentCaptions'] == 0


def test_formula_context_is_candidate_only_and_does_not_cross_heading_or_page():
    rows, summary = enrich_document_structure([block(0, text='Definitions'), block(1, 'formula', 'Ax=b'),
                                             block(2, 'heading', 'New topic'), block(3, 'formula', 'x=1', page=2)])
    relations = rows[1]['metadata']['documentStructure']['relations']
    assert len(relations) == 1 and relations[0]['sourceHash'] == 'hash-0'
    assert relations[0]['method'] == 'adjacent_candidate' and summary['formulaContexts'] == 1
    assert not rows[3]['metadata']['documentStructure']['relations']


def test_caption_labels_are_not_formula_context():
    rows, report = enrich_document_structure([block(0, text='Table 2 Results'), block(1, 'formula', 'x=1')])
    assert report['formulaContexts'] == 0 and not rows[1]['metadata']['documentStructure']['relations']


def test_embedded_provider_caption_is_preserved_without_rewriting_source():
    row = block(0, 'table', '<table>body</table>', structured_data={'mineru': {'table_caption': ['Table 1', 'Results']}})
    rows, report = enrich_document_structure([row])
    assert rows[0]['metadata']['documentStructure']['embeddedCaption']['text'] == 'Table 1\nResults'
    assert report['embeddedCaptions'] == 1 and rows[0]['content_text'] == row['content_text']


def test_caption_neighbour_stays_in_parent_and_child_carries_annotation():
    rows, _ = enrich_document_structure([block(0, 'image', 'x' * 95), block(1, text='Figure 1: Model')])
    chunks = build_structure_chunk_bundle(rows, chunk_size=50, overlap=10, parent_size=100)
    assert len(chunks['parents']) == 1
    assert chunks['parents'][0]['strategy_version'] == 'structure-v2'
    assert chunks['records'][0]['metadata']['documentStructure']['relations'][0]['sourceHash'] == 'hash-1'


def test_formula_neighbour_on_another_page_does_not_override_parent_budget():
    rows, _ = enrich_document_structure([block(0, 'formula', 'x' * 95), block(1, text='y' * 95, page=2)])
    chunks = build_structure_chunk_bundle(rows, chunk_size=50, overlap=10, parent_size=100)
    assert len(chunks['parents']) == 2


@pytest.mark.parametrize('level', ['invalid', True, 1.5, float('inf')])
def test_malformed_mineru_heading_level_does_not_abort_bundle(level):
    parsed = read_mineru_bundle(bundle([{'type': 'text', 'text': 'Body', 'text_level': level, 'page_idx': 0}]))
    assert parsed.blocks[0]['block_type'] == 'paragraph'
    assert parsed.blocks[0]['confidence'] is None
    json.dumps(parsed.blocks, allow_nan=False)


def test_mineru_unknown_and_reported_confidence_telemetry():
    parsed = read_mineru_bundle(bundle([{'type': 'text', 'text': 'Heading', 'text_level': 1},
        {'type': 'image', 'image_caption': ['Figure 1: Model'], 'confidence': .4}]))
    _, report = enrich_document_structure(parsed.blocks)
    assert report['unknownConfidence'] == 1 and report['reportedConfidence'] == 1
    assert report['lowConfidence'] == 1 and report['embeddedCaptions'] == 1


def test_real_docx_native_heading_and_unknown_confidence_without_external_calls():
    document = Document(); document.add_heading('Chapter', level=1); document.add_heading('Detail', level=2); document.add_paragraph('Body')
    stream = BytesIO(); document.save(stream)
    rows = parse_native_document_blocks(stream.getvalue(), filename='lecture.docx')
    enriched, report = enrich_document_structure(rows)
    assert enriched[1]['metadata']['documentStructure']['headingPath'] == ['Chapter', 'Detail']
    assert report['unknownConfidence'] == 3


def test_vision_missing_confidence_is_unknown_not_zero(monkeypatch):
    from app.services import multimodal_service
    monkeypatch.setattr(multimodal_service, 'analyze_image', lambda *_, **kw: {'kind': 'image', 'summary': 'Model diagram'})
    rows = parse_document_blocks(b'fixture', filename='image.png', content_type='image/png')
    assert rows[0]['confidence'] is None


def test_docx_fallback_keeps_table_between_caption_and_following_paragraph():
    document = Document(); document.add_paragraph('Table 1: Scores')
    table = document.add_table(rows=2, cols=1); table.cell(0, 0).text = 'Score'; table.cell(1, 0).text = '10'
    document.add_paragraph('Following explanation')
    stream = BytesIO(); document.save(stream)
    rows = parse_native_document_blocks(stream.getvalue(), filename='lecture.docx')
    assert [row['block_type'] for row in rows] == ['paragraph', 'table', 'paragraph']
    legacy_following = 'python-docx-native-fallback:None:1:paragraph:Following explanation'
    assert rows[2]['source_hash'] == sha256(legacy_following.encode()).hexdigest()
    enriched, report = enrich_document_structure(rows)
    assert report['adjacentCaptions'] == 1
    assert enriched[1]['metadata']['documentStructure']['relations'][0]['sourceHash'] == rows[0]['source_hash']
