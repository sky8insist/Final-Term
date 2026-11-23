"""Deterministic citation/claim checks. Lexical support is not semantic entailment."""
import re

from app.services.evidence_assessment_service import _tokens


def _number(value):
    return int(value) if len(value) <= 6 else -1


def verify_answer(*, answer: str, citations: list[dict]) -> dict:
    markers = [_number(value) for value in re.findall(r'\[(\d+)\]', answer)]
    invalid = sorted({number for number in markers if not 1 <= number <= len(citations)})
    invalid_format = bool(re.search(r'\[(?:(?:citation|source|ref|引用|来源)\s*[:：][^\]]+|c\d+|[a-f0-9]{8}-[a-f0-9-]{27,})\]', answer, re.I))
    allowed_urls = {row.get('url', '').rstrip('/') for row in citations if row.get('url')}
    new_urls = [url for url in re.findall(r'https?://[^\s)\]>]+', answer) if url.rstrip('/') not in allowed_urls]
    claims = []
    questions = 0
    # Treat each sentence/list line separately; [n] immediately after a period
    # belongs to that sentence rather than the next one.
    normalized = re.sub(r'([.!?。！？])\s*((?:\[\d+\])+)', r'\2\1', answer)
    units = re.split(r'(?<=[。！？!?])\s*|(?<=\.)\s+|\n+', normalized)
    for unit in units:
        text = unit.strip()
        if not text or text.strip('# *').rstrip(':：') in {'课程资料依据', '外部补充知识'}:
            continue
        clean = re.sub(r'\[\d+\]', '', text).strip(' -#*\t')
        if not clean or clean.endswith(('?', '？')):
            questions += bool(clean)
            continue
        indices = {_number(value) for value in re.findall(r'\[(\d+)\]', text)}
        sources = [citations[index - 1] for index in indices if 1 <= index <= len(citations)]
        evidence = '\n'.join(str(row.get('text') or row.get('chunkText') or '') for row in sources)
        tokens = _tokens(clean)
        support = len(tokens & _tokens(evidence)) / max(len(tokens), 1)
        numbers = set(re.findall(r'(?<!\w)-?\d+(?:\.\d+)?', clean))
        evidence_numbers = set(re.findall(r'(?<!\w)-?\d+(?:\.\d+)?', evidence))
        negation = lambda value: bool(re.search(r'\b(?:not|never|cannot)\b|不是|不能|不等于|不存在|无法', value, re.I))
        contradiction = bool(sources) and negation(clean) != negation(evidence)
        all_citations_relevant = all(bool(tokens & _tokens(str(row.get('text') or row.get('chunkText') or ''))) for row in sources)
        supported = bool(sources) and bool(tokens) and support >= .2 and all_citations_relevant and numbers <= evidence_numbers and not contradiction
        claims.append({'cited': bool(sources), 'supported': supported, 'lexicalSupport': round(support, 4),
                       'numericMismatch': not numbers <= evidence_numbers, 'negationMismatch': contradiction})
    cited = sum(row['cited'] for row in claims)
    supported = sum(row['supported'] for row in claims)
    passed = not invalid and not invalid_format and not new_urls and bool(claims or questions) and supported == len(claims)
    return {'version': 'claim-citation-v1', 'passed': passed, 'claimCount': len(claims),
            'citationCoverage': cited / max(len(claims), 1), 'groundingScore': supported / max(len(claims), 1),
            'invalidCitationNumbers': invalid, 'invalidCitationFormat': invalid_format, 'unapprovedUrlCount': len(new_urls),
            'usedCitationIds': [row['id'] for index, row in enumerate(citations, 1) if index in markers],
            'reason': 'fabricated_citation' if invalid or invalid_format or new_urls else 'nonassertive_response' if passed and not claims else 'supported_lexically' if passed else 'unsupported_claim',
            'claims': claims}
