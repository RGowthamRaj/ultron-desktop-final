from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import unittest
from unittest.mock import patch

from core.provider_settings import Connection, from_config, normalize_url, updated_config
from core.provider_transport import call_provider, test_connection
from core.llm_client import call_unified
from memory import config_manager

TOOLS=[{'type':'function','function':{'name':'calculator','description':'Arithmetic',
                                     'parameters':{'type':'object','properties':{}}}}]


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.requests=[]
        self.responses=[]
        requests, responses=self.requests, self.responses
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):
                pass
            def do_POST(self):
                requests.append({'path':self.path, 'headers':dict(self.headers),
                                 'payload':json.loads(self.rfile.read(int(self.headers['Content-Length'])))})
                status,data=responses.pop(0)
                self.send_response(status)
                self.send_header('Content-Type','application/json')
                if status==307:
                    self.send_header('Location','/redirected')
                self.end_headers()
                self.wfile.write(json.dumps(data).encode())
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.base=f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def answer(self,text='OK'):
        return {'choices':[{'message':{'content':text}}]}

    def test_openai_http_round_trip_and_token_options(self):
        self.responses.append((200,self.answer()))
        result=call_provider(Connection('gpt','gpt-4.1-mini','fake-key',self.base),
                             [{'role':'user','content':'Hi'}],TOOLS)
        request=self.requests[0]
        self.assertEqual(request['path'],'/v1/chat/completions')
        self.assertFalse(request['payload']['store'])
        self.assertEqual(request['payload']['max_completion_tokens'],2048)
        self.assertEqual(request['headers']['Authorization'],'Bearer fake-key')
        self.assertEqual(result['content'],'OK')

    def test_complete_tool_round_trip_uses_only_supported_openai_message_fields(self):
        from core.conversation import Conversation
        self.responses.extend([(200,{'choices':[{'message':{'content':None,'tool_calls':[
            {'id':'calc1','type':'function','function':{'name':'calculator','arguments':'{}'}}]}}]}),
                               (200,self.answer('The answer is 4.'))])
        connection=Connection('gpt','test-model','',self.base)
        result=Conversation().reply('Calculate','Instructions',TOOLS,
            lambda messages:call_provider(connection,messages,TOOLS),lambda name,args:'4')
        self.assertEqual(result,'The answer is 4.')
        tool=self.requests[-1]['payload']['messages'][-1]
        self.assertEqual(set(tool),{'role','content','tool_call_id'})
        self.assertEqual(tool['tool_call_id'],'calc1')

    def test_unsaved_connection_test_sends_no_tools(self):
        self.responses.append((200,self.answer()))
        self.assertIn('verified',test_connection(Connection('gpt','model','',self.base)))
        self.assertNotIn('tools',self.requests[0]['payload'])

    def test_redirect_does_not_forward_credentials(self):
        self.responses.append((307,{}))
        with self.assertRaisesRegex(RuntimeError,'redirected'):
            test_connection(Connection('gpt','model','fake-key',self.base))
        self.assertEqual(len(self.requests),1)

    def test_provider_error_is_actionable_and_does_not_echo_response_body(self):
        self.responses.append((401,{'error':'fake-secret-in-error-body'}))
        with self.assertRaisesRegex(RuntimeError,'API key rejected') as error:
            test_connection(Connection('gpt','model','fake-key',self.base))
        self.assertNotIn('fake-secret',str(error.exception))

    def test_ollama_keeps_native_tool_arguments(self):
        self.responses.append((200,{'message':{'content':'','tool_calls':[
            {'function':{'name':'calculator','arguments':{'value':2}}}]}}))
        result=call_provider(Connection('ollama','local-model','',self.base),[{'role':'user','content':'Compute'}],TOOLS)
        self.assertEqual(self.requests[0]['path'],'/api/chat')
        self.assertEqual(result['tool_calls'][0]['function']['arguments'],{'value':2})

    def test_gemini_keeps_roles_tool_results_and_key_out_of_url(self):
        self.responses.append((200,{'candidates':[{'content':{'parts':[{'text':'Done'}]}}]}))
        messages=[{'role':'system','content':'Instructions'}, {'role':'user','content':'Compute'},
                  {'role':'assistant','content':'','tool_calls':[{'id':'abc','function':{'name':'calculator','arguments':'{}'}}]},
                  {'role':'tool','tool_call_id':'abc','content':'4'}]
        call_provider(Connection('gemini','models/test-model','fake-google-key',self.base+'/v1beta'),messages,TOOLS)
        request=self.requests[0]
        self.assertEqual(request['path'],'/v1beta/models/test-model:generateContent')
        self.assertNotIn('fake-google-key',request['path'])
        self.assertEqual(request['headers']['x-goog-api-key'],'fake-google-key')
        contents=request['payload']['contents']
        self.assertEqual(contents[1]['role'],'model')
        self.assertEqual(contents[-1]['parts'][0]['functionResponse']['name'],'calculator')

    def test_claude_translates_structured_tool_exchange(self):
        self.responses.append((200,{'content':[{'type':'text','text':'Done'}]}))
        messages=[{'role':'system','content':'Instructions'}, {'role':'user','content':'Compute'},
                  {'role':'assistant','content':'','tool_calls':[{'id':'abc','function':{'name':'calculator','arguments':'{}'}}]},
                  {'role':'tool','tool_call_id':'abc','content':'4'}]
        result=call_provider(Connection('claude','test-model','fake-key',self.base+'/v1'),messages,TOOLS)
        self.assertEqual(result['content'],'Done')
        self.assertEqual(self.requests[0]['payload']['messages'][-1]['content'][0]['tool_use_id'],'abc')

    def test_legacy_dispatcher_uses_same_adapter_and_saved_provider_alias(self):
        self.responses.append((200,self.answer('Ready')))
        config={'ai_provider':'nvidia_nim','ai_model':'test-model','nvidia_api_key':'fake-nvidia',
                'nvidia_base_url':self.base+'/v1'}
        with patch.object(config_manager,'load_api_keys',return_value=config):
            result=call_unified('Hello',system='Instructions')
        self.assertEqual(result['content'],'Ready')
        self.assertEqual(self.requests[0]['headers']['Authorization'],'Bearer fake-nvidia')

    def test_bad_schema_rejected_without_actions(self):
        self.responses.append((200,{'choices':[]}))
        with self.assertRaisesRegex(RuntimeError,'incompatible chat response'):
            test_connection(Connection('gpt','model','',self.base))


class SettingsTests(unittest.TestCase):
    def test_legacy_key_migration_preserves_old_provider_without_forwarding_key(self):
        original={'ai_provider':'gpt','ai_model':'old-model','api_key':'fake-old-key'}
        saved=updated_config(original,Connection('ollama','new-model','', 'http://localhost:11434'))
        self.assertNotIn('api_key',saved)
        self.assertEqual(saved['openai_api_key'],'fake-old-key')
        self.assertEqual(from_config(saved).key,'')
        self.assertEqual(original['api_key'],'fake-old-key')

    def test_transport_validation_and_url_normalization(self):
        for value in ('http://remote.example/v1','https://key@example.com/v1','https://example.com/v1?key=secret',
                      'file:///tmp/model','https://example.com:bad/v1'):
            with self.subTest(url=value),self.assertRaises(ValueError):
                normalize_url(value)
        self.assertEqual(normalize_url('https://example.com/v1/chat/completions/'),'https://example.com/v1')

    def test_key_aliases_and_no_cross_provider_key_fallback(self):
        cfg={'ai_provider':'nvidia_nim','ai_model':'model','nvidia_api_key':'fake-nvidia',
             'api_key':'fake-other-provider'}
        self.assertEqual(from_config(cfg).key,'fake-nvidia')
        cfg={'ai_provider':'claude','ai_model':'model','anthropic_api_key':'fake-claude'}
        self.assertEqual(from_config(cfg).key,'fake-claude')
        with self.assertRaisesRegex(ValueError,'API key'):
            from_config({'ai_provider':'gpt','ai_model':'model','api_key':'fake-openai'},provider='claude')
