# -*- coding: utf-8 -*-
"""Build _perf.json from the published release notes.

Each release's notes hold one side-by-side table against the release
before it. This reads each table named in STEPS from the live GitHub
release, keeps the rows every table shares, and writes each step's before
and after values (median and 95th percentile) exactly as published. Then
tools/build_perf.py draws the charts from _perf.json.

For a new release, append its step to STEPS with the method its notes
state, then run this and tools/build_perf.py. A missing row, a unit that
changes or a value that does not parse stops the run.

usage: python -I tools/perf_from_notes.py [<directory holding body-vX.Y.Z.md files>]
"""
import io, json, os, re, subprocess, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
REPO = "hifihedgehog/HIDMaestro"

METRICS = [
    ('start-ds4', 'Start and create', 'Process start to the first controller, DualShock 4'),
    ('create-ds4', 'Start and create', '`CreateController`, DualShock 4'),
    ('create-x360', 'Start and create', '`CreateController`, Xbox 360'),
    ('create-ds-usbip', 'Start and create', '`CreateController`, DualSense over USB/IP'),
    ('dispose-ds4', 'Removal', '`Dispose`, DualShock 4'),
    ('dispose-x360', 'Removal', '`Dispose`, Xbox 360'),
    ('dispose-ds-usbip', 'Removal', '`Dispose`, DualSense over USB/IP'),
    ('read-ds4', 'Input to the game', "`SubmitState` to a game's `ReadFile`, DualShock 4"),
    ('read-ds', 'Input to the game', "`SubmitState` to a game's `ReadFile`, DualSense"),
    ('read-ds3', 'Input to the game', "`SubmitState` to a game's `ReadFile`, DualShock 3"),
    ('read-ds-usbip', 'Input to the game', "`SubmitState` to a game's `ReadFile`, DualSense over USB/IP"),
    ('xinput-x360', 'Input to the game', '`SubmitState` to `XInputGetState`, Xbox 360'),
    ('output-ds4', 'Output and feature reports', 'Output report 0x05 to `OutputReceived`, DualShock 4'),
    ('feature-ds-usbip', 'Output and feature reports', '`GET_REPORT(Feature 0x05)`, DualSense over USB/IP'),
    ('submit-ds4', 'SubmitState, per call', '`SubmitState`, DualShock 4'),
    ('submit-x360', 'SubmitState, per call', '`SubmitState`, Xbox 360'),
    ('submit-ds3', 'SubmitState, per call', '`SubmitState`, DualShock 3'),
    ('submit-ds-bt', 'SubmitState, per call', '`SubmitState`, DualSense over Bluetooth (report 0x31)'),
    ('submit-ns2', 'SubmitState, per call', '`SubmitState`, Switch 2 Pro'),
    ('rate-x360', 'SubmitState, per call', '`SubmitState` back to back, Xbox 360'),
]

# (from, to, release tag, the method its notes state)
STEPS = [
    ('1.12.0', '2.0.0', 'v2.0.0', '30 runs per build, the two builds one after the other for each path'),
    ('2.0.0', '2.0.1', 'v2.0.1', '30 runs per build in each of two passes, with the order of the builds flipped between passes, three passes for start, create and Dispose, and six for the per-call rows'),
    ('2.0.1', '2.0.2', 'v2.0.2', '30 runs per build in each of two passes, with the order of the builds flipped between passes, three passes for start, create and Dispose, and eight rounds alternating the builds for the per-call rows'),
]
VALUE = re.compile(r'^\s*(?P<p50>[\d,]+(?:\.\d+)?)(?:\s*\((?P<p95>[\d,]+(?:\.\d+)?)\))?\s*$')


def body(tag):
    if len(sys.argv) > 1:
        return io.open(os.path.join(sys.argv[1], 'body-%s.md' % tag), encoding='utf-8').read()
    out = subprocess.run(['gh', 'release', 'view', tag, '--repo', REPO, '--json', 'body', '--jq', '.body'],
                         capture_output=True, text=True, encoding='utf-8', check=True)
    return out.stdout


def table(text, before, after):
    """label -> (unit, [b50, b95], [a50, a95]) from the table headed before | after."""
    lines = text.splitlines()
    head = next((i for i, l in enumerate(lines) if l.startswith('| Path | Unit | %s | %s' % (before, after))), None)
    if head is None:
        sys.exit('no %s -> %s table' % (before, after))

    def val(s):
        m = VALUE.match(s)
        if not m:
            return None
        f = lambda x: float(x.replace(',', '')) if x else None
        return [f(m.group('p50')), f(m.group('p95'))]
    out = {}
    for l in lines[head + 2:]:
        if not l.startswith('|'):
            break
        cells = [c.strip() for c in l.strip().strip('|').split('|')]
        out[cells[0]] = (cells[1], val(cells[2]), val(cells[3]))
    return out


tables = [table(body(tag), b, a) for b, a, tag, _ in STEPS]
metrics = []
for mid, group, label in METRICS:
    steps, unit = [], None
    for t in tables:
        if label not in t:
            sys.exit('%r missing from a table' % label)
        u, b, a = t[label]
        if unit and u != unit:
            sys.exit('%r changes unit: %s then %s' % (label, unit, u))
        if b is None or a is None:
            sys.exit('%r has a value that does not parse' % label)
        unit = u
        steps.append({'before': b, 'after': a})
    metrics.append({'id': mid, 'group': group, 'label': label, 'unit': unit,
                    'better': 'higher' if unit == 'frames a second' else 'lower', 'steps': steps})

data = {
    'about': "Release-over-release performance of HIDMaestro on the development laptop, a Lenovo Legion Pro 7 16AFR10H. "
             "Each step is the side-by-side comparison published in that release's notes, written by tools/perf_from_notes.py. "
             "tools/build_perf.py draws performance.html and the home and press sections from this file.",
    'releases': [STEPS[0][0]] + [s[1] for s in STEPS],
    'steps': [{'from': b, 'to': a, 'notes': 'https://github.com/%s/releases/tag/%s' % (REPO, tag), 'method': m}
              for b, a, tag, m in STEPS],
    'metrics': metrics,
}
io.open(os.path.join(ROOT, '_perf.json'), 'w', encoding='utf-8', newline='\n').write(
    json.dumps(data, indent=2, ensure_ascii=False) + '\n')
print('_perf.json: %d paths, %d steps' % (len(metrics), len(STEPS)))
