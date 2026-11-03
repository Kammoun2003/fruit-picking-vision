"""Run the intent test set through the LLM and score it.

    python voice/evaluate.py --selftest          # offline: check the validator and shortcuts
    python voice/evaluate.py --env .env          # online: needs ARK_API_KEY and MODEL_ID

Writes results/intent_<model>_<timestamp>.csv (one row per sentence) and a .json summary.
"""
import argparse
import csv
from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path
import re
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from intent import MOTIONS, IntentError, interpret, parse_intent, shortcut  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


def load_env(path):
    """Minimal KEY=VALUE reader; the .env file is git-ignored and never printed."""
    cfg = dict(ARK_BASE_URL='https://ark.cn-beijing.volces.com/api/v3', LLM_THINKING='disabled')
    if not Path(path).is_file():
        raise SystemExit('Missing %s: create it with ARK_API_KEY=... and MODEL_ID=...' % path)
    for line in Path(path).read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            if value.strip():
                cfg[key.strip()] = value.strip()
    missing = [k for k in ('ARK_API_KEY', 'MODEL_ID') if not cfg.get(k)]
    if missing:
        raise SystemExit('Fill in %s in %s' % (', '.join(missing), path))
    if not cfg['ARK_BASE_URL'].startswith('https://'):
        raise SystemExit('ARK_BASE_URL must be an https:// URL')
    if cfg['LLM_THINKING'] not in ('auto', 'disabled', 'enabled'):
        raise SystemExit('LLM_THINKING must be auto, disabled or enabled')
    return cfg


def load_tests(path):
    rows = list(csv.DictReader(open(path, encoding='utf-8-sig')))
    for row in rows:
        row['expected_object'] = None if row['expected_object'] == 'null' else row['expected_object']
    return rows


def score(rows):
    """Command accuracy, exact match, unsafe errors and missed commands for a list of results."""
    n = len(rows)
    cmd = sum(r['predicted_command'] == r['expected_command'] for r in rows)
    exact = sum(r['predicted_command'] == r['expected_command'] and
                r['predicted_object'] == r['expected_object'] for r in rows)
    unsafe = sum(r['predicted_command'] in MOTIONS and r['expected_command'] not in MOTIONS for r in rows)
    missed = sum(r['expected_command'] != 'NONE' and r['predicted_command'] in ('NONE', 'INVALID') for r in rows)
    errors = sum(r['predicted_command'] == 'ERROR' for r in rows)
    # Latency only counts answered LLM calls; shortcuts never reach the model.
    times = [r['latency_s'] for r in rows if r.get('latency_s') is not None and r['predicted_command'] != 'ERROR']
    pct = lambda k: round(100 * k / n, 1) if n else 0.0
    return dict(n=n, command_acc=pct(cmd), exact_match=pct(exact), unsafe=unsafe, missed=missed, api_errors=errors,
                latency_median_s=round(statistics.median(times), 2) if times else None,
                latency_max_s=max(times) if times else None)


def run(args):
    cfg = load_env(args.env)
    if args.model:
        cfg['MODEL_ID'] = args.model
    tests = load_tests(args.tests)[:args.limit or None]
    results = []
    for i, row in enumerate(tests, 1):
        uses_llm = shortcut(row['sentence']) is None
        start = time.perf_counter()
        try:
            intent = interpret(row['sentence'], cfg)
            predicted, obj, reply = intent['command'], intent['object'], intent['reply']
        except IntentError as exc:
            predicted, obj, reply = 'INVALID', None, str(exc)
        except ConnectionError as exc:
            predicted, obj, reply = 'ERROR', None, str(exc)
        latency = round(time.perf_counter() - start, 2) if uses_llm else None
        ok = predicted == row['expected_command'] and obj == row['expected_object']
        print('%3s %s %-12s → %-12s %-8s %5s  %s' % (row['id'], 'ok ' if ok else 'XX ', row['expected_command'],
                                                     predicted, obj or '', '%.1fs' % latency if uses_llm else '-',
                                                     row['sentence']), flush=True)
        results.append(dict(row, predicted_command=predicted, predicted_object=obj, reply=reply, latency_s=latency))
        if predicted == 'ERROR' and i == 1:
            raise SystemExit('First request failed (%s); stopping before spending the whole test set.' % reply)
        time.sleep(args.delay)

    summary = dict(model=cfg['MODEL_ID'], tests=str(args.tests), time=datetime.now().isoformat(timespec='seconds'),
                   overall=score(results), by_language={}, by_group={})
    for key, table in (('language', summary['by_language']), ('group', summary['by_group'])):
        groups = defaultdict(list)
        for r in results:
            groups[r[key]].append(r)
        for name, items in sorted(groups.items()):
            table[name] = score(items)

    print('\nOverall:', json.dumps(summary['overall']))
    for title, table in (('Language', summary['by_language']), ('Group', summary['by_group'])):
        print('\n%-20s %4s %8s %8s %7s %7s %9s' % (title, 'n', 'command', 'exact', 'unsafe', 'missed', 'median s'))
        for name, s in table.items():
            median = '%.2f' % s['latency_median_s'] if s['latency_median_s'] is not None else '-'
            print('%-20s %4d %7.1f%% %7.1f%% %7d %7d %9s' % (name, s['n'], s['command_acc'], s['exact_match'],
                                                           s['unsafe'], s['missed'], median))

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stem = 'intent_%s_%s_%s' % (re.sub(r'[^A-Za-z0-9._-]+', '_', cfg['MODEL_ID']), Path(args.tests).stem,
                                datetime.now().strftime('%Y%m%d_%H%M%S'))
    fields = ['id', 'language', 'group', 'sentence', 'expected_command', 'expected_object',
              'predicted_command', 'predicted_object', 'reply', 'latency_s']
    with open(out / (stem + '.csv'), 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        for r in results:
            writer.writerow({k: ('null' if r[k] is None else r[k]) for k in fields})
    (out / (stem + '.json')).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print('\nSaved', out / (stem + '.csv'), 'and .json')


def selftest(tests_path):
    """Check the validator and shortcuts without any network call."""
    good = [
        ('{"command":"PICK","object":"banana","reply":"OK"}', 'PICK', 'banana'),
        ('```json\n{"command":"SORT","object":"potato","reply":"OK"}\n```', 'SORT', 'potato'),
        ('{"command":"REMOVE","object":"battery","reply":"OK"}', 'REMOVE', 'battery'),
        ('{"command":"COUNT","object":null,"reply":"Let me check."}', 'COUNT', None),
        ('{"command":"COUNT","object":"battery","reply":"Let me check."}', 'COUNT', 'battery'),
        ('{"command":"START_AUTO","object":null,"reply":"OK"}', 'START_AUTO', None),
        ('{"command":"NONE","object":null,"reply":"Hello!"}', 'NONE', None),
    ]
    bad = [
        ('{"command":"PICK","object":"battery","reply":"OK"}', 'battery is not handed over'),
        ('{"command":"REMOVE","object":"apple","reply":"OK"}', 'food cannot be removed'),
        ('{"command":"PICK","object":null,"reply":"OK"}', 'PICK needs an object'),
        ('{"command":"PICK","object":"orange","reply":"OK"}', 'unknown class'),
        ('{"command":"SORT","object":"Banana","reply":"OK"}', 'class names are exact'),
        ('{"command":"START_AUTO","object":"apple","reply":"OK"}', 'START_AUTO takes no object'),
        ('{"command":"FLY","object":null,"reply":"OK"}', 'unknown command'),
        ('{"command":"PICK","object":"apple"}', 'missing reply'),
        ('{"command":"PICK","object":"apple","reply":"OK","speed":9}', 'extra key'),
        ('{"command":"NONE","object":null,"reply":""}', 'empty reply'),
        ('Sure! I will pick the apple.', 'not JSON'),
        ('["PICK","apple"]', 'not an object'),
    ]
    failures = 0
    for text, command, obj in good:
        try:
            intent = parse_intent(text)
            assert (intent['command'], intent['object']) == (command, obj)
        except (IntentError, AssertionError) as exc:
            failures += 1
            print('FAIL accept:', text, '→', exc)
    for text, why in bad:
        try:
            parse_intent(text)
            failures += 1
            print('FAIL reject (%s): %s' % (why, text))
        except IntentError:
            pass
    shortcut_rows = 0
    for row in load_tests(tests_path):
        hit = shortcut(row['sentence'])
        if row['group'] == 'basic' and row['expected_command'] in ('STOP', 'STATUS'):
            shortcut_rows += 1
            if not hit or hit['command'] != row['expected_command']:
                failures += 1
                print('FAIL shortcut:', row['sentence'])
        elif hit:
            failures += 1
            print('FAIL shortcut should go to the LLM:', row['sentence'])
    total = len(good) + len(bad) + shortcut_rows
    print('Self-test: %d/%d passed (%d accept, %d reject, %d shortcut cases)'
          % (total - failures, total, len(good), len(bad), shortcut_rows))
    return 1 if failures else 0


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--tests', type=Path, default=REPO / 'tests' / 'intent_test_set.csv')
    p.add_argument('--env', type=Path, default=REPO / '.env', help='file with ARK_API_KEY, MODEL_ID, ARK_BASE_URL')
    p.add_argument('--out', type=Path, default=REPO / 'results')
    p.add_argument('--model', help='override MODEL_ID from the .env file, e.g. to compare models')
    p.add_argument('--limit', type=int, default=0, help='only the first N sentences (0 = all)')
    p.add_argument('--delay', type=float, default=0.5, help='seconds between requests')
    p.add_argument('--selftest', action='store_true', help='offline check of the validator and shortcuts')
    args = p.parse_args()
    if args.selftest:
        return selftest(args.tests)
    run(args)
    return 0


if __name__ == '__main__':
    sys.exit(main())
