"""Provider configuration shared by setup, diagnostics, and HTTP clients."""
from dataclasses import dataclass
from urllib.parse import urlsplit

DEFAULT_URLS = {
    'gemini': 'https://generativelanguage.googleapis.com/v1beta',
    'ollama': 'http://localhost:11434',
    'gpt': 'https://api.openai.com/v1',
    'nvidia_nim': 'https://integrate.api.nvidia.com/v1',
    'opencode_zen': 'https://api.opencode.zen/v1',
    'claude': 'https://api.anthropic.com/v1',
    'deepseek': 'https://api.deepseek.com',
    'groq': 'https://api.groq.com/openai/v1',
    'openrouter': 'https://openrouter.ai/api/v1',
}
KEY_FIELDS = {'gpt': 'openai_api_key', 'nvidia_nim': 'nvidia_api_key',
              'claude': 'anthropic_api_key'}
URL_FIELDS = {'gpt': 'openai_base_url', 'nvidia_nim': 'nvidia_base_url',
              'opencode_zen': 'opencode_base_url', 'ollama': 'llm_url'}


def normalize_url(value: str) -> str:
    value = value.strip().rstrip('/')
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise ValueError('Enter a valid provider URL and port.') from None
    if (parsed.scheme not in ('https', 'http') or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError('Use a provider base URL without credentials, query parameters, or fragments.')
    if parsed.scheme == 'http' and parsed.hostname not in ('localhost', '127.0.0.1', '::1'):
        raise ValueError('Remote providers require HTTPS. HTTP is supported on localhost only.')
    for suffix in ('/chat/completions', '/api/chat'):
        if value.endswith(suffix):
            value = value[:-len(suffix)]
    return value


@dataclass(frozen=True)
class Connection:
    provider: str
    model: str
    key: str = ''
    base_url: str = ''

    def validated(self):
        if self.provider not in DEFAULT_URLS:
            raise ValueError('Choose a supported AI provider.')
        model = self.model.strip()
        if not model or len(model) > 256:
            raise ValueError('Enter a model ID from your provider.')
        url = normalize_url(self.base_url or DEFAULT_URLS[self.provider])
        key = self.key.strip()
        if any(char in key for char in ('\r', '\n')):
            raise ValueError('The API key must fit on one line.')
        local = urlsplit(url).hostname in ('localhost', '127.0.0.1', '::1')
        if self.provider != 'ollama' and not key and not local:
            raise ValueError('Enter an API key for this remote provider.')
        return Connection(self.provider, model, key, url)

    def chat_url(self):
        base = self.base_url
        if not urlsplit(base).path.strip('/'):
            base += '/v1'
        return base + '/chat/completions'


def from_config(config, provider=None, model=None):
    provider = (provider or config.get('ai_provider') or 'gemini').lower()
    key = (config.get(KEY_FIELDS.get(provider, provider + '_api_key'))
           or config.get(provider + '_api_key') or config.get(provider + '_key') or '')
    if not key and config.get('ai_provider') == provider:
        key = config.get('api_key', '')
    url = config.get(URL_FIELDS.get(provider, provider + '_base_url'), '')
    defaults = {'gemini': 'gemini-2.5-flash', 'gpt': 'gpt-4.1-mini', 'ollama': 'llama3.2'}
    return Connection(provider, model or config.get('ai_model') or defaults.get(provider, ''), key, url).validated()


def updated_config(config, connection):
    """Migrate legacy credentials to their provider before saving a new selection."""
    connection = connection.validated()
    result = dict(config)
    previous = result.get('ai_provider')
    legacy = result.pop('api_key', None)
    if legacy and previous in DEFAULT_URLS:
        result.setdefault(KEY_FIELDS.get(previous, previous + '_api_key'), legacy)
    provider = connection.provider
    result.update({'ai_provider': provider, 'ai_model': connection.model})
    result[KEY_FIELDS.get(provider, provider + '_api_key')] = connection.key
    result[URL_FIELDS.get(provider, provider + '_base_url')] = connection.base_url
    if provider == 'ollama':
        result['llm_model'] = connection.model
    return result
