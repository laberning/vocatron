"""The static page of the blind listening test: seamless A/B switching of looped passages.

The page knows only trial numbers and clip ids, never systems, songs or models: the key stays in
``key.json`` beside it. It needs no server. Its own small player (Web Audio, no library) decodes
the lossless clips of a trial, starts the original and both versions at the same moment in a loop,
and switches between them by gains with a 5 ms ramp, so every button plays the same position. The
listener marks which version is better overall and, optionally, per criterion; the work is split
into sessions, kept in the browser between visits, and "Save results" downloads ``results.json``
in the layout of ``vocatron.lab.separation.listening.Results``.
"""

import json
from collections.abc import Sequence

from vocatron.lab.separation.listening import CRITERIA, Trial

CLIP_FOLDER = "clips"
CLIP_SUFFIX = ".flac"
RESULTS_NAME = "results.json"
RAMP_MS = 5
"""The fade between two buttons: short enough to be seamless, long enough not to click."""

_CRITERIA_TEXT = {
    "lead": "Leftovers of the lead voice",
    "artefacts": "Artefacts (watery sound, pumping)",
    "damage": "Instruments damaged or dull",
    "backing": "Backing vocals kept",
}

_STYLE = """
:root { color-scheme: light dark; --line: #8886; --accent: #2a6fdb; --done: #2a8a4a; }
body { font: 16px/1.5 system-ui, sans-serif; max-width: 48rem; margin: 0 auto; padding: 1rem; }
h1 { font-size: 1.4rem; }
nav { display: flex; gap: .5rem; flex-wrap: wrap; margin: 1rem 0; }
nav button.current { outline: 3px solid var(--accent); }
section { border: 1px solid var(--line); border-radius: 8px; padding: .75rem 1rem; margin: 1rem 0; }
section.done { border-color: var(--done); }
h2 { font-size: 1.05rem; margin: 0 0 .5rem; }
.switch { display: flex; gap: .5rem; flex-wrap: wrap; margin: .5rem 0; }
.switch button { min-width: 6rem; }
.switch button.on { background: var(--accent); color: white; }
.rate { display: flex; gap: 1rem; flex-wrap: wrap; margin: .5rem 0; }
.criteria { display: grid; grid-template-columns: 1fr auto; gap: .25rem .75rem; margin-top: .5rem; }
button { font: inherit; padding: .4rem .9rem; border-radius: 6px; border: 1px solid var(--accent);
  background: transparent; color: inherit; cursor: pointer; }
button.primary { background: var(--accent); color: white; }
.pos { font-variant-numeric: tabular-nums; margin-left: .5rem; }
#status { margin-left: 1rem; }
"""

_SCRIPT = """
const DATA = %(data)s;
const CRITERIA = %(criteria)s;
const RAMP = %(ramp)f;
const storage = 'vocatron-listening-%(build)s';
const judged = (() => { try { return JSON.parse(localStorage.getItem(storage)) || {}; }
  catch (e) { return {}; } })();
let context = null, player = null, session = 1;

function remember() {
  try { localStorage.setItem(storage, JSON.stringify(judged)); } catch (e) {}
}
function count(s) { return DATA.trials.filter(t => t.session === s && judged[t.id]).length; }
function total(s) { return DATA.trials.filter(t => t.session === s).length; }

async function load(trial) {
  context = context || new AudioContext();
  const names = ['a', 'b', 'o'];
  const buffers = await Promise.all(names.map(async n => {
    const response = await fetch(DATA.folder + '/' + trial[n] + DATA.suffix);
    return context.decodeAudioData(await response.arrayBuffer());
  }));
  return { trial, buffers, sources: null, gains: [], which: 0, offset: 0, started: 0 };
}
function position(p) {
  if (!p.sources) return p.offset;
  const length = p.buffers[0].duration;
  return (p.offset + context.currentTime - p.started) %% length;
}
function select(p, index) {
  p.which = index;
  if (!p.sources) return;
  const now = context.currentTime;
  p.gains.forEach((g, i) => {
    g.gain.cancelScheduledValues(now);
    g.gain.setValueAtTime(g.gain.value, now);
    g.gain.linearRampToValueAtTime(i === index ? 1 : 0, now + RAMP / 1000);
  });
}
function start(p) {
  const when = context.currentTime + 0.05;
  p.gains = p.buffers.map((b, i) => {
    const g = context.createGain();
    g.gain.value = i === p.which ? 1 : 0;
    g.connect(context.destination);
    return g;
  });
  p.sources = p.buffers.map((b, i) => {
    const s = context.createBufferSource();
    s.buffer = b; s.loop = true; s.connect(p.gains[i]);
    s.start(when, p.offset);
    return s;
  });
  p.started = when;
}
function stop(p) {
  if (!p || !p.sources) return;
  p.offset = position(p);
  p.sources.forEach(s => { try { s.stop(); } catch (e) {} });
  p.sources = null;
}

function card(trial, number, of) {
  const box = document.createElement('section');
  box.dataset.trial = trial.id;
  const criteria = CRITERIA.map(c => '<label>' + c.text +
    '</label><select data-criterion="' + c.id +
    '"><option value="">-</option><option value="A">A is better</option>' +
    '<option value="B">B is better</option><option value="same">same</option></select>').join('');
  box.innerHTML = '<h2>Judgement ' + number + ' of ' + of + '</h2>' +
    '<div><button class="primary" data-act="play">Play</button>' +
    '<span class="pos"></span></div>' +
    '<div class="switch"><button data-pick="0">A</button><button data-pick="1">B</button>' +
    '<button data-pick="2">Original song</button></div>' +
    '<div class="rate"><b>Better overall:</b>' +
    ['A', 'B', 'tie'].map(v => '<label><input type="radio" name="p-' + trial.id + '" value="' + v +
      '"> ' + (v === 'tie' ? "can't tell" : v) + '</label>').join('') + '</div>' +
    '<details><summary>Compare by criterion (optional)</summary><div class="criteria">' + criteria +
    '</div></details>';
  const old = judged[trial.id];
  if (old) {
    box.querySelector('input[value="' + old.preference + '"]').checked = true;
    Object.entries(old.criteria || {}).forEach(([c, v]) => {
      box.querySelector('[data-criterion="' + c + '"]').value = v; });
    box.classList.add('done');
  }
  const buttons = box.querySelectorAll('[data-pick]');
  const paint = i => buttons.forEach(b => b.classList.toggle('on', Number(b.dataset.pick) === i));
  paint(0);
  box.querySelector('[data-act=play]').addEventListener('click', async ev => {
    const button = ev.currentTarget;
    if (player && player.trial.id === trial.id && player.sources) {
      stop(player); button.textContent = 'Play'; return;
    }
    document.querySelectorAll('[data-act=play]').forEach(b => { b.textContent = 'Play'; });
    stop(player);
    button.textContent = 'Loading...';
    if (!player || player.trial.id !== trial.id) {
      player = await load(trial); player.which = Number(box.dataset.which || 0);
    }
    await context.resume();
    start(player); paint(player.which); button.textContent = 'Stop';
  });
  buttons.forEach(b => b.addEventListener('click', () => {
    const i = Number(b.dataset.pick);
    paint(i);
    box.dataset.which = i;
    if (player && player.trial.id === trial.id) select(player, i);
  }));
  const read = () => {
    const checked = box.querySelector('input[type=radio]:checked');
    if (!checked) return;
    const criteria = {};
    box.querySelectorAll('[data-criterion]').forEach(s => {
      if (s.value) criteria[s.dataset.criterion] = s.value;
    });
    judged[trial.id] = { trial: trial.id, preference: checked.value, criteria };
    box.classList.add('done'); remember(); refresh();
  };
  box.addEventListener('change', read);
  return box;
}
function show(s) {
  session = s;
  stop(player); player = null;
  const holder = document.getElementById('trials');
  holder.replaceChildren();
  const list = DATA.trials.filter(t => t.session === s);
  list.forEach((t, i) => holder.appendChild(card(t, i + 1, list.length)));
  refresh();
}
function refresh() {
  document.querySelectorAll('nav button').forEach(b => {
    const s = Number(b.dataset.session);
    b.textContent = 'Session ' + s + ' (' + count(s) + ' of ' + total(s) + ')';
    b.classList.toggle('current', s === session);
  });
}
function save() {
  const all = Object.values(judged);
  const text = JSON.stringify({ judgements: all }, null, 2);
  const blob = new Blob([text], { type: 'application/json' });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = '%(results)s';
  link.click();
  document.getElementById('status').textContent =
    all.length + ' of ' + DATA.trials.length + ' judged; saved as %(results)s.';
}
const nav = document.querySelector('nav');
for (let s = 1; s <= DATA.sessions; s++) {
  const b = document.createElement('button');
  b.dataset.session = s;
  b.addEventListener('click', () => show(s));
  nav.appendChild(b);
}
document.getElementById('save').addEventListener('click', save);
setInterval(() => {
  if (!player || !player.sources) return;
  const shown = document.querySelector('[data-trial="' + player.trial.id + '"] .pos');
  if (shown) shown.textContent = position(player).toFixed(1) + ' s';
}, 200);
show(1);
"""


def clip_path(clip: str) -> str:
    """Return where the clip with id ``clip`` lies, relative to the page."""
    return f"{CLIP_FOLDER}/{clip}{CLIP_SUFFIX}"


def render_page(trials: Sequence[Trial], sessions: int, build: str) -> str:
    """Return the listening page for ``trials``.

    The page shows no song names, passages, systems or models: only the judgement number and the
    buttons A, B and Original.

    Args:
        trials: The trials in page order.
        sessions: How many sessions they are split into.
        build: An id of this build (hex digits). The browser keeps unsaved judgements under it,
            so the judgements of an earlier build, whose clip ids may hide other systems, never
            return.
    """
    data = {
        "folder": CLIP_FOLDER,
        "suffix": CLIP_SUFFIX,
        "sessions": sessions,
        "trials": [
            {"id": t.id, "session": t.session, "a": t.a, "b": t.b, "o": t.original} for t in trials
        ],
    }
    criteria = [{"id": name, "text": _CRITERIA_TEXT[name]} for name in CRITERIA]
    script = _SCRIPT % {
        "data": json.dumps(data, separators=(",", ":")),
        "criteria": json.dumps(criteria, separators=(",", ":")),
        "ramp": float(RAMP_MS),
        "build": build,
        "results": RESULTS_NAME,
    }
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>Listening test</title>\n"
        f"<style>{_STYLE}</style></head><body>\n"
        "<h1>Listening test</h1>\n"
        "<p>Use headphones and a comfortable, fixed volume. Each judgement plays a short passage "
        "in a loop. <b>A</b> and <b>B</b> are two versions of the karaoke track, the "
        "<b>Original song</b> is what should be there. Switch between the buttons while it plays: "
        "they stay at the same position. Listen for leftovers of the lead voice, artefacts "
        "(watery sound, pumping), music that sounds dull or damaged, and whether the backing "
        "vocals are kept. Say which version is better overall, or that you cannot tell. "
        "Your answers stay in this browser; save the results after each session.</p>\n"
        "<nav></nav>\n"
        '<div id="trials"></div>\n'
        '<p><button id="save" type="button" class="primary">Save results</button>'
        '<span id="status" role="status"></span></p>\n'
        f"<script>{script}</script>\n"
        "</body></html>\n"
    )
