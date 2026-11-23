import hashlib
import io
import json
from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException,UploadFile
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.datastructures import Headers

from app.api.deps import get_current_user
from app.main import app
from app.models.conversion import ConversionSource
from app.models.user import CurrentUser
from app.services import audio_service,conversion_service,lecture_service as service
from app.services.file_service import normalized_upload_content_type,validate_upload_file
from app.services.parse_service import DocumentParseError,build_audio_blocks

OWNER,SUBJECT,MATERIAL,BLOCK,LECTURE,TOPIC=[str(UUID(int=index)) for index in range(1,7)]


@pytest.mark.parametrize('mime',['audio/webm','audio/webm;codecs=opus','application/octet-stream'])
def test_browser_webm_normalizes_mime_and_validates_container(mime):
    file=UploadFile(filename='lecture.webm',file=io.BytesIO(b'\x1a\x45\xdf\xa3payload'),headers=Headers({'content-type':mime}))
    assert normalized_upload_content_type(file)=='audio/webm' and validate_upload_file(file)>0
    fake=UploadFile(filename='fake.webm',file=io.BytesIO(b'not webm'),headers=Headers({'content-type':mime}))
    with pytest.raises(HTTPException) as error:validate_upload_file(fake)
    assert error.value.status_code==400


def test_webm_missing_duration_probes_audio_packet_times(monkeypatch):
    calls=[]
    def run(command):
        calls.append(command)
        return SimpleNamespace(stdout=b'{"format":{}}' if len(calls)==1 else b'-0.01,0.02\n0.01,0.02\n1.00,0.02\nN/A,N/A\n')
    monkeypatch.setattr(audio_service,'_run',run)
    monkeypatch.setattr(audio_service,'_require_binary',lambda name:name)
    assert audio_service._probe_duration('lecture.webm')==1.02 and len(calls)==2


@pytest.mark.parametrize('value',['nan','inf','0','-1'])
def test_invalid_audio_duration_cannot_bypass_limits(monkeypatch,value):
    monkeypatch.setattr(audio_service,'_require_binary',lambda name:name)
    monkeypatch.setattr(audio_service,'_run',lambda *_:SimpleNamespace(stdout=json.dumps({'format':{'duration':value}}).encode()))
    with pytest.raises(audio_service.AudioProcessingError):audio_service._probe_duration('audio')


def test_short_browser_recording_transcodes_to_provider_wav(monkeypatch):
    monkeypatch.setattr(audio_service,'_probe_duration',lambda *_:2)
    monkeypatch.setattr(audio_service,'_extract_wav_segment',lambda *args:b'WAV')
    rows,_=audio_service.split_audio_bytes(b'webm',filename='recording.webm',content_type='audio/webm')
    assert len(rows)==1 and rows[0].derived and rows[0].content_type=='audio/wav' and rows[0].data==b'WAV'


def test_repeated_sentence_in_different_segments_has_distinct_stable_identity():
    result={'segments':[{'start':0,'end':3,'text':'Repeated definition'}]}
    first=build_audio_blocks(result,analyze_audio_transcript=False,audio_segment_index=0,audio_segment_duration=10)
    second=build_audio_blocks(result,analyze_audio_transcript=False,audio_segment_index=1,audio_time_offset=600,audio_segment_duration=10)
    assert first[0]['source_hash']!=second[0]['source_hash'] and second[0]['start_time']==600
    assert second==build_audio_blocks(result,analyze_audio_transcript=False,audio_segment_index=1,audio_time_offset=600,audio_segment_duration=10)


@pytest.mark.parametrize('start,end',[(-1,2),(4,3),(0,11),(10.1,10.2),(float('nan'),2),(0,float('inf'))])
def test_asr_timestamps_must_be_finite_ordered_and_inside_audio(start,end):
    with pytest.raises(DocumentParseError):build_audio_blocks({'segments':[{'start':start,'end':end,'text':'Text'}]},analyze_audio_transcript=False,audio_segment_duration=10)


def test_missing_asr_times_use_segment_window_and_unknown_confidence():
    rows=build_audio_blocks({'segments':[{'text':'Definition'}]},analyze_audio_transcript=False,audio_time_offset=600,audio_segment_duration=30)
    assert rows[0]['start_time']==600 and rows[0]['end_time']==630
    assert rows[0]['confidence'] is None and rows[0]['structured_data']['timestampPrecision']=='segment_window'
    precise=build_audio_blocks({'segments':[{'text':'Definition','start':1,'end':2,'confidence':0.7}]},analyze_audio_transcript=False,audio_segment_duration=30)[0]
    assert precise['confidence']==0.7 and precise['structured_data']['timestampPrecision']=='asr_segment'
    rounded=build_audio_blocks({'segments':[{'text':'Definition','start':1,'end':10.2,'confidence':True}]},analyze_audio_transcript=False,audio_segment_duration=10)[0]
    assert rounded['end_time']==10 and rounded['confidence'] is None


@pytest.mark.parametrize('source',[{'kind':'notes','version':1},{'kind':'wrong_answer'},{'kind':'mind_map_node','version':1,'nodeId':'n'}])
def test_only_material_sources_allow_selected_blocks(source):
    with pytest.raises(ValidationError):ConversionSource(id=MATERIAL,blockIds=[BLOCK],**source)


def test_new_optional_field_preserves_old_conversion_fingerprints():
    from app.models.conversion import ConversionRequest
    values={'requestId':LECTURE,'subjectId':SUBJECT,'source':{'kind':'notes','id':MATERIAL,'version':1},'target':'flashcards'}
    request=ConversionRequest.model_validate(values)
    old=request.model_dump(mode='json',by_alias=True,exclude={'request_id'})
    old['source'].pop('blockIds')
    assert conversion_service.fingerprint(request)==hashlib.sha256(json.dumps(old,sort_keys=True,separators=(',',':')).encode()).hexdigest()


class Query:
    def __init__(self,client,table):self.client,self.table,self.filters=client,table,[]
    def select(self,*args):return self
    def eq(self,key,value):self.filters.append((key,value));return self
    def in_(self,key,values):self.filters.append((key,values));return self
    def order(self,*args,**kwargs):return self
    def limit(self,*args):return self
    def execute(self):
        self.client.calls.append((self.table,self.filters))
        return SimpleNamespace(data=deepcopy(self.client.rows.get(self.table,[])))


class Client:
    def __init__(self,rows):self.rows,self.calls=rows,[]
    def table(self,name):return Query(self,name)


def test_selected_transcript_conversion_uses_only_owned_material_blocks(monkeypatch):
    client=Client({'content_blocks':[{'id':BLOCK}]})
    monkeypatch.setattr(conversion_service,'get_supabase_client',lambda:client)
    monkeypatch.setattr(conversion_service,'_owned',lambda **_:{'status':'ready','filename':'Lecture.wav'})
    scopes=[]
    monkeypatch.setattr(conversion_service.notes_service,'canonical_sources',lambda **values:scopes.append(values) or [{'id':BLOCK,'chunkText':'Definition','startTime':600}])
    monkeypatch.setattr(service,'selected_context',lambda **_:{'topicIds':[TOPIC],'lectureId':LECTURE})
    source=ConversionSource(kind='material',id=MATERIAL,blockIds=[BLOCK])
    result=conversion_service.snapshot_source(user_id=OWNER,subject_id=SUBJECT,source=source)
    assert result['topicIds']==[TOPIC] and result['content']['lectureId']==LECTURE and result['content']['selectedBlockIds']==[BLOCK]
    assert scopes[0]['block_ids']==[BLOCK] and ('material_id',MATERIAL) in client.calls[0][1]
    client.rows['content_blocks']=[]
    with pytest.raises(HTTPException) as error:conversion_service.snapshot_source(user_id=OWNER,subject_id=SUBJECT,source=source)
    assert error.value.status_code==404


@pytest.mark.parametrize('stale',[False,True])
def test_only_current_topic_alignment_is_inherited(monkeypatch,stale):
    evidence=[{'id':BLOCK,'chunkText':'Original','startTime':0,'endTime':10}]
    client=Client({'lectures':[{'id':LECTURE}],'lecture_topic_links':[{'block_id':BLOCK,'knowledge_point_id':TOPIC,'source_text':'Changed' if stale else 'Original','start_time':0,'end_time':10}],'knowledge_points':[{'id':TOPIC}]})
    monkeypatch.setattr(service,'get_supabase_client',lambda:client)
    result=service.selected_context(user_id=OWNER,subject_id=SUBJECT,material_id=MATERIAL,citations=evidence)
    assert result['lectureId']==LECTURE and result['topicIds']==([] if stale else [TOPIC])
    assert all(('user_id',OWNER) in filters and ('subject_id',SUBJECT) in filters for _,filters in client.calls)


@pytest.mark.parametrize('code,status',[('40001',409),('42501',404),('23503',404),('22023',422)])
def test_lecture_rpc_maps_errors_without_internal_details(monkeypatch,code,status):
    class Failure(Exception):pass
    failure=Failure('private detail');failure.code=code
    def fail(*args):raise failure
    monkeypatch.setattr(service,'get_supabase_client',lambda:SimpleNamespace(rpc=fail))
    with pytest.raises(HTTPException) as error:service.rpc('operation',{})
    assert error.value.status_code==status and 'private detail' not in error.value.detail


def test_lecture_api_auth_identity_version_and_pagination(monkeypatch):
    calls=[]
    monkeypatch.setattr(service,'attach',lambda **values:calls.append(values) or {'id':LECTURE})
    monkeypatch.setattr(service,'align',lambda **values:calls.append(values) or {'version':2})
    monkeypatch.setattr(service,'transcript',lambda **values:calls.append(values) or {'blocks':[]})
    app.dependency_overrides[get_current_user]=lambda:CurrentUser(id=OWNER)
    try:
        with TestClient(app) as client:
            assert client.post('/api/v1/lectures',json={'subject_id':SUBJECT,'material_id':MATERIAL,'title':'Lecture'}).status_code==200
            assert calls[-1]['user_id']==OWNER and calls[-1]['source_kind']=='upload'
            assert client.put(f'/api/v1/lectures/{LECTURE}/blocks/{BLOCK}/topic',json={'topic_id':TOPIC,'version':1}).status_code==200
            assert calls[-1]['user_id']==OWNER and calls[-1]['version']==1
            assert client.get(f'/api/v1/lectures/{LECTURE}/transcript',params={'block_id':BLOCK}).status_code==200
            assert calls[-1]['block_id']==BLOCK and calls[-1]['user_id']==OWNER
            assert client.get(f'/api/v1/lectures/{LECTURE}/transcript',params={'limit':101}).status_code==422
            assert client.post('/api/v1/lectures',json={'subject_id':SUBJECT,'material_id':MATERIAL,'title':'Lecture','user_id':'forged'}).status_code==422
    finally:app.dependency_overrides.pop(get_current_user,None)
    with TestClient(app) as client:assert client.get('/api/v1/lectures/capabilities').status_code==401
