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
    'COUNT: ask how many items are on the table. object=one class, or null for everything '
    'or for several classes at once.\n'
    'START_SINGLE: sort one item of any class, e.g. "pick one object", "抓取一个", "分拣一个". object=null. '
    'Only when the user clearly asks to pick or sort one object; vague requests such as "take something" '
    'or "do something" are NONE.\n'
    'STATUS: ask about the robot state or what it is doing. object=null.\n'
    'STOP: stop the current task. object=null.\n'
    'NONE: anything else. object=null.\n'
    'Classes and synonyms: banana (香蕉); pepper (bell pepper, chili, 辣椒, 青椒, 甜椒); '
    'potato (土豆, 马铃薯); apple (苹果); battery (电池, intruder, anything that is not food).\n'
    'Rules: object must be exactly one of these class names or null. '
    'Asking to give, pick or sort a battery means REMOVE battery. '
    'Removing a food item is not allowed: use NONE. '
    'Use NONE for objects outside the five classes, more than one object (except COUNT), negations, '
    'unclear references such as "that one" or "it", and conversation.\n'
    'reply: one short sentence in the same language as the request (English request: English reply; '
    'Chinese request: Chinese reply). Never say an action is done. '
    'Never state a number of items: you cannot see the table.'
)

CJK = re.compile(r'[㐀-鿿]')
ZH_NAMES = {'banana': '香蕉', 'pepper': '甜椒', 'potato': '土豆', 'apple': '苹果', 'battery': '电池'}
# Fallback replies when the model answers in the wrong language. They follow the reply rules:
# no claim that an action is done, no number of items.
FALLBACK_REPLIES = {
    'START_AUTO': ('OK, I will sort everything on the table.', '好的，我来分拣桌上的所有物品。'),
    'SORT': ('OK, I will sort the {en} into their box.', '好的，我来把{zh}分拣到对应的盒子里。'),
    'REMOVE': ('OK, I will remove the {en}.', '好的，我来把{zh}清除掉。'),
    'PICK': ('OK, I will hand you the {en}.', '好的，我来把{zh}递给你。'),
    'COUNT': ('Let me check the table.', '我来看一下桌上的情况。'),
    'START_SINGLE': ('OK, I will sort one object.', '好的，我来分拣一个物品。'),
    'STATUS': ('Let me check the robot status.', '我来查询一下机器人的状态。'),
    'STOP': ('Stopping the current task.', '正在停止当前任务。'),
    'NONE': ('Sorry, I can only sort, hand over, remove or count the items on the table.',
             '抱歉，我只能分拣、递送、清除或清点桌上的物品。'),
}

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


def wrong_language(request_text, reply):
    """True when a Chinese request gets a reply without Chinese, or a non-Chinese request gets one with it."""
    return bool(CJK.search(request_text)) != bool(CJK.search(reply))


def match_language(request_text, intent):
    """Replace a reply written in the wrong language by a fixed reply in the request's language.
    The command and object are never changed."""
    if not wrong_language(request_text, intent['reply']):
        return intent
    english, chinese = FALLBACK_REPLIES[intent['command']]
    obj = intent['object'] or ''
    template = chinese if CJK.search(request_text) else english
    return dict(intent, reply=template.format(en=obj, zh=ZH_NAMES.get(obj, obj)))


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
    """Shortcut first, otherwise ask the LLM, validate its answer and fix the reply language."""
    return shortcut(text) or match_language(text, parse_intent(ask_llm(text, cfg)))
