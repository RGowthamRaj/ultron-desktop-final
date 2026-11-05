import json
import threading
import unittest
from unittest.mock import Mock

from core.conversation import Conversation, ConversationCancelled, ConversationBusy
from core.prompting import auto_prompt

TOOLS = [{'type': 'function', 'function': {'name': 'calculator', 'parameters': {'type': 'object'}}}]

def tool_call(arguments=None, name='calculator'):
    return {'content': '', 'tool_calls': [{'id': 'call1', 'function': {'name': name, 'arguments': arguments or {'value': 2}}}]}


class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.session = Conversation()
        self.execute = Mock(return_value='4')

    def reply(self, call, text='Calculate', stopped=lambda: False, **kwargs):
        return self.session.reply(text, 'system instructions', TOOLS, call, self.execute, stopped, **kwargs)

    def test_tool_results_use_the_original_call_id_and_all_messages(self):
        received=[]
        def call(messages):
            received.append(json.loads(json.dumps(messages)))
            return tool_call() if len(received)==1 else {'content': 'Result: 4'}
        self.assertEqual(self.reply(call), 'Result: 4')
        self.execute.assert_called_once_with('calculator', {'value': 2})
        self.assertEqual(received[1][-1]['role'], 'tool')
        self.assertEqual(received[1][-1]['tool_call_id'], 'call1')
        self.assertEqual(received[1][-2]['tool_calls'][0]['id'], 'call1')
        self.assertEqual(received[1][1]['role'], 'user')

    def test_followup_keeps_history_and_does_not_mutate_prior_requests(self):
        first=Mock(return_value={'content': 'Your name is Sam.'})
        self.reply(first, 'My name is Sam')
        second=Mock(return_value={'content': 'Sam.'})
        self.reply(second, 'What is my name?')
        messages=second.call_args.args[0]
        self.assertEqual([m['role'] for m in messages], ['system','user','assistant','user'])
        self.assertEqual(messages[1]['content'], 'My name is Sam')
        self.assertEqual(len(first.call_args.args[0]), 2)

    def test_cancel_after_provider_response_prevents_desktop_action(self):
        stopped=threading.Event()
        def call(messages):
            stopped.set()
            return tool_call()
        with self.assertRaises(ConversationCancelled):
            self.reply(call, stopped=stopped.is_set)
        self.execute.assert_not_called()
        self.assertEqual(self.session.turns, [])

    def test_unknown_or_malformed_tool_is_reported_without_execution(self):
        for result in (tool_call(name='unavailable'), tool_call(arguments='not-json')):
            with self.subTest(result=result):
                calls=Mock(side_effect=[result, {'content':'Could not complete the action.'}])
                self.reply(calls)
                self.execute.assert_not_called()
                self.assertIn('Action failed', calls.call_args.args[0][-1]['content'])

    def test_failed_tool_feedback_is_available_for_model_recovery(self):
        self.execute.side_effect=RuntimeError('Device unavailable')
        calls=Mock(side_effect=[tool_call(), {'content':'The device is unavailable.'}])
        self.assertEqual(self.reply(calls), 'The device is unavailable.')
        self.assertIn('Device unavailable', calls.call_args.args[0][-1]['content'])

    def test_history_is_bounded_and_provider_switch_clears_old_context(self):
        for index in range(9):
            self.reply(Mock(return_value={'content':'Answer'}), str(index), identity='provider-a')
        self.assertEqual(len(self.session.turns), 6)
        other=Mock(return_value={'content':'New provider'})
        self.reply(other, 'Hello', identity='provider-b')
        self.assertEqual(len(other.call_args.args[0]), 2)
        self.assertEqual(len(self.session.turns), 1)

    def test_concurrent_turn_and_clear_do_not_interleave(self):
        self.session._lock.acquire()
        try:
            with self.assertRaises(ConversationBusy):
                self.reply(Mock())
            self.assertFalse(self.session.clear())
        finally:
            self.session._lock.release()

    def test_auto_prompt_contains_only_enabled_capabilities(self):
        prompt=auto_prompt('Debug my Python code', TOOLS, microphone=False)
        self.assertIn('development', prompt)
        self.assertIn('calculator', prompt)
        self.assertIn('no; use typed input', prompt)
        self.assertIn('none; conversation only', auto_prompt('Hello'))

    def test_action_limit_never_reports_false_success(self):
        with self.assertRaisesRegex(RuntimeError, 'action limit'):
            self.reply(Mock(side_effect=lambda messages: tool_call()))
        self.assertEqual(self.session.turns, [])
        self.assertEqual(self.execute.call_count, 6)
