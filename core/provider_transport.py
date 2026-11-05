"""Non-streaming provider adapters with one normalized tool-call protocol."""
import json
import requests

from .provider_settings import Connection


def _post(url, payload, headers, timeout):
    try:
        with requests.post(url, json=payload, headers=headers, timeout=timeout,
                           allow_redirects=False) as response:
            if 300 <= response.status_code < 400:
                raise RuntimeError('The provider redirected the request. Check its base URL; no redirect was followed.')
            errors = {400: 'Provider rejected this model or tool configuration.',
                      401: 'API key rejected. Check the selected provider and key.',
                      403: 'This key does not have access to the selected model.',
                      404: 'Model or endpoint not found. Check the model ID and base URL.',
                      429: 'Provider usage limit reached. Check your allowance or retry later.'}
            if response.status_code != 200:
                raise RuntimeError(errors.get(response.status_code, f'Provider returned HTTP {response.status_code}.'))
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError
            return data
    except requests.exceptions.Timeout:
        raise RuntimeError('Provider request timed out. Your next message can retry.') from None
    except requests.exceptions.SSLError:
        raise RuntimeError('Provider TLS verification failed. Check the certificate configuration.') from None
    except requests.exceptions.RequestException:
        raise RuntimeError('Cannot reach the provider. Check its base URL and network connection.') from None
    except (ValueError, TypeError):
        raise RuntimeError('Provider did not return compatible JSON.') from None


def _message(content, calls):
    if content is not None and not isinstance(content, str):
        raise RuntimeError('Provider returned unsupported message content.')
    if not isinstance(calls, list):
        raise RuntimeError('Provider returned incompatible tool calls.')
    normalized = []
    for index, call in enumerate(calls):
        if not isinstance(call, dict) or not isinstance(call.get('function'), dict):
            raise RuntimeError('Provider returned an invalid tool call.')
        function = call['function']
        if not isinstance(function.get('name'), str) or not function['name']:
            raise RuntimeError('Provider returned a tool without a name.')
        arguments = function.get('arguments', {})
        if not isinstance(arguments, (str, dict)):
            raise RuntimeError('Provider returned invalid tool arguments.')
        identifier = call.get('id') or f'call_{index}'
        if not isinstance(identifier, str):
            raise RuntimeError('Provider returned an invalid tool-call identifier.')
        normalized.append({'id': identifier, 'function': {'name': function['name'], 'arguments': arguments}})
    if len({call['id'] for call in normalized}) != len(normalized):
        raise RuntimeError('Provider returned duplicate tool-call identifiers.')
    return {'content': content or '', 'tool_calls': normalized}


def _gemini_messages(messages):
    system, contents, names = [], [], {}
    for message in messages:
        role, content = message['role'], message.get('content') or ''
        if role in ('system', 'developer'):
            system.append(content)
            continue
        parts = []
        if role == 'tool':
            parts.append({'functionResponse': {'name': names.get(message['tool_call_id'], 'tool'),
                                               'response': {'result': content}}})
        else:
            if content:
                parts.append({'text': content})
            for call in message.get('tool_calls', []):
                function = call['function']
                names[call['id']] = function['name']
                arguments = function['arguments']
                if isinstance(arguments, str):
                    arguments = json.loads(arguments)
                parts.append({'functionCall': {'name': function['name'], 'args': arguments}})
        if parts:
            contents.append({'role': 'model' if role == 'assistant' else 'user', 'parts': parts})
    return system, contents


def _claude_messages(messages):
    system, contents = [], []
    for message in messages:
        role, content = message['role'], message.get('content') or ''
        if role in ('system', 'developer'):
            system.append(content)
            continue
        blocks = []
        if role == 'tool':
            blocks.append({'type': 'tool_result', 'tool_use_id': message['tool_call_id'], 'content': content})
        else:
            if content:
                blocks.append({'type': 'text', 'text': content})
            for call in message.get('tool_calls', []):
                function = call['function']
                arguments = function['arguments']
                if isinstance(arguments, str):
                    arguments = json.loads(arguments)
                blocks.append({'type': 'tool_use', 'id': call['id'], 'name': function['name'], 'input': arguments})
        if blocks:
            target_role = 'assistant' if role == 'assistant' else 'user'
            if contents and contents[-1]['role'] == target_role:
                contents[-1]['content'].extend(blocks)
            else:
                contents.append({'role': target_role, 'content': blocks})
    return system, contents


def call_provider(connection: Connection, messages, tools=None, timeout=60):
    connection = connection.validated()
    provider, model, key, base = connection.provider, connection.model, connection.key, connection.base_url
    headers = {'Content-Type': 'application/json'}
    tools = tools or []
    try:
        if provider == 'gemini':
            system, contents = _gemini_messages(messages)
            payload = {'contents': contents}
            if system:
                payload['systemInstruction'] = {'parts': [{'text': '\n'.join(system)}]}
            if tools:
                payload['tools'] = [{'functionDeclarations': [tool['function'] for tool in tools]}]
            headers['x-goog-api-key'] = key
            data = _post(f'{base}/models/{model.removeprefix("models/")}:generateContent', payload, headers, timeout)
            parts = data['candidates'][0]['content']['parts']
            content = ''.join(part.get('text', '') for part in parts if not part.get('thought'))
            calls = [{'id': f'call_{i}', 'function': {'name': part['functionCall']['name'],
                       'arguments': part['functionCall'].get('args', {})}}
                     for i, part in enumerate(parts) if 'functionCall' in part]
            return _message(content, calls)
        if provider == 'claude':
            system, contents = _claude_messages(messages)
            headers.update({'x-api-key': key, 'anthropic-version': '2023-06-01'})
            payload = {'model': model, 'messages': contents, 'max_tokens': 2048}
            if system:
                payload['system'] = '\n'.join(system)
            if tools:
                payload['tools'] = [{'name': tool['function']['name'],
                                     'description': tool['function'].get('description', ''),
                                     'input_schema': tool['function']['parameters']} for tool in tools]
            data = _post(base + '/messages', payload, headers, timeout)
            blocks = data['content']
            content = ''.join(block.get('text', '') for block in blocks if block.get('type') == 'text')
            calls = [{'id': block['id'], 'function': {'name': block['name'], 'arguments': block['input']}}
                     for block in blocks if block.get('type') == 'tool_use']
            return _message(content, calls)
        wire_messages = []
        for message in messages:
            item = dict(message)
            name = item.pop('name', None)
            if provider == 'ollama':
                if item['role'] == 'tool':
                    item.pop('tool_call_id', None)
                    if name:
                        item['tool_name'] = name
                if item.get('tool_calls'):
                    native_calls = []
                    for call in item['tool_calls']:
                        function = dict(call['function'])
                        if isinstance(function['arguments'], str):
                            try:
                                function['arguments'] = json.loads(function['arguments'])
                            except ValueError:
                                raise RuntimeError('Provider returned invalid JSON tool arguments.') from None
                        native_calls.append({'function': function})
                    item['tool_calls'] = native_calls
            wire_messages.append(item)
        payload = {'model': model, 'messages': wire_messages, 'stream': False}
        if key:
            headers['Authorization'] = 'Bearer ' + key
        if tools:
            payload['tools'] = tools
        if provider == 'ollama':
            payload['keep_alive'] = -1
            data = _post(base + '/api/chat', payload, headers, timeout)
            message = data['message']
        else:
            if tools:
                payload['tool_choice'] = 'auto'
            if provider == 'gpt':
                payload.update({'max_completion_tokens': 2048, 'store': False})
            data = _post(connection.chat_url(), payload, headers, timeout)
            message = data['choices'][0]['message']
        return _message(message.get('content'), message.get('tool_calls') or [])
    except (KeyError, IndexError, TypeError, AttributeError):
        raise RuntimeError('Provider returned an incompatible chat response. Check the model.') from None


def test_connection(connection):
    result = call_provider(connection, [{'role': 'user', 'content': 'Reply with OK.'}], timeout=15)
    if not result['content'].strip():
        raise RuntimeError('The model returned no final text. Check model compatibility.')
    return 'Connection verified. Save to start your conversation.'
