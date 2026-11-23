"""Conservative structural annotations; preserve source text, order and hashes."""
from copy import deepcopy
import math
import re

VERSION = 'document-structure-v1'


def reported_confidence(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            number = float(value)
            if math.isfinite(number) and 0 <= number <= 1:
                return number
        except (OverflowError, ValueError):
            pass
    return None


def heading_level(block):
    metadata = block.get('metadata') or {}
    candidates = [('headingLevel', metadata.get('headingLevel')), ('text_level', metadata.get('text_level')),
                  ('mineru', ((block.get('structured_data') or {}).get('mineru') or {}).get('text_level'))]
    for source, value in candidates:
        if isinstance(value, bool): continue
        try:
            number = float(value)
            if math.isfinite(number) and number.is_integer() and 1 <= number <= 6:
                return int(number), source
        except (ValueError, TypeError):
            pass
    style = re.search(r'(?:heading|标题)\s*([1-6])\b', str(metadata.get('style') or ''), re.I)
    if style: return int(style[1]), 'style'
    text = str(block.get('content_text') or '').strip()
    numbering = re.match(r'^(\d+(?:\.\d+){0,5})[.、]?\s+\S', text)
    if numbering: return numbering[1].count('.') + 1, 'numbering_rule'
    if re.match(r'^第[一二三四五六七八九十百\d]+节', text): return 2, 'numbering_rule'
    return 1, 'default'


def _reference(block):
    return {'sourceHash': block.get('source_hash'), 'sequenceIndex': block['sequence_index'],
            'blockType': block['block_type'], 'pageNumber': block.get('page_number')}


def _caption_kind(text):
    if re.match(r'^(?:table|表)\s*[\d一二三四五六七八九十]', text.strip(), re.I): return 'table'
    if re.match(r'^(?:figure|fig\.?|图)\s*[\d一二三四五六七八九十]', text.strip(), re.I): return 'figure'
    return None


def _same_page(left, right):
    # Both unknown is useful for DOCX, but never guess across a known page boundary.
    return left.get('page_number') == right.get('page_number')


def enrich_document_structure(blocks: list[dict]) -> tuple[list[dict], dict]:
    ordered = sorted(deepcopy(blocks), key=lambda row: (row['sequence_index'], str(row.get('source_hash') or '')))
    path = []
    summary = {'version': VERSION, 'blockCount': len(ordered), 'headingCount': 0,
               'defaultHeadingLevels': 0, 'embeddedCaptions': 0, 'adjacentCaptions': 0,
               'ambiguousCaptions': 0, 'unmatchedCaptions': 0, 'formulaContexts': 0,
               'unknownConfidence': 0, 'reportedConfidence': 0, 'lowConfidence': 0}
    for block in ordered:
        metadata = block.setdefault('metadata', {})
        confidence = reported_confidence(block.get('confidence'))
        block['confidence'] = confidence
        summary['unknownConfidence' if confidence is None else 'reportedConfidence'] += 1
        if confidence is not None and confidence < .6:
            summary['lowConfidence'] += 1
            metadata['needsReview'] = True
        annotation = {'version': VERSION, 'relations': [], 'headingPath': []}
        metadata['documentStructure'] = annotation
        if block['block_type'] == 'heading':
            level, source = heading_level(block)
            annotation.update(headingLevel=level, headingLevelSource=source)
            path = [(depth, ancestor) for depth, ancestor in path if depth < level]
            annotation['parentHeading'] = _reference(path[-1][1]) if path else None
            path.append((level, block))
            summary['headingCount'] += 1
            summary['defaultHeadingLevels'] += source == 'default'
        annotation['headingPath'] = [str(ancestor['content_text']) for _, ancestor in path]
        kind = block['block_type']
        field = {'image': 'image_caption', 'chart': 'chart_caption', 'table': 'table_caption'}.get(kind)
        raw = ((block.get('structured_data') or {}).get('mineru') or {}).get(field) if field else None
        caption = raw if isinstance(raw, str) else '\n'.join(value for value in raw if isinstance(value, str)) if isinstance(raw, list) else ''
        if caption.strip():
            annotation['embeddedCaption'] = {'text': caption.strip()[:2000], 'truncated': len(caption.strip()) > 2000,
                                              'method': 'provider_field', 'field': field}
            summary['embeddedCaptions'] += 1

    def link(left, right, kind, method):
        left['metadata']['documentStructure']['relations'].append({'kind': kind, 'method': method, **_reference(right)})

    for index, block in enumerate(ordered):
        kind = _caption_kind(block['content_text']) if block['block_type'] == 'paragraph' else None
        neighbours = ordered[max(0, index - 1):index] + ordered[index + 1:index + 2]
        if kind:
            matches = [other for other in neighbours if _same_page(block, other) and
                       other['block_type'] in ({'table'} if kind == 'table' else {'image', 'chart'})]
            if len(matches) == 1:
                link(matches[0], block, 'caption', 'unique_adjacent_label')
                link(block, matches[0], 'caption_for', 'unique_adjacent_label')
                summary['adjacentCaptions'] += 1
            else:
                reason = 'ambiguous' if len(matches) > 1 else 'unmatched'
                block['metadata']['documentStructure']['captionReview'] = reason
                summary['ambiguousCaptions' if matches else 'unmatchedCaptions'] += 1
        if block['block_type'] == 'formula':
            for other in neighbours:
                if other['block_type'] == 'paragraph' and _same_page(block, other) and not _caption_kind(other['content_text']):
                    link(block, other, 'context', 'adjacent_candidate')
                    link(other, block, 'context_for', 'adjacent_candidate')
                    summary['formulaContexts'] += 1
    return ordered, summary
