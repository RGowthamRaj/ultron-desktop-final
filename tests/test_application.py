import asyncio
import threading
import unittest
from unittest.mock import Mock, patch

from core.conversation import Conversation
from main import JarvisLive


class ApplicationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.controller=JarvisLive.__new__(JarvisLive)
        self.controller.ui=Mock()
        self.controller._command_lock=threading.Lock()
        self.controller._turn_cancel=None
        self.controller._conversation=Conversation()
        self.controller._has_microphone=False
        self.controller._dashboard=None
        self.controller._asst_name='Ultron'
        self.controller._session_log=[]
        self.controller._tts_player=None
        self.controller.set_speaking=Mock()
        self.controller._execute_tool_sync=Mock(return_value='4')
        self.controller._build_full_system_prompt=Mock(return_value=('system',[]))
        self.config={'ai_provider':'ollama','ai_model':'model','llm_url':'http://localhost:11434',
                     'speak_replies':False,'tools_enabled':False}

    async def test_controller_preserves_followup_and_releases_busy_state(self):
        with patch('main.load_api_keys',return_value=self.config),patch('core.provider_transport.call_provider',return_value={'content':'Hello'}) as provider:
            await self.controller._handle_unified_text_command('My name is Sam')
            await self.controller._handle_unified_text_command('What is my name?')
        self.assertEqual(len(self.controller._conversation.turns),2)
        messages=provider.call_args.args[1]
        self.assertIn('My name is Sam',[message.get('content') for message in messages])
        self.assertFalse(self.controller._command_lock.locked())
        self.controller.ui.set_state.assert_called_with('ONLINE')
        self.controller._execute_tool_sync.assert_not_called()

    async def test_provider_error_does_not_leave_controller_busy(self):
        with patch('main.load_api_keys',return_value=self.config),patch('core.provider_transport.call_provider',side_effect=RuntimeError('Provider unavailable')):
            await self.controller._handle_unified_text_command('Hello')
        self.assertFalse(self.controller._command_lock.locked())
        self.controller.ui.write_log.assert_any_call('ERR: Provider unavailable')
        self.assertEqual(self.controller._conversation.turns,[])

    async def test_microphone_failure_leaves_text_session_running(self):
        with patch('main.audio_devices.resolve',return_value=None),patch('main.sd.InputStream',side_effect=RuntimeError('No hardware')):
            await self.controller._listen_audio()
        self.controller.ui.set_microphone_available.assert_called_with(False)
        self.assertFalse(self.controller._has_microphone)

    async def test_busy_typed_command_is_rejected_before_submission(self):
        self.controller._loop=asyncio.get_running_loop()
        self.controller._wake_enabled=False
        self.controller.session=None
        self.controller._command_lock.acquire()
        try:
            self.assertFalse(self.controller._on_text_command('Keep this draft'))
        finally:
            self.controller._command_lock.release()

    async def test_interrupt_cancels_future_actions(self):
        self.controller._turn_cancel=threading.Event()
        self.controller.audio_in_queue=None
        self.controller._visemes=Mock()
        self.controller._turn_done_event=None
        self.controller.interrupt()
        self.assertTrue(self.controller._turn_cancel.is_set())
