import asyncio
from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.deps import get_current_user
from app.main import app
from app.models.assistant import AssistantMessageRequest
from app.models.conversion import CAPABILITIES, ConversionRequest, ConversionSource
from app.models.user import CurrentUser
from app.services import assistant_service, conversion_service as service, task_service
from app.services import artifact_service, exam_service, notes_service

OWNER, SUBJECT, SOURCE, BLOCK, REQUEST, JOB, TOKEN = [str(UUID(int=i)) for i in range(1,8)]
CITATIONS = [{'id':BLOCK,'filename':'source.pdf','chunkText':'Canonical course definition','pageNumber':7}]
CONTENT = {'sections':[{'id':'s1','title':'Definition','body':'Saved focus','citationIds':[BLOCK]}]}


def request(**patch):
    return ConversionRequest.model_validate({'requestId':REQUEST,'subjectId':SUBJECT,
        'source':{'kind':'notes','id':SOURCE,'version':1},'target':'flashcards',**patch})


def snapshot():
    return {'source':{'kind':'notes','id':SOURCE,'version':1},'title':'Saved focus','content':deepcopy(CONTENT),
        'citations':deepcopy(CITATIONS),'topicIds':[],'warnings':[]}


def job():
    return {'id':JOB,'user_id':OWNER,'subject_id':SUBJECT,'request_id':REQUEST,'claim_token':TOKEN,
        'fingerprint':service.fingerprint(request()),'source_artifact_id':SOURCE,'source_version':1,
        'source_kind':'notes','target':'flashcards','options':{'count':2,'mode':'standard'},'snapshot':snapshot()}


class Client:
    def __init__(self, tables):
        self.tables, self.calls = tables, []
    def table(self, name):
        self.calls.append(('table',name))
        return Query(self,name)


class Query:
    def __init__(self, client, table): self.client,self.name,self.filters,self.columns=client,table,[],None
    def select(self, columns): self.columns=columns; return self
    def eq(self,key,value): self.filters.append((key,value)); return self
    def in_(self,key,value): return self
    def order(self,*args,**kwargs): return self
    def limit(self,*args): return self
    def or_(self,*args): return self
    def execute(self):
        self.client.calls.append((self.name,self.columns,self.filters))
        return SimpleNamespace(data=deepcopy(self.client.tables.get(self.name,[])))


@pytest.mark.parametrize('kind,version,node', [('material',1,None),('notes',None,None),('notes',1,'node'),('mind_map_node',1,None),('wrong_answer',None,'node')])
def test_source_shape_rejects_ambiguous_fields(kind,version,node):
    with pytest.raises(ValidationError): ConversionSource(kind=kind,id=SOURCE,version=version,nodeId=node)


@pytest.mark.parametrize('kind,target',[(kind,target) for kind,targets in CAPABILITIES.items() for target in targets])
def test_capability_matrix_accepts_supported_pairs(kind,target):
    source={'kind':kind,'id':SOURCE}
    if kind in {'notes','mind_map_node'}: source['version']=1
    if kind=='mind_map_node': source['nodeId']='n1'
    assert request(source=source,target=target).target == target


@pytest.mark.parametrize('patch',[{'target':'notes'},{'count':0},{'count':21},{'claim_token':TOKEN},{'source':{'kind':'notes','id':SOURCE,'version':1,'content':'forged'}}])
def test_request_rejects_invalid_pair_limits_and_client_context(patch):
    with pytest.raises(ValidationError): request(**patch)


def test_fingerprint_ignores_request_id_but_binds_versions_options():
    first=request()
    assert service.fingerprint(first)==service.fingerprint(first.model_copy(update={'request_id':UUID(int=99)}))
    assert service.fingerprint(first)!=service.fingerprint(request(count=2))
    assert service.fingerprint(first)!=service.fingerprint(request(source={'kind':'notes','id':SOURCE,'version':2}))


def test_replay_returns_existing_before_reloading_edited_source(monkeypatch):
    client=Client({'learning_conversions':[job()]})
    monkeypatch.setattr(service,'get_supabase_client',lambda:client)
    monkeypatch.setattr(service,'get_subject',lambda **_:None)
    monkeypatch.setattr(service.task_service,'get_task',lambda **_:{'status':'queued'})
    monkeypatch.setattr(service,'snapshot_source',lambda **_:pytest.fail('Replay reloaded source'))
    result=service.enqueue(user_id=OWNER,payload=request())
    assert result['id']==JOB and result['source_title']=='Saved focus'
    assert not {'snapshot','claim_token','fingerprint','user_id'} & result.keys()
    with pytest.raises(HTTPException) as error: service.enqueue(user_id=OWNER,payload=request(count=2))
    assert error.value.status_code==409


def test_notes_snapshot_uses_section_citations_and_saved_version(monkeypatch):
    monkeypatch.setattr(service,'_owned',lambda **_: {'artifact_type':'notes','version':1,'content':CONTENT,'title':'Saved'})
    monkeypatch.setattr(service,'get_supabase_client',lambda:Client({'artifact_topics':[]}))
    scopes=[]
    def canonical(**values): scopes.append(values); return CITATIONS
    monkeypatch.setattr(service.notes_service,'canonical_sources',canonical)
    result=service.snapshot_source(user_id=OWNER,subject_id=SUBJECT,source=request().source)
    assert result['content']==CONTENT and scopes==[{'user_id':OWNER,'subject_id':SUBJECT,'block_ids':[BLOCK]}]
    result['content']['sections'][0]['body']='Changed'
    assert CONTENT['sections'][0]['body']=='Saved focus'
    with pytest.raises(HTTPException) as error: service.snapshot_source(user_id=OWNER,subject_id=SUBJECT,source=request().source.model_copy(update={'version':2}))
    assert error.value.status_code==409


def test_material_snapshot_limits_and_labels_partial_coverage(monkeypatch):
    monkeypatch.setattr(service,'_owned',lambda **_:{'status':'ready','filename':'Course'})
    ids=[str(UUID(int=i+100)) for i in range(31)]
    client=Client({'content_blocks':[{'id':value} for value in ids]})
    monkeypatch.setattr(service,'get_supabase_client',lambda:client)
    canonical=[]
    monkeypatch.setattr(service.notes_service,'canonical_sources',lambda **values:canonical.append(values) or [{'id':value} for value in values['block_ids']])
    result=service.snapshot_source(user_id=OWNER,subject_id=SUBJECT,source=ConversionSource(kind='material',id=SOURCE))
    assert result['warnings']==['material_first_30_blocks'] and len(canonical[0]['block_ids'])==30
    assert ('user_id',OWNER) in client.calls[-1][2] and ('subject_id',SUBJECT) in client.calls[-1][2]


def test_node_snapshot_is_selected_node_not_whole_map(monkeypatch):
    from app.services import mind_map_topic_service
    monkeypatch.setattr(mind_map_topic_service, 'learning', lambda **_: {'artifactVersion': 1, 'nodes': {'n1': {'knowledgePointId': None}}})
    nodes=[{'id':'n1','title':'Focus','citationIds':[BLOCK]},{'id':'n2','title':'Other','citationIds':[SOURCE]}]
    monkeypatch.setattr(service,'_owned',lambda **_:{'artifact_type':'mind_map','version':1,'title':'Map','content':{'nodes':nodes}})
    monkeypatch.setattr(service,'get_supabase_client',lambda:Client({'artifact_topics':[]}))
    monkeypatch.setattr(service.notes_service,'canonical_sources',lambda **values:CITATIONS if values['block_ids']==[BLOCK] else pytest.fail('Wrong node evidence'))
    source=ConversionSource(kind='mind_map_node',id=SOURCE,version=1,nodeId='n1')
    assert service.snapshot_source(user_id=OWNER,subject_id=SUBJECT,source=source)['content']==nodes[0]
    with pytest.raises(HTTPException) as error:service.snapshot_source(user_id=OWNER,subject_id=SUBJECT,source=source.model_copy(update={'node_id':'missing'}))
    assert error.value.status_code==404


@pytest.mark.parametrize('formal,status,is_correct,expected',[(True,'in_progress',False,409),(True,'graded',False,None),(False,'in_progress',False,None),(False,'graded',True,409)])
def test_wrong_answer_guard_and_frozen_question_version(monkeypatch,formal,status,is_correct,expected):
    roots={'wrong_answers':{'attempt_id':JOB,'question_id':SOURCE},'exam_attempts':{'id':JOB,'exam_id':REQUEST,'status':status},
        'exams':{'id':REQUEST,'assessment_mode':'formal' if formal else 'adaptive'},'questions':{'id':SOURCE,'knowledge_key':'Definition','knowledge_point_id':None}}
    monkeypatch.setattr(service,'_owned',lambda **values:roots[values['table']])
    client=Client({'exam_questions':[{'question_version':3}],
        'question_versions':[{'stem':'Original question','options':['A','B'],'correct_answer':['A'],'explanation':'Explain','citations':[BLOCK]}],
        'exam_responses':[{'response':'B'}], 'grading_results':[{'is_correct':is_correct,'error_type':'concept','feedback':'Review definition'}]})
    monkeypatch.setattr(service,'get_supabase_client',lambda:client)
    if expected:
        with pytest.raises(HTTPException) as error:service._question_source(user_id=OWNER,subject_id=SUBJECT,wrong_id=TOKEN)
        assert error.value.status_code==expected
    else:
        result=service._question_source(user_id=OWNER,subject_id=SUBJECT,wrong_id=TOKEN)
        assert result['content']['userAnswer']=='B' and result['content']['correctAnswer']==['A'] and result['content']['errorType']=='concept'
        assert ('version',3) in next(call[2] for call in client.calls if call[0]=='question_versions')


def test_worker_duplicate_delivery_never_generates(monkeypatch):
    monkeypatch.setattr(service,'rpc',lambda *_:None)
    monkeypatch.setattr(service,'generate_draft',lambda *_:pytest.fail('Duplicate generated'))
    assert service.run_conversion(JOB) is None


@pytest.mark.parametrize('target',['notes','flashcards','mind_map','quiz','tutor'])
def test_generation_drafts_never_write_outputs_or_expand_source_scope(monkeypatch,target):
    value={**job(),'target':target}
    client=Client({'questions':[]})
    monkeypatch.setattr(notes_service,'get_subject',lambda **_:None)
    monkeypatch.setattr(notes_service,'canonical_sources',lambda **_:CITATIONS)
    for module in [notes_service,artifact_service,exam_service]:
        monkeypatch.setattr(module,'get_supabase_client',lambda:client)
    prompts=[]
    async def model(prompt,**kwargs):
        prompts.append(prompt)
        if target=='notes':return {'title':'Draft note',**CONTENT}
        if target=='flashcards':return {'title':'Cards','cards':[{'front':'Definition?','back':'Canonical definition','knowledgeKey':'Definition','citationIds':[BLOCK]}]}
        if target=='mind_map':return {'title':'Map','nodes':[{'id':'root','parentId':None,'title':'Definition','citationIds':[BLOCK]}]}
        return {'questions':[{'questionType':'single_choice','stem':'Eigenvalues definition?','options':['A','B'],'correctAnswer':['A'],'explanation':'Definition','knowledgeKey':'Definition','citationIds':[BLOCK]},
            {'questionType':'single_choice','stem':'Which condition ensures this calculation holds?','options':['C','D'],'correctAnswer':['C'],'explanation':'Condition','knowledgeKey':'Definition','citationIds':[BLOCK]}]}
    for module in [notes_service,artifact_service,exam_service]:monkeypatch.setattr(module,'generate_json_async',model)
    result=asyncio.run(service.generate_draft(value))
    if target=='tutor':assert result=={} and not prompts
    else:
        assert result['title'] and prompts and 'Saved focus' in prompts[0] and 'Canonical course definition' in prompts[0]
    assert all(call[1]=='questions' if call[0]=='table' else call[0]=='questions' for call in client.calls)


@pytest.mark.parametrize('fails',[False,True])
def test_worker_only_publishes_validated_draft_with_claim_token(monkeypatch,fails):
    calls=[]
    def rpc(name,params):
        calls.append((name,params))
        if name=='claim_conversion':return job()
        if name=='finish_conversion' and fails:raise HTTPException(409,'Cancelled')
        return {'id':JOB}
    async def draft(value):return {'title':'Draft'}
    monkeypatch.setattr(service,'rpc',rpc);monkeypatch.setattr(service,'generate_draft',draft)
    service.run_conversion(JOB)
    assert calls[1][1]=={'p_id':JOB,'p_token':TOKEN,'p_draft':{'title':'Draft'}}
    if fails:assert calls[2][0]=='transition_conversion' and calls[2][1]['p_token']==TOKEN


@pytest.mark.parametrize('action',['cancel','retry'])
def test_task_transitions_delegate_to_atomic_conversion_rpc(monkeypatch,action):
    monkeypatch.setattr(task_service,'get_task',lambda **_:{'taskType':'learning_conversion'})
    calls=[]
    monkeypatch.setattr(service,'transition',lambda **values:calls.append(values) or {'status':'queued'})
    (task_service.cancel_task if action=='cancel' else task_service.retry_task)(user_id=OWNER,task_id=JOB)
    assert calls==[{'user_id':OWNER,'conversion_id':JOB,'action':action}]


def test_tutor_owner_subject_completed_and_current_evidence_guards(monkeypatch):
    scopes=[]
    monkeypatch.setattr(service,'get_conversion',lambda **values:scopes.append(values) or {**job(),'target':'tutor'})
    monkeypatch.setattr(service.task_service,'get_task',lambda **_:{'status':'succeeded'})
    monkeypatch.setattr(service.notes_service,'canonical_sources',lambda **_:CITATIONS)
    assert service.tutor_context(user_id=OWNER,subject_id=SUBJECT,conversion_id=JOB)==snapshot()
    assert scopes[0]=={'user_id':OWNER,'conversion_id':JOB,'subject_id':SUBJECT,'include_snapshot':True}
    monkeypatch.setattr(service.notes_service,'canonical_sources',lambda **_:[{**CITATIONS[0],'chunkText':'Changed'}])
    with pytest.raises(HTTPException) as error:service.tutor_context(user_id=OWNER,subject_id=SUBJECT,conversion_id=JOB)
    assert error.value.status_code==409


def test_tutor_inherits_frozen_context_without_client_answer_or_new_retrieval(monkeypatch):
    monkeypatch.setattr(assistant_service,'get_subject',lambda **_:None)
    source={**snapshot(),'content':{'question':'Definition?','userAnswer':'B','correctAnswer':'A','errorType':'concept','knowledgeKey':'Definition'}}
    monkeypatch.setattr(service,'tutor_context',lambda **_:source)
    calls=[]
    async def answer(**values):calls.append(values);return {'answer':'Tutor explanation','messageId':TOKEN}
    monkeypatch.setattr(assistant_service.rag_service,'answer_with_rag',answer)
    payload=AssistantMessageRequest(subjectId=SUBJECT,message='Explain my mistake',sessionId=REQUEST,conversionId=JOB)
    result=asyncio.run(assistant_service.handle_message(user_id=OWNER,payload=payload))
    context=calls[0]['context_override']
    assert '"userAnswer": "B"' in context['rawContext'] and '"correctAnswer": "A"' in context['rawContext']
    assert context['citations']==CITATIONS and calls[0]['allow_external_knowledge'] is False and result['messageId']==TOKEN
    with pytest.raises(HTTPException):asyncio.run(assistant_service.handle_message(user_id=OWNER,payload=payload.model_copy(update={'guided_session_id':REQUEST})))


def test_api_authenticated_enqueue202_history_and_uuid_validation(monkeypatch):
    calls=[]
    monkeypatch.setattr(service,'enqueue',lambda **values:calls.append(values) or {'id':JOB})
    monkeypatch.setattr(service,'dispatch',lambda value:calls.append(value))
    monkeypatch.setattr(service,'list_conversions',lambda **values:calls.append(values) or [])
    app.dependency_overrides[get_current_user]=lambda:CurrentUser(id=OWNER,email='test@example.com')
    try:
        with TestClient(app) as client:
            response=client.post('/api/v1/conversions',json=request().model_dump(mode='json',by_alias=True))
            assert response.status_code==202 and calls[0]['user_id']==OWNER and calls[1]==JOB
            assert client.get('/api/v1/conversions',params={'subject_id':SUBJECT,'object_id':SOURCE}).status_code==200
            assert calls[-1]=={'user_id':OWNER,'subject_id':SUBJECT,'object_id':SOURCE}
            assert client.get('/api/v1/conversions',params={'subject_id':SUBJECT,'object_id':'invalid'}).status_code==422
    finally:app.dependency_overrides.pop(get_current_user,None)
    with TestClient(app) as client:assert client.get('/api/v1/conversions/capabilities').status_code==401
