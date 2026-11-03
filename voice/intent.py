"""Fruit-assistant intents: allowed commands, LLM prompt, strict validation and shortcuts.

The LLM only translates a sentence into {"command", "object", "reply"}; this module decides
whether that answer is allowed. Standard library only.
"""
import json
import re
from urllib import error, request

CLASSES = ('banana', 'pepper', 'potato', 'apple', 'battery')
FOOD = ('banana', 'pepper', 'potato', 'apple')
INTRUDERS = ('battery',)

COMMANDS = ('START_AUTO', 'SORT', 'REMOVE', 'PICK', 'COUNT', 'START_SINGLE', 'STATUS', 'STOP', 'NONE')
MOTIONS = frozenset({'START_AUTO', 'SORT', 'REMOVE', 'PICK', 'START_SINGLE'})

# Allowed `object` values per command; any command not listed only accepts null.
OBJECTS = {
    'SORT': FOOD,
    'PICK': FOOD,
    'REMOVE': INTRUDERS,
    'COUNT': CLASSES + (None,),
}

SYSTEM_PROMPT = (
    'You translate one user request for a fruit-sorting robot into JSON. '
    'Return ONLY a JSON object with exactly three keys: command, object, reply.\n'
    'Commands:\n'
    'START_AUTO: sort everything on the table, each item into its box. object=null.\n'
    'SORT: sort all items of ONE food class into its box. object=banana, pepper, potato or apple.\n'
    'REMOVE: remove the intruders into the waste bin. object=battery.\n'
    'PICK: hand ONE item of a food class to the user. object=banana, pepper, potato or apple.\n'
    'COUNT: ask how many items are on the table. object=one class, or null for everything.\n'
    'START_SINGLE: sort one item of any class. object=null.\n'
    'STATUS: ask about the robot state or what it is doing. object=null.\n'
    'STOP: stop the current task. object=null.\n'
    'NONE: anything else. object=null.\n'
    'Classes and synonyms: banana (香蕉); pepper (bell pepper, chili, 辣椒, 青椒, 甜椒); '
    'potato (土豆, 马铃薯); apple (苹果); battery (电池, intruder, anything that is not food).\n'
    'Rules: object must be exactly one of these class names or null. '
    'Asking to give, pick or sort a battery means REMOVE battery. '
    'Removing a food item is not allowed: use NONE. '
    'Use NONE for objects outside the five classes, more than one object, negations, '
    'unclear references such as "that one" or "it", and conversation.\n'
    'reply: one short sentence in the user\'s language. Never say an action is done. '
    'Never state a number of items: you cannot see the table.'
)

STOP_WORDS = {'停止', '停止分拣', 'stop', 'stopsorting', '暂停'}
STATUS_WORDS = {'状态', '查询状态', '当前状态', 'status', 'robotstatus'}


class IntentError(ValueError):
    """The LLM answer is not an allowed intent; nothing may be sent to the robot."""


def shortcut(text):
    """Exact stop/status phrases bypass the LLM; return an intent or None."""
    exact = re.sub(r'[\s,，.。!?！？]+', '', text.lower())
    if exact in STOP_WORDS:
        return dict(command='STOP', object=None, reply='软件停止 / Software stop')
    if exact in STATUS_WORDS:
        return dict(command='STATUS', object=None, reply='查询实际任务状态 / Query task state')
    return None


def parse_intent(content):
    """Strictly validate the LLM's raw text answer and return the intent dict."""
    if not isinstance(content, str):
        raise IntentError('answer is not text')
    content = re.sub(r'^```(?:json)?\s*|\s*```$', '', content.strip())
    try:
        intent = json.loads(content)
    except ValueError:
        raise IntentError('answer is not JSON') from None
    if not isinstance(intent, dict) or set(intent) != {'command', 'object', 'reply'}:
        raise IntentError('expected exactly the keys command, object, reply')
    command, obj, reply = intent['command'], intent['object'], intent['reply']
    if command not in COMMANDS:
        raise IntentError('unknown command: %r' % (command,))
    if obj not in OBJECTS.get(command, (None,)):
        raise IntentError('object %r not allowed for %s' % (obj, command))
    if not isinstance(reply, str) or not reply.strip() or len(reply) > 2000:
        raise IntentError('reply must be 1..2000 characters')
    return dict(command=command, object=obj, reply=reply)


def build_payload(text, model_id, thinking='disabled'):
    payload = dict(model=model_id, stream=False, max_tokens=512, temperature=0,
                   messages=[dict(role='system', content=SYSTEM_PROMPT), dict(role='user', content=text)])
    if thinking != 'auto':
        payload['thinking'] = dict(type=thinking)
    return payload


def ask_llm(text, cfg, timeout=45):
    """Send one OpenAI-compatible chat request and return the raw answer text."""
    url = cfg['ARK_BASE_URL'].rstrip('/') + '/chat/completions'
    body = json.dumps(build_payload(text, cfg['MODEL_ID'], cfg.get('LLM_THINKING', 'disabled')),
                      ensure_ascii=False).encode('utf-8')
    req = request.Request(url, data=body, headers={'Content-Type': 'application/json',
                                                  'Authorization': 'Bearer ' + cfg['ARK_API_KEY']})
    try:
        with request.urlopen(req, timeout=timeout) as response:
            result = json.loads(response.read(2 * 1024 * 1024))
        return result['choices'][0]['message']['content']
    except error.HTTPError as exc:
        # Provider error bodies can echo credentials; report the status code only.
        raise ConnectionError('HTTP %s: check key, model ID, permission and quota' % exc.code) from None
    except (error.URLError, OSError) as exc:
        raise ConnectionError('connection failed: %s' % exc) from None
    except (ValueError, KeyError, IndexError, TypeError):
        raise ConnectionError('the API did not return a chat completion') from None


def interpret(text, cfg):
    """Shortcut first, otherwise ask the LLM and validate its answer."""
    return shortcut(text) or parse_intent(ask_llm(text, cfg))
