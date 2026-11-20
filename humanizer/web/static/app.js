// Humanizer web client. No framework: the page is one editor, one report, one rewrite.

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const store = {
  get(k, d) { try { const v = localStorage.getItem("hz." + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("hz." + k, JSON.stringify(v)); } catch {} },
};
// Where the API lives. Same origin locally; on Vercel, config.js points at the FastAPI Cloud URL.
const LOCAL = /^(localhost|127\.0\.0\.1|\[::1\])$/.test(location.hostname);
const API = (LOCAL ? "" : (window.HUMANIZER_API || "")).replace(/\/$/, "");
const headers = () => {
  const h = { "Content-Type": "application/json" };
  const code = store.get("code", "");
  if (code) h["X-Access-Code"] = code;
  return h;
};
const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

const MODES = [
  { group: "Research and school", items: [
    ["essay", "Essay", "Argumentative, analytical, or reflective. Thesis and evidence stay put."],
    ["academic", "Research paper", "Formal register, discipline terms, honest hedges."],
    ["abstract", "Abstract", "Background, method, results, conclusion. Same length."],
    ["review", "Literature review", "Every attribution kept; sources connected in plain sentences."],
    ["proposal", "Grant proposal", "Problem and aims first. Confident, never salesy."],
  ]},
  { group: "Everyday writing", items: [
    ["auto", "Auto-detect", "Reads the draft and matches its register."],
    ["personal", "Blog or personal essay", "Keeps your opinions, doubts, and asides."],
    ["social", "Social post", "LinkedIn, X, Threads. No hooks or bait."],
    ["business", "Email or memo", "Point first. Direct and warm."],
    ["technical", "Technical writing", "Neutral, plain, precise."],
    ["marketing", "Marketing copy", "Persuades with facts, not hype."],
    ["casual", "Casual message", "Short and spoken."],
  ]},
];
const ACADEMIC = new Set(["essay", "academic", "abstract", "review", "proposal"]);
const MODE_LABEL = Object.fromEntries(MODES.flatMap((g) => g.items.map(([k, l]) => [k, l])));
const STAGES = ["scan", "rewrite", "check", "revise"];

const SAMPLES = {
  essay: { mode: "essay", text: `In today's rapidly evolving digital landscape, social media plays a pivotal role in shaping how teenagers perceive themselves. It's not just a platform for communication; it's a mirror that reflects and distorts identity. This essay will delve into the intricate interplay between online validation and adolescent self-esteem.

Research shows that heavy users are more likely to report symptoms of anxiety. A 2019 study by Riehm et al. found that adolescents who spent more than three hours per day on social media faced a heightened risk of internalizing problems (Riehm et al., 2019). Furthermore, Twenge (2017) argues that the arrival of the smartphone marked a pivotal moment in the mental health of an entire generation. These findings underscore the importance of understanding this multifaceted issue.

However, it is important to note that social media is not inherently harmful. It can foster a sense of community, provide support, and elevate marginalized voices. The real question is not whether teenagers should use social media, but how they can navigate the digital realm in a healthy way.

Ultimately, the relationship between social media and self-esteem is a complex tapestry woven from both positive and negative threads. Let that sink in.` },
  abstract: { mode: "abstract", text: `Background: Sleep deprivation is a pivotal yet often overlooked factor in academic performance among university students, and it plays a crucial role in cognitive functioning. Aim: This study seeks to address a critical gap in the literature by examining the intricate relationship between sleep duration and examination outcomes. Methods: We conducted a prospective cohort study of undergraduate students (N = 412) across three faculties, measuring sleep with wrist actigraphy over a 14-day examination period. Results: Students who averaged fewer than six hours of sleep scored significantly lower on final examinations than those who slept seven hours or more (mean difference 8.4 points, 95% CI [5.1, 11.7], p < .001). Notably, the association remained robust after adjusting for prior GPA, caffeine intake, and course load. Conclusion: These findings underscore the paramount importance of sleep hygiene and hold the potential to make a meaningful impact on student wellbeing policies, setting the stage for future interventions.` },
  review: { mode: "review", text: `The landscape of remote work research has evolved significantly over the past decade. Bloom et al. (2015) conducted a landmark randomized experiment at a Chinese travel agency, finding that home-based workers were 13% more productive. Moreover, this study stands as a testament to the potential of flexible work arrangements. Furthermore, Choudhury et al. (2021) extended this line of inquiry by examining "work-from-anywhere" policies at the United States Patent and Trademark Office, reporting a 4.4% increase in output.

However, not all scholars agree. Experts argue that remote work may erode collaboration and innovation. Yang et al. (2022) analyzed communication data from 61,182 Microsoft employees and found that firm-wide remote work caused collaboration networks to become more static and siloed. Additionally, Gibbs et al. (2023) observed that productivity declined by 8% to 19% among IT professionals in India after the shift to working from home.

Taken together, these studies paint a nuanced and multifaceted picture. It is worth noting that the effects of remote work appear to depend on task type, measurement approach, and organizational context (Bloom et al., 2015; Gibbs et al., 2023). This underscores the need for further research in this ever-evolving field.` },
  social: { mode: "social", text: `I'm thrilled to share that I've officially defended my PhD! 🎓

5 years. 3 papers. 1 dissertation.

Here's the thing: it wasn't just about the research. It was about resilience, growth, and learning to embrace failure.

The best part? I got to work with an incredible, dynamic team who supported me every step of the way.

To anyone on this journey: don't give up. Your breakthrough is closer than you think. ✨

Let that sink in.

#PhD #Research #Growth #Grateful` },
};

// ------------------------------------------------------------------------------------------------------------
const S = {
  mode: store.get("mode", "auto"),
  intensity: store.get("intensity", "balanced"),
  dialect: store.get("dialect", "auto"),
  cites: store.get("cites", true),
  keepLength: store.get("keepLength", null),   // null = follow the mode
  terms: store.get("terms", []),
  voice: store.get("voice", ""),
  scan: null,
  result: null,
  acc: [],
  view: "clean",
  busy: false,
  abort: null,
  hasKey: true,
};

const el = {
  app: $("#app"), draft: $("#draft"), backdrop: $("#backdrop"), run: $("#runBtn"), tip: $("#tip"), chgTip: $("#chgTip"),
  output: $("#output"), toast: $("#toast"),
};

// ---------- theme ----------
$("#themeBtn").addEventListener("click", () => {
  const cur = document.documentElement.dataset.theme
    || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  const next = cur === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("hz.theme", next); } catch {}
});

// ---------- toast ----------
let toastT;
function toast(msg, err = false) {
  el.toast.textContent = msg;
  el.toast.classList.toggle("err", err);
  el.toast.classList.add("show");
  clearTimeout(toastT);
  toastT = setTimeout(() => el.toast.classList.remove("show"), err ? 5200 : 2200);
}

// ---------- popovers ----------
function closePops(except) {
  $$(".pop").forEach((p) => { if (p !== except) p.hidden = true; });
  $$("[aria-expanded]").forEach((b) => { if (!except || b.nextElementSibling !== except) b.setAttribute("aria-expanded", "false"); });
}
function togglePop(btn, pop) {
  const open = pop.hidden;
  closePops(open ? pop : null);
  pop.hidden = !open;
  btn.setAttribute("aria-expanded", String(open));
}
document.addEventListener("click", (e) => {
  if (!e.target.closest(".ctl")) closePops();
  if (!e.target.closest("#chgTip") && !e.target.closest(".chg")) hideChgTip();
  if (!e.target.closest("#tip") && e.target !== el.draft) el.tip.hidden = true;
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { closePops(); el.tip.hidden = true; hideChgTip(); closeDrawers(); }
  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") { e.preventDefault(); if (!S.busy) run(); }
});

// ---------- mode ----------
const modePop = $("#modePop");
modePop.innerHTML = MODES.map((g) => `<div class="mode-group"><h4>${g.group}</h4>${g.items.map(([k, l, d]) =>
  `<button class="mode-opt" role="option" data-mode="${k}"><b>${l}</b><small>${d}</small></button>`).join("")}</div>`).join("");
$("#modeBtn").addEventListener("click", () => togglePop($("#modeBtn"), modePop));
modePop.addEventListener("click", (e) => {
  const b = e.target.closest(".mode-opt"); if (!b) return;
  setMode(b.dataset.mode); closePops();
});
function setMode(m) {
  S.mode = m; store.set("mode", m);
  $("#modeLabel").textContent = MODE_LABEL[m];
  $$(".mode-opt").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.mode === m)));
  syncLength();
}

// ---------- segmented controls ----------
function seg(root, value, onChange) {
  const set = (v) => $$("button", root).forEach((b) => b.setAttribute("aria-checked", String(b.dataset.v === v)));
  set(value);
  root.addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; set(b.dataset.v); onChange(b.dataset.v); });
}
seg($("#intensity"), S.intensity, (v) => { S.intensity = v; store.set("intensity", v); });
seg($("#dialect"), S.dialect, (v) => { S.dialect = v; store.set("dialect", v); syncOptsLabel(); });
seg($("#viewMode"), S.view, (v) => { S.view = v; renderOutput(); });

// ---------- safeguards ----------
$("#optsBtn").addEventListener("click", () => togglePop($("#optsBtn"), $("#optsPop")));
const optCites = $("#optCites"), optLength = $("#optLength");
optCites.checked = S.cites;
optCites.addEventListener("change", () => { S.cites = optCites.checked; store.set("cites", S.cites); syncOptsLabel(); paintBackdrop(); });
optLength.addEventListener("change", () => { S.keepLength = optLength.checked; store.set("keepLength", S.keepLength); syncOptsLabel(); });
function keepLength() { return S.keepLength == null ? ACADEMIC.has(S.mode) : S.keepLength; }
function syncLength() { optLength.checked = keepLength(); syncOptsLabel(); }
function syncOptsLabel() {
  const parts = [S.cites ? "Citations locked" : "Citations free"];
  if (S.terms.length) parts.push(`${S.terms.length} term${S.terms.length > 1 ? "s" : ""}`);
  $("#optsLabel").textContent = parts.join(" · ");
  $("#optsBtn").classList.toggle("on", S.cites || S.terms.length > 0);
}
const termsBox = $("#terms"), termInput = $("#termInput");
function renderTerms() {
  $$(".chip", termsBox).forEach((c) => c.remove());
  S.terms.forEach((t, i) => {
    const c = document.createElement("span");
    c.className = "chip";
    c.innerHTML = `${esc(t)}<button aria-label="Remove ${esc(t)}" data-i="${i}">×</button>`;
    termsBox.insertBefore(c, termInput);
  });
  syncOptsLabel();
}
termInput.addEventListener("keydown", (e) => {
  if ((e.key === "Enter" || e.key === ",") && termInput.value.trim()) {
    e.preventDefault();
    termInput.value.split(",").map((s) => s.trim()).filter(Boolean).forEach((t) => { if (!S.terms.includes(t)) S.terms.push(t); });
    termInput.value = ""; store.set("terms", S.terms); renderTerms();
  } else if (e.key === "Backspace" && !termInput.value && S.terms.length) {
    S.terms.pop(); store.set("terms", S.terms); renderTerms();
  }
});
termsBox.addEventListener("click", (e) => {
  const b = e.target.closest("button[data-i]");
  if (b) { S.terms.splice(+b.dataset.i, 1); store.set("terms", S.terms); renderTerms(); }
  else termInput.focus();
});

// ---------- drawers ----------
function openDrawer(d) { closePops(); d.hidden = false; $("#scrim").hidden = false; }
function closeDrawers() { $$(".drawer").forEach((d) => (d.hidden = true)); $("#scrim").hidden = true; }
$("#scrim").addEventListener("click", closeDrawers);
$$("[data-close]").forEach((b) => b.addEventListener("click", closeDrawers));

// voice
const voiceSample = $("#voiceSample");
voiceSample.value = S.voice;
$("#voiceBtn").addEventListener("click", () => { openDrawer($("#voiceDrawer")); voiceSample.focus(); });
const readVoice = debounce(async () => {
  const words = S.voice.trim().split(/\s+/).filter(Boolean).length;
  const box = $("#voiceRead");
  syncVoiceLabel(words);
  if (words < 60) {
    box.innerHTML = words ? `<div class="note">${words} words so far. Add at least ${150 - words} more for a reliable read.</div>` : "";
    return;
  }
  const r = await api("/api/profile", { sample: S.voice }).catch(() => null);
  if (!r) return;
  const p = r.profile;
  box.innerHTML = `
    <div class="stat"><div class="v">${p.mean_sentence_len}</div><div class="k">words per sentence</div></div>
    <div class="stat"><div class="v">${p.contractions_per_1k}</div><div class="k">contractions per 1k</div></div>
    <div class="stat"><div class="v">${p.dashes_per_1k}</div><div class="k">dashes per 1k</div></div>
    <div class="note">${words} words read.${words < 150 ? " More text gives a closer match." : ""}
      ${p.common_openers.length ? `You often start with “${p.common_openers.slice(0, 3).join("”, “")}”.` : ""}</div>`;
}, 350);
function syncVoiceLabel(words = S.voice.trim().split(/\s+/).filter(Boolean).length) {
  const on = words >= 60;
  $("#voiceLabel").textContent = on ? "Your voice" : "Neutral";
  $("#voiceBtn").classList.toggle("on", on);
}
voiceSample.addEventListener("input", () => { S.voice = voiceSample.value; store.set("voice", S.voice); readVoice(); });
$("#voiceClear").addEventListener("click", () => { voiceSample.value = ""; S.voice = ""; store.set("voice", ""); readVoice(); });

// history
$("#historyBtn").addEventListener("click", () => { renderHistory(); openDrawer($("#historyDrawer")); });
function renderHistory() {
  const h = store.get("history", []);
  const list = $("#historyList");
  if (!h.length) { list.innerHTML = `<li class="h-empty">Nothing yet. Your rewrites will appear here.</li>`; return; }
  list.innerHTML = h.map((x, i) => `<li><button data-i="${i}">
    <span class="h-meta"><span>${new Date(x.at).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</span>
    <span>·</span><span>${esc(MODE_LABEL[x.mode] || x.mode)}</span><span>·</span><span>${x.result.before.score} → ${x.result.after.score}</span></span>
    <span class="h-text">${esc(x.text.slice(0, 220))}</span></button></li>`).join("");
}
$("#historyList").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-i]"); if (!b) return;
  const x = store.get("history", [])[+b.dataset.i]; if (!x) return;
  el.draft.value = x.text; setMode(x.mode); onInput(true);
  showResult(x.result);
  closeDrawers();
});
function saveHistory(text, result) {
  const h = store.get("history", []);
  h.unshift({ at: Date.now(), mode: S.mode, text, result });
  while (h.length) { try { localStorage.setItem("hz.history", JSON.stringify(h.slice(0, 12))); break; } catch { h.pop(); } }
}

// ---------- API ----------
async function api(path, body) {
  const r = await fetch(API + path, { method: "POST", headers: headers(), body: JSON.stringify(body) });
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}

// ---------- draft + scan ----------
function words(t) { return (t.match(/[A-Za-z0-9][A-Za-z0-9'’-]*/g) || []).length; }
function sentenceLengths(t) {
  const out = [];
  t.split(/\n\s*\n/).forEach((p) => {
    p = p.trim(); if (!p) return;
    p.split(/(?<=[.!?])["')\]]*\s+(?=["'(\[]?[A-Z0-9])/).forEach((s) => { const n = (s.match(/[A-Za-z][A-Za-z'-]*/g) || []).length; if (n) out.push(n); });
  });
  return out;
}

const scanNow = debounce(async () => {
  const text = el.draft.value;
  if (!text.trim()) { S.scan = null; renderReport(); paintBackdrop(); return; }
  try {
    const r = await api("/api/scan", { text });
    if (el.draft.value !== text) return;
    S.scan = r; renderReport(); paintBackdrop();
  } catch (e) { /* the server may be restarting; try again on next keystroke */ }
}, 220);

function onInput(immediate) {
  const t = el.draft.value;
  const n = words(t);
  el.app.dataset.state = t.trim() ? (S.result ? "done" : "draft") : "empty";
  $("#wc").textContent = `${n.toLocaleString()} word${n === 1 ? "" : "s"}`;
  $("#rt").textContent = `${Math.max(1, Math.round(n / 230))} min read`;
  $("#samples").hidden = !!t.trim();
  $("#clearBtn").hidden = !t.trim();
  $("#legend").hidden = !t.trim();
  el.run.disabled = !t.trim() || S.busy;
  el.tip.hidden = true;
  paintBackdrop();   // keep highlights aligned while typing, with stale offsets clipped to text
  if (immediate === true) { scanNow(); } else scanNow();
}
el.draft.addEventListener("input", onInput);
el.draft.addEventListener("scroll", () => { el.backdrop.scrollTop = el.draft.scrollTop; el.tip.hidden = true; });
$("#clearBtn").addEventListener("click", () => { el.draft.value = ""; clearResult(); onInput(); el.draft.focus(); });
$("#samples").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-sample]"); if (!b) return;
  const s = SAMPLES[b.dataset.sample];
  el.draft.value = s.text; setMode(s.mode); clearResult(); onInput(); el.draft.focus(); el.draft.setSelectionRange(0, 0);
});

function spans() {
  if (!S.scan) return [];
  const text = el.draft.value;
  const list = S.scan.hits.map((h, i) => ({ s: h.start, e: h.end, cls: "s" + h.strength, i, str: h.strength }));
  if (S.cites) S.scan.marks.forEach((m) => list.push({ s: m.start, e: m.end, cls: "cite", str: 0 }));
  list.sort((a, b) => a.s - b.s || b.str - a.str);
  const out = []; let end = -1;
  for (const x of list) { if (x.s >= end && x.e <= text.length && x.e > x.s) { out.push(x); end = x.e; } }
  return out;
}
function paintBackdrop() {
  const text = el.draft.value;
  let html = "", pos = 0;
  for (const x of spans()) {
    html += esc(text.slice(pos, x.s)) + `<mark class="${x.cls}"${x.i != null ? ` data-i="${x.i}"` : ""}>${esc(text.slice(x.s, x.e))}</mark>`;
    pos = x.e;
  }
  html += esc(text.slice(pos)) + "\n​";
  el.backdrop.innerHTML = html;
  el.backdrop.scrollTop = el.draft.scrollTop;
}

// click a highlighted phrase in the draft to see why it was flagged
el.draft.addEventListener("click", () => {
  if (!S.scan || el.draft.selectionStart !== el.draft.selectionEnd) return;
  const p = el.draft.selectionStart;
  const hit = S.scan.hits.map((h, i) => ({ ...h, i })).filter((h) => p >= h.start && p <= h.end).sort((a, b) => b.strength - a.strength)[0];
  if (!hit) { el.tip.hidden = true; return; }
  showTellTip(hit.i);
});
function showTellTip(i) {
  const h = S.scan.hits[i];
  const m = $(`mark[data-i="${i}"]`, el.backdrop);
  if (!m) return;
  const color = { 3: "var(--red)", 2: "var(--amber)", 1: "var(--weak)" }[h.strength];
  el.tip.innerHTML = `<div class="t-name"><i style="background:${color}"></i>${esc(h.name)}</div><div class="t-adv">${esc(h.advice)}</div>`;
  el.tip.hidden = false;
  const wrap = $("#editorWrap").getBoundingClientRect(), r = m.getBoundingClientRect();
  const left = Math.min(Math.max(12, r.left - wrap.left), wrap.width - 312);
  let top = r.bottom - wrap.top + 8;
  if (top + el.tip.offsetHeight > wrap.height - 8) top = r.top - wrap.top - el.tip.offsetHeight - 8;
  el.tip.style.left = left + "px"; el.tip.style.top = top + "px";
}
function jumpTo(i) {
  const h = S.scan.hits[i];
  showPane("left");
  const m = $(`mark[data-i="${i}"]`, el.backdrop);
  if (m) {
    el.draft.scrollTop = Math.max(0, m.offsetTop - el.draft.clientHeight / 3);
    el.backdrop.scrollTop = el.draft.scrollTop;
    m.classList.remove("focus"); void m.offsetWidth; m.classList.add("focus");
  }
  el.draft.focus({ preventScroll: true });
  el.draft.setSelectionRange(h.start, h.end);
  setTimeout(() => showTellTip(i), 60);
}

// ---------- report ----------
function verdict(score) {
  if (score < 15) return "Reads human";
  if (score < 40) return "Some machine habits";
  if (score < 70) return "Reads machine-made";
  return "Unmistakably machine-made";
}
function statHTML(v, k, cls = "", was = null) {
  return `<div class="stat"><div class="v ${cls}">${was != null ? `<span class="was">${was}</span><span class="arrow">→</span>` : ""}${v}</div><div class="k">${k}</div></div>`;
}
function renderReport() {
  const r = S.scan;
  $("#reportEmpty").hidden = !!r;
  $("#report").hidden = !r;
  $("#citeCount").textContent = r && r.marks.length ? `${r.marks.length} citation${r.marks.length > 1 ? "s" : ""} and figures ${S.cites ? "locked" : "found"}` : "";
  if (!r) return;
  const st = r.stats;
  animateNum($("#scoreNum"), Math.round(r.score));
  $("#scoreVerdict").textContent = verdict(r.score);
  $("#scaleFill").style.left = Math.min(100, r.score) + "%";
  const total = r.hits.length;
  $("#statGrid").innerHTML =
    statHTML(total, `tells${r.counts.strong ? `, ${r.counts.strong} strong` : ""}`, r.counts.strong ? "bad" : "") +
    statHTML(st.sentence_len_cv, "rhythm spread", st.sentences >= 6 && st.sentence_len_cv < .25 ? "bad" : "") +
    statHTML(st.mean_sentence_len, "words per sentence") +
    statHTML(st.dashes_per_1k, "dashes per 1k words", st.dashes_per_1k >= 5 ? "bad" : "");

  const lens = sentenceLengths(el.draft.value);
  const max = Math.max(...lens, 1);
  const rh = $("#rhythm");
  rh.classList.toggle("flat", st.sentences >= 6 && st.sentence_len_cv < .25);
  rh.innerHTML = lens.slice(0, 160).map((n, i) => `<i style="height:${Math.max(6, (n / max) * 100)}%" title="Sentence ${i + 1}: ${n} words"></i>`).join("");
  $("#rhythmHint").textContent = lens.length < 4 ? "needs a few sentences"
    : st.sentence_len_cv < .25 ? "flat: sentences are all one length" : st.sentence_len_cv < .4 ? "a little even" : "varied, like a person";

  const groups = {};
  r.hits.forEach((h, i) => { (groups[h.rule] ||= { name: h.name, strength: h.strength, advice: h.advice, hits: [] }).hits.push({ ...h, i }); });
  const gs = Object.values(groups).sort((a, b) => b.strength - a.strength || b.hits.length - a.hits.length);
  $("#tellHint").textContent = gs.length ? `${gs.length} kind${gs.length > 1 ? "s" : ""} · click one to find it` : "";
  $("#tells").innerHTML = gs.length ? gs.map((g, gi) => `
    <div class="tell-group${gi === 0 ? " open" : ""}">
      <button><span class="sw s${g.strength}"></span><b>${esc(g.name)}</b><span class="n">${g.hits.length}</span>
        <svg viewBox="0 0 12 12"><path d="m3 4.5 3 3 3-3" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg></button>
      <div class="tell-body"><p class="tell-adv">${esc(g.advice)}</p>
        ${g.hits.slice(0, 12).map((h) => `<button class="tell-hit" data-i="${h.i}">“${esc(h.text.length > 120 ? h.text.slice(0, 117) + "…" : h.text)}”</button>`).join("")}
        ${g.hits.length > 12 ? `<p class="tell-adv">and ${g.hits.length - 12} more</p>` : ""}
      </div>
    </div>`).join("") : `<p class="no-tells">No tells found. This already reads like a person wrote it.</p>`;

  $("#marksBlock").hidden = !r.marks.length;
  $("#marks").innerHTML = r.marks.slice(0, 60).map((m) => `<span class="mark-chip"><span class="mk">${m.kind.replace("-", " ")}</span>${esc(m.text)}</span>`).join("");
}
$("#tells").addEventListener("click", (e) => {
  const hit = e.target.closest(".tell-hit");
  if (hit) return jumpTo(+hit.dataset.i);
  const g = e.target.closest(".tell-group > button");
  if (g) g.parentElement.classList.toggle("open");
});
function animateNum(node, to) {
  const from = +node.textContent || 0; const t0 = performance.now();
  const step = (t) => { const k = Math.min(1, (t - t0) / 500); node.textContent = Math.round(from + (to - from) * (1 - Math.pow(1 - k, 3))); if (k < 1) requestAnimationFrame(step); };
  requestAnimationFrame(step);
}

// ---------- panes / tabs ----------
function showView(v) {
  $("#viewReport").hidden = v !== "report";
  $("#viewProgress").hidden = v !== "progress";
  $("#viewResult").hidden = v !== "result";
  $("#resultTools").hidden = v !== "result";
  $("#resultFoot").hidden = v !== "result";
  $$("#rightTabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.view === v || (v === "progress" && b.dataset.view === "result"))));
}
$("#rightTabs").addEventListener("click", (e) => {
  const b = e.target.closest("button"); if (!b || b.disabled) return;
  showView(S.busy && b.dataset.view === "result" ? "progress" : b.dataset.view);
});
function showPane(p) {
  $("#desk").dataset.show = p;
  $$(".mobile-tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.pane === p)));
}
$(".mobile-tabs").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) showPane(b.dataset.pane); });

// ---------- run ----------
el.run.addEventListener("click", run);
$("#cancelBtn").addEventListener("click", () => S.abort?.abort());

function setStage(stage) {
  const k = STAGES.indexOf(stage);
  $$("#stages li").forEach((li, i) => { li.classList.toggle("done", i < k); li.classList.toggle("active", i === k); });
  $("#progTitle").textContent = { scan: "Reading your draft", rewrite: "Rewriting for a human reader", check: "Checking every claim", revise: "Fixing what moved" }[stage];
}

async function run() {
  const text = el.draft.value;
  if (!text.trim() || S.busy) return;
  if (!S.hasKey) { toast("Add ANTHROPIC_API_KEY to .env and restart the server to rewrite. Scanning still works.", true); return; }
  closePops(); el.tip.hidden = true;
  S.busy = true; el.app.classList.add("busy"); el.run.classList.add("busy"); el.run.disabled = true;
  $("#rightTabs [data-view=result]").disabled = false;
  showView("progress"); showPane("right"); setStage("scan");
  $("#progEyebrow").textContent = MODE_LABEL[S.mode];
  $("#progLog").textContent = "";
  $("#chunks").innerHTML = "";
  let maxStage = 0; const chunkStage = {};

  const ctrl = new AbortController(); S.abort = ctrl;
  try {
    const resp = await fetch(API + "/api/humanize", {
      method: "POST", headers: headers(), signal: ctrl.signal,
      body: JSON.stringify({
        text, mode: S.mode, intensity: S.intensity, dialect: S.dialect, keep_length: keepLength(),
        protect_citations: S.cites, protected_terms: S.terms, voice_sample: S.voice,
      }),
    });
    if (!resp.ok) { const j = await resp.json().catch(() => ({})); throw new Error(j.error || resp.statusText); }
    const reader = resp.body.getReader(); const dec = new TextDecoder(); let buf = ""; let result = null;
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const line = buf.slice(0, idx); buf = buf.slice(idx + 2);
        if (!line.startsWith("data: ")) continue;
        const ev = JSON.parse(line.slice(6));
        if (ev.type === "plan") {
          $("#chunks").innerHTML = ev.chunks > 1 ? Array.from({ length: ev.chunks }, () => "<i></i>").join("") : "";
          if (ev.chunks > 1) $("#progLog").textContent = `Long document: editing ${ev.chunks} sections in parallel`;
        } else if (ev.type === "step") {
          chunkStage[ev.chunk] = ev.stage;
          const k = Math.max(maxStage, STAGES.indexOf(ev.stage)); maxStage = k; setStage(STAGES[k]);
          $$("#chunks i")[ev.chunk]?.classList.add("run");
          if (!/^Rewriting$/.test(ev.message)) $("#progLog").textContent = ($$("#chunks i").length ? `Section ${ev.chunk + 1}: ` : "") + ev.message;
        } else if (ev.type === "chunk_done") {
          const c = $$("#chunks i")[ev.chunk]; if (c) { c.classList.remove("run"); c.classList.add("done"); }
        } else if (ev.type === "error") {
          throw new Error(ev.message);
        } else if (ev.type === "result") {
          result = ev;
        }
      }
    }
    if (!result) throw new Error("The connection closed before the rewrite finished.");
    $$("#stages li").forEach((li) => { li.classList.remove("active"); li.classList.add("done"); });
    saveHistory(text, result);
    setTimeout(() => showResult(result), 250);
  } catch (e) {
    if (e.name === "AbortError") { toast("Cancelled"); } else { toast(e.message || "Something went wrong.", true); }
    showView(S.result ? "result" : "report");
    if (!S.result) $("#rightTabs [data-view=result]").disabled = true;
  } finally {
    S.busy = false; S.abort = null;
    el.app.classList.remove("busy"); el.run.classList.remove("busy"); el.run.disabled = !el.draft.value.trim();
  }
}

// ---------- result ----------
function clearResult() {
  S.result = null; S.acc = [];
  $("#rightTabs [data-view=result]").disabled = true;
  $("#chgBadge").hidden = true;
  showView("report");
}
function showResult(r) {
  S.result = r;
  S.acc = r.hunks.map(() => true);
  el.app.dataset.state = "done";
  $("#rightTabs [data-view=result]").disabled = false;
  showView("result"); showPane("right");
  renderChecks(); renderOutput(); renderStrip(r.after);
  $("#viewResult").scrollTop = 0;
}
function finalText() {
  return S.result.hunks.map((h, i) => (h.t === "eq" ? h.s : S.acc[i] ? h.b : h.a)).join("");
}
function changeCount() { return S.result.hunks.filter((h) => h.t === "ch").length; }

function renderOutput() {
  if (!S.result) return;
  const track = S.view === "track";
  el.output.className = "output " + (track ? "track" : "clean");
  el.output.innerHTML = S.result.hunks.map((h, i) => {
    if (h.t === "eq") return esc(h.s);
    const st = S.acc[i] ? "acc" : "rej";
    const delOnly = !h.b ? " del-only" : "";
    if (track) return `<span class="chg ${st}${delOnly}" data-i="${i}">${h.a ? `<del>${esc(h.a)}</del>` : ""}${h.b ? `<ins>${esc(h.b)}</ins>` : ""}</span>`;
    const shown = S.acc[i] ? h.b : h.a;
    return `<span class="chg ${st}${delOnly && S.acc[i] ? delOnly : ""}" data-i="${i}" title="${S.acc[i] ? "Changed. Click to compare." : "Restored original. Click to compare."}">${esc(shown)}</span>`;
  }).join("");
  const n = changeCount(), rej = S.result.hunks.filter((h, i) => h.t === "ch" && !S.acc[i]).length;
  $("#chgBadge").hidden = !n; $("#chgBadge").textContent = n;
  $("#chgSummary").textContent = n ? `${n} change${n > 1 ? "s" : ""}${rej ? ` · ${rej} reverted` : ""}` : "No changes needed";
}

el.output.addEventListener("click", (e) => {
  const c = e.target.closest(".chg"); if (!c) return;
  e.stopPropagation();
  showChgTip(+c.dataset.i, c);
});
function showChgTip(i, node) {
  const h = S.result.hunks[i];
  $$(".chg.sel", el.output).forEach((x) => x.classList.remove("sel"));
  node.classList.add("sel");
  el.chgTip.innerHTML = `
    <div class="t-label">Original</div><div class="t-was${h.a.trim() ? "" : " empty"}">${h.a.trim() ? esc(h.a) : "Nothing here before. The rewrite added this."}</div>
    <div class="t-label">Rewrite</div><div class="t-was${h.b.trim() ? "" : " empty"}">${h.b.trim() ? esc(h.b) : "Cut entirely."}</div>
    <div class="t-act"><button data-a="1" class="${S.acc[i] ? "on" : ""}">Keep rewrite</button><button data-a="0" class="${S.acc[i] ? "" : "on"}">Restore original</button></div>`;
  el.chgTip.dataset.i = i;
  el.chgTip.hidden = false;
  const rects = node.getClientRects(), r = rects[rects.length - 1] || node.getBoundingClientRect();
  const first = rects[0] || r, th = el.chgTip.offsetHeight, vw = innerWidth, vh = innerHeight;
  const left = Math.min(Math.max(12, first.left), vw - 352);
  let top = r.bottom + 8;
  if (top + th > vh - 12 && first.top - th - 8 > 12) top = first.top - th - 8;
  el.chgTip.style.left = left + "px"; el.chgTip.style.top = Math.max(12, Math.min(top, vh - th - 12)) + "px";
}
$("#viewResult").addEventListener("scroll", () => hideChgTip());
function hideChgTip() { el.chgTip.hidden = true; $$(".chg.sel", el.output).forEach((x) => x.classList.remove("sel")); }
el.chgTip.addEventListener("click", (e) => {
  const b = e.target.closest("button[data-a]"); if (!b) return;
  const i = +el.chgTip.dataset.i;
  S.acc[i] = b.dataset.a === "1";
  renderOutput(); hideChgTip(); rescoreFinal();
});
$("#acceptAll").addEventListener("click", () => { S.acc = S.acc.map(() => true); renderOutput(); rescoreFinal(); });
$("#revertAll").addEventListener("click", () => { S.acc = S.acc.map(() => false); renderOutput(); rescoreFinal(); });

const rescoreFinal = debounce(async () => {
  if (!S.result) return;
  try { renderStrip(await api("/api/scan", { text: finalText() })); } catch {}
}, 200);

function renderStrip(after) {
  const r = S.result, b = r.before;
  const wb = b.stats.words, wa = after.stats.words;
  const dw = wb ? Math.round(((wa - wb) / wb) * 100) : 0;
  $("#verdictStrip").innerHTML =
    statHTML(Math.round(after.score), "machine score", after.score < b.score ? "good" : "", Math.round(b.score)) +
    statHTML(after.hits ? after.hits.length : 0, "tells left", "", b.counts.strong + b.counts.medium + b.counts.weak) +
    statHTML(after.stats.sentence_len_cv, "rhythm spread", after.stats.sentence_len_cv > b.stats.sentence_len_cv ? "good" : "", b.stats.sentence_len_cv) +
    statHTML(wa, `words${dw ? ` (${dw > 0 ? "+" : ""}${dw}%)` : ""}`, "", wb);
}

const ICON_OK = `<svg viewBox="0 0 16 16"><circle cx="8" cy="8" r="7" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="m5 8.2 2 2 4-4.2" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
const ICON_WARN = `<svg viewBox="0 0 16 16"><circle cx="8" cy="8" r="7" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M8 4.5v4.2M8 11v.3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>`;
function renderChecks() {
  const r = S.result, out = [];
  if (r.fact_issues.length) {
    out.push(`<div class="check warn">${ICON_WARN}<details open><summary><b>${r.fact_issues.length} possible change${r.fact_issues.length > 1 ? "s" : ""} in meaning.</b> Check these before you submit.</summary>
      <ul>${r.fact_issues.map((i) => `<li><b>${esc(i.kind)}:</b> ${esc(i.explanation)}</li>`).join("")}</ul></details></div>`);
  } else {
    out.push(`<div class="check ok">${ICON_OK}<span><b>Meaning verified.</b> A separate pass compared every claim, number, and name with your original${r.revisions ? ` and fixed ${r.revisions === 1 ? "one round" : r.revisions + " rounds"} of drift` : ""}.</span></div>`);
  }
  if (r.marks_total) {
    out.push(r.lost_marks.length
      ? `<div class="check warn">${ICON_WARN}<span><b>${r.lost_marks.length} of ${r.marks_total} citations or figures changed:</b> ${r.lost_marks.map((m) => `<code>${esc(m)}</code>`).join(", ")}. Restore them from the original.</span></div>`
      : `<div class="check ok">${ICON_OK}<span><b>All ${r.marks_total} citations and figures kept</b> character for character.</span></div>`);
  }
  if (S.terms.length) {
    out.push(r.lost_terms.length
      ? `<div class="check warn">${ICON_WARN}<span><b>Missing protected terms:</b> ${r.lost_terms.map(esc).join(", ")}.</span></div>`
      : `<div class="check ok">${ICON_OK}<span><b>Protected terms kept.</b></span></div>`);
  }
  if (r.voice_used) {
    const d = r.voice_distance;
    out.push(`<div class="check ok">${ICON_OK}<span><b>Written in your voice.</b>${d != null ? ` Distance from your sample: ${d} (0 is identical).` : ""}</span></div>`);
  }
  $("#checks").innerHTML = out.join("");
}

$("#copyBtn").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText(finalText()); toast("Copied to clipboard"); }
  catch { toast("Could not copy. Select the text and copy it by hand.", true); }
});
$("#dlBtn").addEventListener("click", () => {
  const blob = new Blob([finalText()], { type: "text/plain;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `humanized-${S.mode}-${new Date().toISOString().slice(0, 10)}.txt`;
  a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
});
$("#useDraft").addEventListener("click", () => {
  el.draft.value = finalText(); clearResult(); onInput(); showPane("left"); el.draft.focus(); toast("Moved into the draft. Scan updated.");
});

// ---------- boot ----------
setMode(S.mode); syncLength(); renderTerms(); syncVoiceLabel(); readVoice(); onInput();
fetch(API + "/api/meta").then((r) => r.json()).then((m) => {
  S.hasKey = m.has_key;
  if (m.needs_code) {
    $("#codeRow").hidden = false;
    const ci = $("#optCode");
    ci.value = store.get("code", "");
    ci.addEventListener("input", () => store.set("code", ci.value.trim()));
  }
  if (!m.has_key) { const k = $("#keyStatus"); k.hidden = false; k.textContent = "Scan only: no API key"; }
}).catch(() => {
  const k = $("#keyStatus"); k.hidden = false; k.textContent = "Server unreachable";
});
