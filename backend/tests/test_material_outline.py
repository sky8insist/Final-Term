from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.deps import get_current_user
from app.main import app
from app.models.material_outline import TopicProposalDecision
from app.models.user import CurrentUser
from app.services import material_outline_service as service


def block(index, kind='paragraph', text=None, metadata=None):
    return {'id': str(uuid4()), 'sequence_index': index, 'block_type': kind,
            'content_text': text or f'Body {index}', 'metadata': metadata or {},
            'structured_data': {}, 'page_number': index + 1}


def test_sections_cover_preamble_nested_headings_and_all_blocks_in_order():
    rows = [block(0), block(1, 'heading', 'Chapter 1', {'headingLevel': 1}), block(2),
            block(3, 'heading', 'Attention', {'style': 'Heading 2'}), block(4),
            block(5, 'heading', 'Chapter 2', {'headingLevel': 1}), block(6)]
    result = service.split_sections(list(reversed(rows)))
    assert len(result) == 4
    assert result[0]['sourceBlockId'] is None
    assert result[2]['headingPath'] == ['Chapter 1', 'Attention']
    assert result[2]['chapterTitle'] == 'Chapter 1'
    assert result[3]['headingPath'] == ['Chapter 2']
    assert [bid for section in result for bid in section['blockIds']] == [row['id'] for row in rows]
    assert result[2]['pageNumber'] == 4


def test_plain_text_does_not_invent_topics():
    sections = service.split_sections([block(0), block(1)])
    assert len(sections) == 1 and sections[0]['sourceBlockId'] is None
    assert service.split_sections([]) == []


@pytest.mark.parametrize('metadata,structured', [
    ({'headingLevel': 2}, {}), ({'style': '标题 2'}, {}),
    ({'text_level': 2}, {}), ({}, {'mineru': {'text_level': 2}}),
])
def test_supported_heading_level_sources(metadata, structured):
    root, child = block(0, 'heading', 'Root'), block(1, 'heading', 'Child', metadata)
    child['structured_data'] = structured
    assert service.split_sections([root, child])[1]['headingPath'] == ['Root', 'Child']


@pytest.mark.parametrize('rows', [
    [block(i) for i in range(2001)],
    [block(i, 'heading') for i in range(61)],
    [block(0, 'heading', 'x' * 301)],
])
def test_explicit_limits_reject_instead_of_silent_truncation(rows):
    with pytest.raises(HTTPException) as caught: service.split_sections(rows)
    assert caught.value.status_code == 422


def test_prepare_paginates_beyond_postgrest_default_and_keeps_scope(monkeypatch):
    rows = [block(i, 'heading' if i == 0 else 'paragraph') for i in range(1201)]
    calls = []
    class Query:
        def __init__(self): self.filters = {}; self.bounds = None
        def select(self, fields): assert fields == service.SNAPSHOT_FIELDS; return self
        def eq(self, key, value): self.filters[key] = value; return self
        def order(self, *_): return self
        def range(self, start, end): self.bounds = (start, end); return self
        def execute(self):
            assert self.filters == {'user_id': 'u', 'subject_id': 's', 'material_id': 'm'}
            calls.append(self.bounds)
            start, end = self.bounds
            return SimpleNamespace(data=rows[start:end + 1])
    monkeypatch.setattr(service, '_owned', lambda **_: {'status': 'ready'})
    monkeypatch.setattr(service, 'get_supabase_client', lambda: SimpleNamespace(table=lambda _: Query()))
    def rpc(name, values):
        assert name == 'prepare_material_outline' and values['p_snapshot'] == rows
        assert len(values['p_sections'][0]['blockIds']) == 1201
        return {'id': 'batch'}
    monkeypatch.setattr(service, 'rpc', rpc)
    assert service.prepare(user_id='u', subject_id='s', material_id='m') == {'id': 'batch'}
    assert calls == [(0, 499), (500, 999), (1000, 1499)]


def test_unready_material_never_reads_blocks(monkeypatch):
    monkeypatch.setattr(service, '_owned', lambda **_: {'status': 'embedding'})
    monkeypatch.setattr(service, 'get_supabase_client', lambda: pytest.fail('must not read blocks'))
    with pytest.raises(HTTPException) as caught: service.prepare(user_id='u', subject_id='s', material_id='m')
    assert caught.value.status_code == 409


def test_oversized_snapshot_is_not_published(monkeypatch):
    monkeypatch.setattr(service, 'MAX_SNAPSHOT_BYTES', 1)
    class Query:
        def select(self, *_): return self
        def eq(self, *_): return self
        def order(self, *_): return self
        def range(self, *_): return self
        def execute(self): return SimpleNamespace(data=[block(0)])
    monkeypatch.setattr(service, '_owned', lambda **_: {'status': 'ready'})
    monkeypatch.setattr(service, 'get_supabase_client', lambda: SimpleNamespace(table=lambda _: Query()))
    monkeypatch.setattr(service, 'rpc', lambda *_: pytest.fail('must not persist oversized snapshots'))
    with pytest.raises(HTTPException) as caught: service.prepare(user_id='u', subject_id='s', material_id='m')
    assert caught.value.status_code == 422


@pytest.mark.parametrize('values', [
    {'action': 'accept', 'version': 0}, {'action': 'delete', 'version': 1},
    {'action': 'accept', 'version': 1, 'title': '   '},
    {'action': 'accept', 'version': 1, 'title': 'x' * 301},
])
def test_decision_validation(values):
    with pytest.raises(ValidationError): TopicProposalDecision(**values)


@pytest.mark.parametrize('code,http', [('42501', 404), ('40001', 409), ('40P01', 409), ('22023', 422), ('23514', 422)])
def test_rpc_errors_hide_database_details(monkeypatch, code, http):
    class Failure(Exception): pass
    error = Failure('private table details'); error.code = code
    def call(*_): raise error
    monkeypatch.setattr(service, 'get_supabase_client', lambda: SimpleNamespace(rpc=call))
    with pytest.raises(HTTPException) as caught: service.rpc('operation', {})
    assert caught.value.status_code == http and 'private table' not in caught.value.detail


def test_outline_api_auth_scope_and_decision_forwarding(monkeypatch):
    owner, subject, material, proposal = [str(uuid4()) for _ in range(4)]
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=owner)
    captured = {}
    monkeypatch.setattr(service, 'get_outline', lambda **kw: captured.update(kw) or None)
    monkeypatch.setattr(service, 'prepare', lambda **kw: captured.update(kw) or {'id': 'batch'})
    monkeypatch.setattr(service, 'decide', lambda **kw: captured.update(kw) or {'status': 'accepted'})
    try:
        with TestClient(app) as client:
            url = f'/api/v1/materials/{material}/outline?subject_id={subject}'
            assert client.get(url).status_code == 200
            assert captured == {'user_id': owner, 'subject_id': subject, 'material_id': material}
            assert client.post(url).status_code == 200
            result = client.post(f'/api/v1/materials/topic-proposals/{proposal}/decision', json={'action': 'accept', 'version': 1, 'title': ' Attention '})
            assert result.status_code == 200
            assert captured['user_id'] == owner and captured['proposal_id'] == proposal and captured['title'] == 'Attention'
    finally: app.dependency_overrides.clear()
    with TestClient(app) as client:
        assert client.get(url).status_code == 401


def test_outline_tables_included_in_privacy_export():
    from app.services.privacy_service import USER_TABLES
    assert {'material_outlines', 'material_topic_proposals'} <= set(USER_TABLES)


@pytest.mark.parametrize('outline_fails', [False, True])
def test_optional_outline_failure_keeps_material_worker_successful(monkeypatch, outline_fails):
    from app.services import material_ingestion_job_service as jobs
    called=[]
    def prepare(**kw):
        called.append(kw)
        if outline_fails: raise RuntimeError('optional database service unavailable')
        return {'id':'outline'}
    monkeypatch.setattr(service,'prepare',prepare)
    warnings=jobs.optional_postprocessing({'user_id':'u','subject_id':'s','material_id':'m'}, {})
    assert called==[{'user_id':'u','subject_id':'s','material_id':'m'}]
    assert ('outlineWarning' in warnings) is outline_fails
