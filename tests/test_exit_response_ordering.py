"""Exit acknowledgement must cross the outer transport before shutdown."""
import asyncio
import json

import pytest
from fieldbook_sync import app as field
from surveysync.http_shutdown import EXIT_REQUESTED, ExitAfterResponseMiddleware


def scope(method='POST',path='/api/application/exit'):
    return {'type':'http','asgi':{'version':'3.0','spec_version':'2.4'},'http_version':'1.1',
            'method':method,'scheme':'http','path':path,'raw_path':path.encode(),
            'query_string':b'','root_path':'','headers':[], 'server':('127.0.0.1',8765),'client':('127.0.0.1',1234)}


def test_real_app_finishes_slow_outer_body_before_shutdown(monkeypatch):
    sent=[]; events=[]
    monkeypatch.setattr(field,'request_application_shutdown',lambda reason:events.append('shutdown'))
    async def scenario():
        disconnected=asyncio.Event(); sent_request=False
        async def receive():
            nonlocal sent_request
            if not sent_request:
                sent_request=True
                return {'type':'http.request','body':b'','more_body':False}
            await disconnected.wait()
            return {'type':'http.disconnect'}
        async def send(message):
            if message['type']=='http.response.body' and not message.get('more_body',False):
                # Exceeds the old 150ms timer. The route-level BackgroundTask
                # alternative also fails this real buffering-middleware check.
                await asyncio.sleep(.22)
                assert 'shutdown' not in events
                events.append('body-sent')
            sent.append(message)
        await field.app(scope(),receive,send)
    asyncio.run(scenario())
    assert events==['body-sent','shutdown']
    assert sent[0]['status']==200
    assert json.loads(b''.join(m.get('body',b'') for m in sent))['ok'] is True


@pytest.mark.parametrize('marked,status,method,path,expected',[
    (True,200,'POST','/api/application/exit',True),
    (False,200,'POST','/api/application/exit',False),
    (True,400,'POST','/api/application/exit',False),
    (True,500,'POST','/api/application/exit',False),
    (True,200,'GET','/api/application/exit',False),
    (True,200,'POST','/api/other',False),
])
def test_only_successful_explicit_exit_response_triggers_callback(marked,status,method,path,expected):
    events=[]
    async def inner(s,receive,send):
        if marked:s[EXIT_REQUESTED]=True
        await send({'type':'http.response.start','status':status,'headers':[]})
        await send({'type':'http.response.body','body':b'{}','more_body':False})
        events.append('inner-complete')
    async def send(message):events.append(message['type'])
    middleware=ExitAfterResponseMiddleware(inner,lambda:events.append('shutdown'))
    asyncio.run(middleware(scope(method,path),None,send))
    assert ('shutdown' in events)==expected
    if expected:assert events[-2:]==['inner-complete','shutdown']


def test_failed_transport_send_does_not_claim_exit_acknowledgement():
    events=[]
    async def inner(s,receive,send):
        s[EXIT_REQUESTED]=True
        await send({'type':'http.response.start','status':200,'headers':[]})
        await send({'type':'http.response.body','body':b'{}','more_body':False})
    async def send(message):
        if message['type']=='http.response.body':raise ConnectionAbortedError('fixture')
    middleware=ExitAfterResponseMiddleware(inner,lambda:events.append('shutdown'))
    with pytest.raises(ConnectionAbortedError):asyncio.run(middleware(scope(),None,send))
    assert events==[]
