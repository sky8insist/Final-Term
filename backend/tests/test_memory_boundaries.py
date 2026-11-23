from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.deps import get_current_user
from app.main import app
from app.models.memory import LearnerProfileUpdate, MemoryWrite
from app.models.user import CurrentUser
from app.services import hermes_memory_service as service, memory_policy_service as policy

OWNER, SUBJECT, SESSION = [str(UUID(int=i)) for i in range(1,4)]


@pytest.mark.parametrize('content,kind', [('偏好简洁的类比讲解','preference'),('I prefer worked examples','preference'),
    ('习惯先阅读再练习','habit'),('I usually study with examples','habit'),('经常在抽象符号理解上有困难','difficulty'),
    ('I often struggle with notation','difficulty'),('长期目标是从事统计研究','long_term_goal'),('My long-term goal is research','long_term_goal')])
def test_stable_memory_categories(content,kind):
    assert policy.admit(content) == kind


@pytest.mark.parametrize('content', ['掌握度 90%','偏好简洁，考试成绩80分','长期目标：正确率90%',
    'I prefer examples; mastery is high','My exam date is 2026-11-01','偏好简洁，下次复习在明天',
    '习惯：自报信心很高','喜欢这次考试的成绩','矩阵是数表','今天喜欢快速讲解','偏好采用2026年10月考试目标',
    'I prefer examples with accuracy 0.9','偏好记录已掌握矩阵','习惯：今天答对题目','I prefer next review tomorrow'])
def test_state_and_unclassified_content_rejected_before_database(monkeypatch,content):
    monkeypatch.setattr(service,'get_profile',lambda **_:{'memoryEnabled':True,'writeApproval':True})
    monkeypatch.setattr(service,'get_supabase_client',lambda:pytest.fail('Invalid memory reached DB'))
    with pytest.raises(HTTPException) as error:
        service.request_write(user_id=OWNER,action='add',target='assistant_memory',subject_id=None,old_text=None,
            content=content,confidence=1,importance=50,reason=None,require_approval=True)
    assert error.value.status_code == 422


def test_automatic_candidate_always_waits_for_confirmation(monkeypatch):
    monkeypatch.setattr(service,'get_profile',lambda **_:{'memoryEnabled':True,'writeApproval':False})
    written = {}
    class Client:
        def table(self,name): assert name=='memory_write_requests'; return self
        def insert(self,payload): written.update(payload); return self
        def select(self,*_): return self
        def execute(self): return SimpleNamespace(data=[{'id':'queued'}])
    monkeypatch.setattr(service,'get_supabase_client',lambda:Client())
    monkeypatch.setattr(service,'_apply_write',lambda **_:pytest.fail('Automatic applied without approval'))
    value=service.request_write(user_id=OWNER,action='add',target='assistant_memory',subject_id=None,old_text=None,
        content='偏好分步骤讲解',confidence=1,importance=50,reason=None,require_approval=False,source_event_id=SESSION)
    assert value['status']=='pending' and written['source_event_id']==SESSION


def test_old_pending_state_is_rechecked_on_approval(monkeypatch):
    item={'action':'add','target':'assistant_memory','content':'偏好：掌握度90%', 'subject_id':None}
    class Client:
        def table(self,*_):return self
        def select(self,*_):return self
        def eq(self,*_):return self
        def limit(self,*_):return self
        def execute(self):return SimpleNamespace(data=[item])
    monkeypatch.setattr(service,'get_supabase_client',lambda:Client())
    monkeypatch.setattr(service,'get_profile',lambda **_:{'memoryEnabled':True})
    monkeypatch.setattr(service,'list_memories',lambda **_:[])
    with pytest.raises(HTTPException) as error: service.resolve_write(user_id=OWNER,request_id=SESSION,approve=True)
    assert error.value.status_code==422


@pytest.mark.parametrize('field,value', [('preferredRole','unknown'),('content','x'*1001),('provenance',{})])
def test_profile_and_memory_reject_untrusted_fields(field,value):
    with pytest.raises(ValidationError):
        if field=='preferredRole': LearnerProfileUpdate.model_validate({field:value})
        else: MemoryWrite.model_validate({'action':'add','target':'assistant_memory',field:value})


def test_profile_exam_date_cannot_reenter_long_term_profile():
    with pytest.raises(HTTPException) as error: service.update_profile(user_id=OWNER,changes={'exam_date':'2026-12-01'})
    assert error.value.status_code==422


def test_snapshot_uses_atomic_scoped_rpc(monkeypatch):
    calls=[]
    monkeypatch.setattr(service,'boundary_rpc',lambda name,values:calls.append((name,values)) or {'manifest':[]})
    assert service.create_snapshot(user_id=OWNER,session_id=SESSION,subject_id=SUBJECT)=={'manifest':[]}
    assert calls==[('freeze_teaching_memory',{'p_user':OWNER,'p_session':SESSION,'p_subject':SUBJECT})]


@pytest.mark.parametrize('code,status',[('42501',404),('40001',409),('22023',422)])
def test_boundary_errors_do_not_expose_internal_details(monkeypatch,code,status):
    class Failure(Exception):pass
    exc=Failure('private');exc.code=code
    def fail(*_):raise exc
    monkeypatch.setattr(service,'get_supabase_client',lambda:SimpleNamespace(rpc=fail))
    with pytest.raises(HTTPException) as error: service.boundary_rpc('read',{})
    assert error.value.status_code==status and 'private' not in error.value.detail


def test_behavior_api_uses_authenticated_owner_and_validates_subject(monkeypatch):
    calls=[]
    monkeypatch.setattr(service,'study_behavior',lambda **values:calls.append(values) or {'sessionCount':0})
    app.dependency_overrides[get_current_user]=lambda:CurrentUser(id=OWNER)
    try:
        with TestClient(app) as client:
            assert client.get('/api/v1/learner-profile/study-behavior',params={'subject_id':SUBJECT}).status_code==200
            assert calls==[{'user_id':OWNER,'subject_id':SUBJECT}]
            assert client.get('/api/v1/learner-profile/study-behavior',params={'subject_id':'invalid'}).status_code==422
            assert client.post('/api/v1/memory-snapshots',json={'sessionId':'invalid'}).status_code==422
            writes=[]
            monkeypatch.setattr(service,'list_memories',lambda **_:[{'id':'memory','subject_id':SUBJECT,'target':'assistant_memory','content':'偏好简洁'}])
            monkeypatch.setattr(service,'request_write',lambda **values:writes.append(values) or {'status':'applied'})
            assert client.patch('/api/v1/memories/memory',json={'action':'replace','target':'assistant_memory','content':'偏好类比'}).status_code==200
            assert writes[0]['subject_id']==SUBJECT and writes[0]['user_id']==OWNER
    finally:app.dependency_overrides.pop(get_current_user,None)
    with TestClient(app) as client:
        assert client.get('/api/v1/learner-profile/study-behavior',params={'subject_id':SUBJECT}).status_code==401


@pytest.mark.parametrize('scope', [None,SUBJECT])
def test_replace_cannot_match_other_subject_memory(monkeypatch,scope):
    monkeypatch.setattr(service,'get_subject',lambda **_:None)
    monkeypatch.setattr(service,'get_supabase_client',lambda:SimpleNamespace())
    monkeypatch.setattr(service,'list_memories',lambda **_:[{'id':'other','subject_id':SESSION,'content':'偏好简洁'}])
    with pytest.raises(HTTPException) as error:
        service._apply_write(user_id=OWNER,action='remove',target='assistant_memory',subject_id=scope,old_text='偏好简洁',content=None,confidence=1)
    assert error.value.status_code==404


def test_legacy_preference_can_be_explicitly_reconfirmed(monkeypatch):
    row={'id':'old','content':'偏好简洁','memory_kind':'legacy','subject_id':None}
    updated=[]
    class Client:
        def table(self,*_):return self
        def update(self,payload):updated.append(payload);return self
        def eq(self,*_):return self
        def select(self,*_):return self
        def execute(self):return SimpleNamespace(data=[{**row,'memory_kind':'preference'}])
    monkeypatch.setattr(service,'get_supabase_client',lambda:Client())
    monkeypatch.setattr(service,'list_memories',lambda **_:[row])
    monkeypatch.setattr(service,'_semantic_candidate',lambda **_:(None,None))
    value=service._apply_write(user_id=OWNER,action='replace',target='assistant_memory',subject_id=None,
        old_text='偏好简洁',content='偏好简洁',confidence=1)
    assert updated and not value['duplicate']


def test_capacity_still_counts_preferences_from_all_scopes(monkeypatch):
    monkeypatch.setattr(service,'get_supabase_client',lambda:SimpleNamespace())
    monkeypatch.setattr(service,'get_subject',lambda **_:None)
    monkeypatch.setattr(service,'list_memories',lambda **_:[{'id':'global','subject_id':None,'content':'I prefer very detailed examples'}])
    monkeypatch.setattr(service,'_semantic_candidate',lambda **_:(None,None))
    monkeypatch.setattr(service,'_capacity',lambda _:10)
    with pytest.raises(HTTPException) as error:
        service._apply_write(user_id=OWNER,action='add',target='assistant_memory',subject_id=SUBJECT,
            old_text=None,content='偏好短句',confidence=1)
    assert error.value.status_code==409
