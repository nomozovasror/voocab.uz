#!/usr/bin/env node
/**
 * The CEFR scale's contrast gate. Runs in `npm run lint`.
 *
 * It does not carry its own copy of the colour formulas. It PARSES
 * src/styles/globals.css, applies the cascade for each theme the way the
 * browser would (every rule whose selector matches that theme, in source
 * order), resolves var() and color-mix(in srgb) on the result, and measures
 * what comes out. A new theme that defines only its base tokens is therefore
 * measured with the same derived formulas the app ships with; a formula
 * edited in CSS is measured as edited.
 *
 * A failure names the theme, the measurement and the token to override in
 * that theme's block (--pen, --cefr-ink-base, or a base colour).
 *
 * Provenance of the thresholds and the maths: scripts/cefr-design/.
 * Measures: WCAG 2 contrast ratio; OKLab distance x100 ("dE"); Machado 2009
 * protan/deutan simulation for the colour-blind column (reported, not gated).
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const css = readFileSync(join(root, "src/styles/globals.css"), "utf8");
const registry = readFileSync(join(root, "src/theme/themes.ts"), "utf8");

// ── Thresholds ──────────────────────────────────────────────────────────
const MIN = {
  chipText: 4.5, // chip letters on chip ground (WCAG AA, small text)
  passageText: 4.5, // passage text inside any mark
  a1Edge: 3, // the A1 outline against the ground (WCAG 1.4.11)
  washStep: 3.5, // dE between neighbouring passage washes
  hueVsVerdict: 15, // dE, CEFR hue vs --correct / --incorrect
  washVsPen: 8, // dE, CEFR wash vs the pen's fill
};
/**
 * Measured shortfalls in the APPROVED design, recorded so the check can be
 * strict everywhere else. Each is a floor just under the measured value, not
 * a pass: the figure may not get worse, and a new theme gets no exceptions.
 * Fixing one (a different pen, a different verdict colour) means deleting its
 * line here.
 *
 *  - serika-dark washVsPen: the pen is amber (#e2b714), the theme's own brand
 *    yellow, and C1/C2's orange wash is 6.1 dE from it. ACCEPTED (owner
 *    decision): the two marks differ in style, not just hue. The pen fills
 *    at full strength and is the same colour as the theme's accent; CEFR is
 *    a tint. The floor stays so it may not get worse.
 *  - dracula hueVsVerdict:C/wrong: dracula's own red (#ff5555) is 12.4 dE
 *    from C1's orange. ACCEPTED (owner decision): it is the theme's red, and
 *    only one layer (CEFR or the verdict) shows at a time.
 *
 * (dracula's pen text, once an exception, is fixed: dracula sets
 * --pen-strength so its yellow fill is quieter. Do not re-add it.)
 */
const EXCEPTIONS = {
  "serika-dark": { washVsPen: 6.0 },
  dracula: { "hueVsVerdict:C/wrong": 12.0 },
};
const floor = (theme, key, dflt) => EXCEPTIONS[theme.id]?.[key] ?? dflt;
const note = (theme, key) => (EXCEPTIONS[theme.id]?.[key] != null ? "  [approved exception]" : "");

const LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"];
const STEPS = [
  ["A2", "B1"],
  ["B1", "B2"],
  ["B2", "C1"],
];

// ── Colour ──────────────────────────────────────────────────────────────
const NAMED = {
  white: [1, 1, 1, 1],
  black: [0, 0, 0, 1],
  transparent: [0, 0, 0, 0],
};
function parseHex(h) {
  let x = h.slice(1);
  if (x.length === 3 || x.length === 4) x = [...x].map((c) => c + c).join("");
  const n = (i) => parseInt(x.slice(i, i + 2), 16) / 255;
  return [n(0), n(2), n(4), x.length === 8 ? n(6) : 1];
}
/** CSS Color 4 color-mix in srgb: premultiplied interpolation. */
function mix(a, pa, b, pb) {
  if (pa == null && pb == null) (pa = 50), (pb = 50);
  else if (pa == null) pa = 100 - pb;
  else if (pb == null) pb = 100 - pa;
  const sum = pa + pb;
  const wa = pa / sum;
  const wb = pb / sum;
  const alpha = a[3] * wa + b[3] * wb;
  const out = [0, 0, 0].map((_, i) =>
    alpha === 0 ? 0 : (a[i] * a[3] * wa + b[i] * b[3] * wb) / alpha,
  );
  return [...out, alpha * Math.min(1, sum / 100)];
}
function over(c, ground) {
  return [0, 1, 2].map((i) => c[i] * c[3] + ground[i] * (1 - c[3])).concat(1);
}
const lin = (c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const unlin = (c) => (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055);
function lum(c) {
  const [r, g, b] = c.slice(0, 3).map(lin);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
function contrast(a, b) {
  const la = lum(a);
  const lb = lum(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}
const MACH = {
  protan: [
    [0.152286, 1.052583, -0.204868],
    [0.114503, 0.786281, 0.099216],
    [-0.003882, -0.048116, 1.051998],
  ],
  deutan: [
    [0.367322, 0.860646, -0.227968],
    [0.280085, 0.672501, 0.047413],
    [-0.01182, 0.04294, 0.968881],
  ],
};
function sim(c, kind) {
  if (!kind) return c;
  const l = c.slice(0, 3).map(lin);
  const m = MACH[kind];
  return m
    .map((row) => unlin(Math.max(0, Math.min(1, row[0] * l[0] + row[1] * l[1] + row[2] * l[2]))))
    .concat(1);
}
function oklab(c) {
  const [r, g, b] = c.slice(0, 3).map(lin);
  const cbrt = Math.cbrt;
  const l = cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  return [
    0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s,
  ];
}
function dE(a, b, kind) {
  return 100 * Math.hypot(...oklab(sim(a, kind)).map((v, i) => v - oklab(sim(b, kind))[i]));
}
const cvd = (a, b) => Math.min(dE(a, b, "protan"), dE(a, b, "deutan"));
const hex = (c) =>
  "#" +
  c
    .slice(0, 3)
    .map((v) => Math.round(Math.max(0, Math.min(1, v)) * 255).toString(16).padStart(2, "0"))
    .join("");

// ── CSS: rules, cascade, value resolution ───────────────────────────────
const stripped = css.replace(/\/\*[\s\S]*?\*\//g, "");

/** Top-level style rules in source order: [{selectors, decls}]. At-rules
 *  (@theme, @layer, @custom-variant...) are skipped whole. */
function parseRules(src) {
  const rules = [];
  let i = 0;
  while (i < src.length) {
    const open = src.indexOf("{", i);
    const semi = src.indexOf(";", i);
    if (open === -1) break;
    if (semi !== -1 && semi < open && src.slice(i, semi).trim().startsWith("@")) {
      i = semi + 1;
      continue;
    }
    let depth = 1;
    let j = open + 1;
    while (depth && j < src.length) {
      if (src[j] === "{") depth++;
      else if (src[j] === "}") depth--;
      j++;
    }
    const head = src.slice(i, open).trim();
    const body = src.slice(open + 1, j - 1);
    if (!head.startsWith("@")) {
      const decls = {};
      for (const m of body.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
        decls[m[1]] = m[2].replace(/\s+/g, " ").trim();
      }
      rules.push({ selectors: head.split(",").map((s) => s.trim()), decls });
    }
    i = j;
  }
  return rules;
}
const rules = parseRules(stripped);

/** Which themes exist: the registry, which also says dark or light. */
const themes = [...registry.matchAll(/id:\s*"([\w-]+)"[\s\S]*?appearance:\s*"(dark|light)"/g)].map(
  (m) => ({ id: m[1], dark: m[2] === "dark" }),
);
const blockIds = new Set(
  [...stripped.matchAll(/\[data-theme="([\w-]+)"\]/g)].map((m) => m[1]),
);

function cascade(theme) {
  const env = {};
  for (const rule of rules) {
    const hit = rule.selectors.some(
      (s) =>
        s === ":root" ||
        (s === ".dark" && theme.dark) ||
        s === `[data-theme="${theme.id}"]`,
    );
    if (hit) Object.assign(env, rule.decls);
  }
  return env;
}

/** Split "a, b" on top-level commas. */
function splitArgs(s) {
  const out = [];
  let depth = 0;
  let cur = "";
  for (const ch of s) {
    if (ch === "(") depth++;
    if (ch === ")") depth--;
    if (ch === "," && depth === 0) (out.push(cur), (cur = ""));
    else cur += ch;
  }
  out.push(cur);
  return out.map((x) => x.trim());
}
function call(v, name) {
  if (!v.startsWith(name + "(") || !v.endsWith(")")) return null;
  return v.slice(name.length + 1, -1);
}
function resolve(v, env, theme, trail = []) {
  v = v.trim();
  if (v.startsWith("#")) return parseHex(v);
  if (NAMED[v]) return NAMED[v];
  const vr = call(v, "var");
  if (vr !== null) {
    const [name, ...fb] = splitArgs(vr);
    if (env[name] !== undefined) {
      if (trail.includes(name)) throw new Error(`cycle through ${name}`);
      return resolve(env[name], env, theme, [...trail, name]);
    }
    if (fb.length) return resolve(fb.join(","), env, theme, trail);
    throw new Error(`${name} is not defined for ${theme.id}`);
  }
  const cm = call(v, "color-mix");
  if (cm !== null) {
    const [space, a, b] = splitArgs(cm);
    if (space !== "in srgb") throw new Error(`only "in srgb" is supported: ${v}`);
    const part = (arg) => {
      const m = arg.match(/^(.*?)(?:\s+(\d+(?:\.\d+)?)%)?$/s);
      return [resolve(m[1], env, theme, trail), m[2] == null ? null : Number(m[2])];
    };
    const [ca, pa] = part(a);
    const [cb, pb] = part(b);
    return mix(ca, pa, cb, pb);
  }
  throw new Error(`cannot resolve "${v}" (use a hex colour, var() or color-mix in srgb)`);
}

// ── Measure ─────────────────────────────────────────────────────────────
const failures = [];
const fail = (theme, what, got, need, fix) =>
  failures.push(`${theme.id}: ${what} is ${got}, needs ${need}. Fix: ${fix}`);
const f1 = (n) => n.toFixed(1);
const f2 = (n) => n.toFixed(2);

function measure(theme) {
  const env = cascade(theme);
  const get = (name) => {
    try {
      return resolve(`var(${name})`, env, theme);
    } catch (e) {
      fail(theme, name, `unresolvable (${e.message})`, "a colour", `define ${name} or the base tokens it derives from`);
      return null;
    }
  };
  const bg = get("--background");
  const card = get("--card");
  const fg = get("--foreground");
  const ok = get("--correct");
  const bad = get("--incorrect");
  const penFull = get("--mark-key");
  const ink = get("--mark-ink");
  const c2on = get("--cefr-c2-on");
  const edge = get("--cefr-a1-edge");
  if ([bg, card, fg, ok, bad, penFull, ink, c2on, edge].some((x) => !x)) return null;
  const hues = {};
  const inks = {};
  const washes = {};
  for (const L of LEVELS) {
    const l = L.toLowerCase();
    hues[L] = get(`--cefr-${l}`);
    inks[L] = get(`--cefr-${l}-ink`);
    washes[L] = get(`--cefr-${l}-wash`);
    if (!hues[L] || !inks[L] || !washes[L]) return null;
  }
  const grounds = { bg, card };
  // PassagePane WASH.fill = --mark-key at var(--pen-strength, 40%)
  const strength = Number.parseFloat(env["--pen-strength"] ?? "40") / 100;
  const pen = over([penFull[0], penFull[1], penFull[2], strength], bg);
  const lines = [];

  const rows = LEVELS.map((L) => {
    // Chip ground per surface it can sit on.
    const chipGround = (surface) =>
      L === "A1" ? surface : L === "C2" ? hues.C2 : over(washes[L], surface);
    const chipInk = L === "C2" ? c2on : inks[L];
    const chipCR = Math.min(
      ...Object.values(grounds).map((s) => contrast(chipInk, chipGround(s))),
    );
    const wash = over(washes[L], bg);
    const textCR = contrast(ink, wash);
    const washVis = dE(wash, bg);
    const penDE = dE(wash, pen);
    return { L, chipCR, wash, textCR, washVis, penDE, chipInk, chipBg: chipGround(bg) };
  });

  for (const r of rows) {
    const l = r.L.toLowerCase();
    if (r.chipCR < MIN.chipText)
      fail(theme, `${r.L} chip letters on ground`, f2(r.chipCR), MIN.chipText,
        `--cefr-ink-base (the ink base the letters are mixed from), or the base tokens`);
    if (r.textCR < MIN.passageText)
      fail(theme, `passage text on the ${r.L} wash`, f2(r.textCR), MIN.passageText,
        `--cefr-ink-base (the text colour inside every mark)`);
    // A wash that does not step off the ground is no mark at all; the
    // ordered steps below carry the real requirement, this catches a
    // wash that vanished entirely.
    if (r.washVis < 1)
      fail(theme, `${r.L} wash against the ground`, f1(r.washVis) + " dE", "visible", `--cefr-${l}-wash`);
    if (r.penDE < floor(theme, "washVsPen", MIN.washVsPen))
      fail(theme, `${r.L} wash against the pen fill`, f1(r.penDE) + " dE", floor(theme, "washVsPen", MIN.washVsPen) + " dE",
        `--pen (give this theme a pen colour away from the CEFR hues)`);
  }
  const penTextCR = contrast(ink, pen);
  if (penTextCR < floor(theme, "penText", MIN.passageText))
    fail(theme, "passage text on the pen fill", f2(penTextCR), floor(theme, "penText", MIN.passageText), `--cefr-ink-base or --pen`);

  const edgeCR = Math.min(...Object.values(grounds).map((s) => contrast(edge, s)));
  if (edgeCR < MIN.a1Edge)
    fail(theme, "A1 outline edge against the ground", f2(edgeCR), MIN.a1Edge, "the base tokens (the edge is the A hue mixed 50% with --foreground)");

  const steps = STEPS.map(([a, b]) => {
    const wa = rows.find((r) => r.L === a).wash;
    const wb = rows.find((r) => r.L === b).wash;
    const n = dE(wa, wb);
    if (n < MIN.washStep)
      fail(theme, `${a} to ${b} wash step`, f1(n) + " dE", MIN.washStep + " dE", "the base tokens (a wash cannot step off a ground it matches)");
    return { pair: `${a}-${b}`, n, c: cvd(wa, wb) };
  });

  const verdict = [];
  for (const [L, hue] of [["A", hues.A1], ["B1", hues.B1], ["B2", hues.B2], ["C", hues.C1]]) {
    for (const [name, col, token] of [["correct", ok, "--success"], ["wrong", bad, "--destructive"]]) {
      const d = dE(hue, col);
      verdict.push({ L, name, d });
      if (d < floor(theme, `hueVsVerdict:${L}/${name}`, MIN.hueVsVerdict))
        fail(theme, `${L} hue against ${name}`, f1(d) + " dE", floor(theme, `hueVsVerdict:${L}/${name}`, MIN.hueVsVerdict) + " dE", `${token} (move the theme's ${name} colour off the CEFR hue)`);
    }
  }

  // ── Table ──
  lines.push(`\n== ${theme.id} (${theme.dark ? "dark" : "light"})  ground ${hex(bg)}  text ${hex(fg)}  pen ${hex(penFull)}  ink ${hex(ink)}`);
  lines.push("  level  chip CR  text/wash  wash CR  wash vs ground  wash vs pen  chip ink / ground");
  for (const r of rows) {
    lines.push(
      `  ${r.L.padEnd(5)}  ${f2(r.chipCR).padStart(7)}  ${f2(r.textCR).padStart(9)}  ${f2(contrast(r.wash, bg)).padStart(7)}  ${f1(r.washVis).padStart(14)}  ${f1(r.penDE).padStart(11)}  ${hex(r.chipInk)} / ${hex(r.chipBg)}`,
    );
  }
  lines.push(`  pen fill ${hex(pen)}: CR vs ground ${f2(contrast(pen, bg))}, text on pen ${f2(penTextCR)}${note(theme, "penText")}`);
  lines.push(`  A1 edge ${hex(edge)}: CR ${f2(edgeCR)}`);
  lines.push("  wash steps (dE normal / colour-blind): " + steps.map((s) => `${s.pair} ${f1(s.n)}/${f1(s.c)}`).join("  "));
  for (const k of Object.keys(EXCEPTIONS[theme.id] ?? {})) lines.push(`  approved exception: ${k}, floor ${EXCEPTIONS[theme.id][k]}`);
  lines.push("  hue vs verdict colours (dE): " + verdict.map((v) => `${v.L}/${v.name} ${f1(v.d)}`).join("  "));
  return lines.join("\n");
}

// The inline first-paint script in index.html keeps its own id lists.
{
  const html = readFileSync(join(root, "index.html"), "utf8");
  const grab = (name) => html.match(new RegExp(`var ${name} = \\{([^}]*)\\}`))?.[1] ?? "";
  const ids = (s) => [...s.matchAll(/"?([\w-]+)"?\s*:/g)].map((m) => m[1]).sort().join();
  for (const [name, dark] of [["dark", true], ["light", false]]) {
    const want = themes.filter((t) => t.dark === dark).map((t) => t.id).sort().join();
    if (ids(grab(name)) !== want)
      failures.push(`index.html: first-paint script's ${name} theme ids (${ids(grab(name))}) differ from themes.ts (${want}). Fix: update the lists in the inline script.`);
  }
}

// ── Run ─────────────────────────────────────────────────────────────────
for (const id of blockIds) {
  if (!themes.some((t) => t.id === id))
    failures.push(`${id}: has a [data-theme] block in globals.css but no entry in src/theme/themes.ts (the check needs its light/dark appearance)`);
}
for (const t of themes) {
  if (!blockIds.has(t.id) && !(t.id === "serika-dark"))
    failures.push(`${t.id}: is in src/theme/themes.ts but has no [data-theme="${t.id}"] block in globals.css`);
}
for (const t of themes) {
  const table = measure(t);
  if (table) console.log(table);
}
if (failures.length) {
  console.error(`\nCEFR contrast check FAILED (${failures.length}):`);
  for (const f of failures) console.error("  - " + f);
  console.error("\nSee frontend/CLAUDE.md, 'Adding a theme'.");
  process.exit(1);
}
console.log(`\nCEFR contrast check passed for ${themes.length} themes.`);
