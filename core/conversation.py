"""Bounded conversation history and cancellable, structured tool round trips."""
import copy
import json
import threading


class ConversationCancelled(Exception):
    pass


class ConversationBusy(Exception):
    pass


class Conversation:
    def __init__(self, max_turns=6, max_characters=64000):
        self.turns = []
        self.max_turns = max_turns
        self.max_characters = max_characters
        self.identity = None
        self._lock = threading.Lock()

    def clear(self):
        if not self._lock.acquire(blocking=False):
            return False
        try:
            self.turns.clear()
            return True
        finally:
            self._lock.release()

    def reply(self, text, system, tools, call, execute, stopped=lambda: False,
              identity=None, provider='gpt', report=lambda name, result: None):
        if not text.strip() or len(text) > 16000:
            raise ValueError('Enter a message between 1 and 16,000 characters.')
        if not self._lock.acquire(blocking=False):
            raise ConversationBusy('A response is still running. Stop it or wait before sending another.')
        def check():
            if stopped():
                raise ConversationCancelled('Response stopped. Actions already completed cannot be undone.')
        try:
            check()
            if identity != self.identity:
                self.turns.clear()
                self.identity = identity
            messages = [{'role': 'system', 'content': system}]
            messages.extend(copy.deepcopy([item for turn in self.turns for item in turn]))
            turn = [{'role': 'user', 'content': text.strip()}]
            messages.extend(turn)
            allowed = {tool.get('function', tool).get('name') for tool in tools}
            for _ in range(6):
                check()
                result = call(messages)
                check()
                content = result.get('content') or ''
                calls = result.get('tool_calls') or []
                if not isinstance(content, str) or not isinstance(calls, list) or len(calls) > 8:
                    raise RuntimeError('The model returned an incompatible response or too many actions.')
                if not calls:
                    if not content.strip():
                        raise RuntimeError('The model returned no final answer. Check the model and tool settings.')
                    turn.append({'role': 'assistant', 'content': content})
                    self.turns.append(copy.deepcopy(turn))
                    while (len(self.turns) > self.max_turns or
                           len(json.dumps(self.turns)) > self.max_characters):
                        self.turns.pop(0)
                    return content
                wire_calls = []
                for index, tool in enumerate(calls):
                    function = tool.get('function', {})
                    name = function.get('name')
                    arguments = function.get('arguments', {})
                    if not isinstance(name, str) or not isinstance(arguments, (str, dict)):
                        raise RuntimeError('The model returned an invalid tool call.')
                    identifier = tool.get('id') or f'call_{index}'
                    if not isinstance(identifier, str):
                        raise RuntimeError('The model returned an invalid tool identifier.')
                    if isinstance(arguments, dict) and provider != 'ollama':
                        arguments = json.dumps(arguments)
                    wire_calls.append({'id': identifier, 'type': 'function',
                                       'function': {'name': name, 'arguments': arguments}})
                if len({tool['id'] for tool in wire_calls}) != len(wire_calls):
                    raise RuntimeError('The model returned duplicate tool identifiers.')
                assistant = {'role': 'assistant', 'content': content, 'tool_calls': wire_calls}
                turn.append(assistant)
                messages.append(assistant)
                for tool in wire_calls:
                    check()
                    function = tool['function']
                    name = function['name']
                    try:
                        if name not in allowed:
                            raise ValueError('This tool is not enabled for the current conversation.')
                        arguments = function['arguments']
                        if isinstance(arguments, str):
                            arguments = json.loads(arguments)
                        if not isinstance(arguments, dict):
                            raise ValueError('Tool arguments must be a JSON object.')
                        check()
                        output = str(execute(name, arguments))
                    except ConversationCancelled:
                        raise
                    except Exception as error:
                        output = 'Action failed: ' + str(error)
                    # Results may contain large documents; keep the next request bounded.
                    output = output[:16000]
                    report(name, output)
                    item = {'role': 'tool', 'tool_call_id': tool['id'], 'name': name, 'content': output}
                    turn.append(item)
                    messages.append(item)
            raise RuntimeError('The model reached the action limit. Ask for a smaller task.')
        finally:
            self._lock.release()
