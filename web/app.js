/* Routeur Rhum · interface cockpit. Lit les fichiers publiés dans data/ ; l'API locale est facultative. */
"use strict";

const SAIL_COLORS = { Jib: "#8ecae6", Spi: "#ffb703", Staysail: "#2a9dc0", LightJib: "#a7c957",
  Code0: "#ef7b5a", HeavyGnk: "#f4a261", LightGnk: "#c8a2e0" };
// Noms des voiles tels qu'affichés dans le jeu (identiques en version française).
const SAIL_LABEL = { Jib: "Jib", Spi: "Spi", Staysail: "Staysail", LightJib: "Light Jib", Code0: "Code 0",
  HeavyGnk: "Heavy Gnk", LightGnk: "Light Gnk" };
const sailLabel = (s) => SAIL_LABEL[s] || s;
// Options du jeu (clés du routeur), dans l'ordre de l'écran « Les options de … ».
const OPTIONS = [
  ["foils", "Foils", "+4 % de vitesse de 16 à 35 nœuds, du vent de travers au portant"],
  ["hull", "Coque polie", "+0,3 % de vitesse partout"],
  ["winch_pro", "Winchs pro", "Virements, empannages et changements de voile plus courts"],
  ["auto_sail", "Voiles auto", "Le jeu change de voile tout seul"],
  ["light_sails", "Voiles légères", "Light Jib et Light Gnk, pour le petit temps"],
  ["heavy_sails", "Voiles lourdes", "Staysail et Heavy Gnk, pour le vent fort"],
  ["reach_sail", "Code 0", "Pour le vent de travers"],
];
const $ = (s) => document.querySelector(s);
const state = { route: null, main: null, safe: null, ens: null, ensSt: null, choice: "gfs",
  status: null, wx: null, wind: null, api: false, fmt: "dms", slider: 0, boats: [], boat: null, topic: null };
const store = {
  get(k, d) { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* stockage indisponible */ } },
  del(k) { try { localStorage.removeItem(k); } catch { /* stockage indisponible */ } },
};

// --- formats ----------------------------------------------------------------------------------
const ts = (iso) => (iso ? Date.parse(iso) : NaN);
const dtLocal = new Intl.DateTimeFormat("fr-FR", { weekday: "short", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
const dtUtc = new Intl.DateTimeFormat("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", timeZone: "UTC" });
const dtGwada = new Intl.DateTimeFormat("fr-FR", { weekday: "short", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", timeZone: "America/Guadeloupe" });
const fmtT = (iso) => (iso ? dtLocal.format(new Date(iso)) : "–");
const fmtZ = (iso) => (iso ? dtUtc.format(new Date(iso)).replace(" ", " ") + " UTC" : "");
const pad = (n, w = 2) => String(n).padStart(w, "0");
const dtLong = new Intl.DateTimeFormat("fr-FR", { weekday: "long", day: "numeric", month: "long" });
const dtDay = new Intl.DateTimeFormat("fr-FR", { weekday: "short", day: "2-digit", month: "2-digit" });
const dtDayShort = new Intl.DateTimeFormat("fr-FR", { weekday: "short", day: "numeric" });
const dtHM = new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit" });
const hm = (t) => dtHM.format(new Date(t));
const fr1 = (x) => x.toFixed(1).replace(".", ",");

// Icônes dessinées (trait 1,75, même famille que la barre d'onglets).
const ICONS = {
  copy: '<rect x="8.5" y="8.5" width="11" height="11" rx="2"/><path d="M15.5 8.5V6.5a2 2 0 0 0-2-2h-7a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h2"/>',
  pin: '<path d="M12 21s-7-6.2-7-11.5a7 7 0 0 1 14 0C19 14.8 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/>',
  check: '<circle cx="12" cy="12" r="9"/><path d="M8 12.3l2.7 2.7L16.2 9.5"/>',
  alert: '<path d="M12 3.8l9 15.7H3z"/><path d="M12 10v4M12 16.8v.01"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7.5V12l3 2"/>',
  flag: '<path d="M5.5 21V4M5.5 4.5h11l-2.2 4 2.2 4h-11"/>',
  sync: '<path d="M19.5 11A7.5 7.5 0 0 0 6 6.6L4.5 8M4.5 13A7.5 7.5 0 0 0 18 17.4l1.5-1.4"/><path d="M4.5 4v4h4M19.5 20v-4h-4"/>',
  lock: '<rect x="5" y="10.5" width="14" height="10" rx="2"/><path d="M8 10.5V7.5a4 4 0 0 1 8 0v3"/>',
  unlock: '<rect x="5" y="10.5" width="14" height="10" rx="2"/><path d="M8 10.5V7.5a4 4 0 0 1 7.7-1.5"/>',
  sail: '<path d="M12 3.5v14"/><path d="M12 4.5c3.8 2.8 6 7.4 6 12.5h-6"/><path d="M10 7.5c-2.6 2.6-4 5.8-4 9.5h4"/><path d="M4 20.5h16"/>',
  locate: '<circle cx="12" cy="12" r="6.5"/><circle cx="12" cy="12" r="2"/><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3"/>',
  ruler: '<path d="M3.5 16.5L16.5 3.5l4 4-13 13z"/><path d="M7.5 12.5l2 2M10.5 9.5l1.5 1.5M13.5 6.5l2 2"/>',
};
const ico = (k) => `<svg class="ico" viewBox="0 0 24 24" aria-hidden="true">${ICONS[k]}</svg>`;
const swatch = (s) => `<i class="sw" style="background:${SAIL_COLORS[s] || "#999"}"></i>`;
// Chaque position se copie d'une touche ; « both » ajoute un bouton qui copie les deux d'un coup.
const coordsHtml = (w, both = true) => `<div class="c"><button class="coord" data-copy="${latS(w.lat)}" aria-label="Copier la latitude">${latS(w.lat)}</button>
  <button class="coord" data-copy="${lonS(w.lon)}" aria-label="Copier la longitude">${lonS(w.lon)}</button>
  ${both ? `<button class="copy" data-copy="${latS(w.lat)} ${lonS(w.lon)}" aria-label="Copier latitude et longitude">${ico("copy")}</button>` : ""}</div>`;

function coord(v, pos, neg, degW) {
  const h = v >= 0 ? pos : neg, a = Math.abs(v);
  if (state.fmt === "dd") return `${v.toFixed(5)}`;
  let d = Math.floor(a), m = (a - d) * 60;
  if (state.fmt === "dms") {
    let mi = Math.floor(m), s = Math.round((m - mi) * 60);
    if (s === 60) { s = 0; mi += 1; } if (mi === 60) { mi = 0; d += 1; }
    return `${pad(d, degW)}°${pad(mi)}'${pad(s)}" ${h}`;
  }
  if (+m.toFixed(2) >= 60) { m = 0; d += 1; }
  return `${pad(d, degW)}°${m.toFixed(2).padStart(5, "0").replace(".", ",")}' ${h}`;
}
const latS = (v) => coord(v, "N", "S", 2);
const lonS = (v) => coord(v, "E", "W", 3);
const deg = (v) => `${Math.round(((v % 360) + 360) % 360).toString().padStart(3, "0")}°`;
// TWA en degrés et côté d'où vient le vent (routeur : négative = bâbord) ; 0° et 180° n'ont pas de côté.
const twaS = (v) => {
  const a = Math.round(Math.abs(v));
  return a === 0 || a === 180 ? `${a}°` : `${a}° ${v < 0 ? "bâbord" : "tribord"}`;
};
const hoursS = (h) => `${Math.floor(h / 24)} j ${pad(Math.round(h % 24))} h`;
// Ordre à programmer dans le jeu : TWA fixe si le vent tourne le long du segment, sinon cap fixe.
// Dans le jeu : cadenas fermé = TWA verrouillée (le bateau suit le vent), cadenas ouvert = cap fixe.
const lockS = (w) => (w.order?.mode === "twa" ? `<span class="lock on">${ico("lock")}cadenas fermé</span>`
  : `<span class="lock">${ico("unlock")}cadenas ouvert</span>`);
const orderS = (w) => (w.order?.mode === "twa" ? `TWA <b>${twaS(w.order.value)}</b>` : `Cap <b>${deg(w.heading)}</b>`);
const orderTxt = (w) => (w.order?.mode === "twa" ? `TWA ${twaS(w.order.value)}` : `Cap ${deg(w.heading)}`);
const orderWhy = (w) => (w.order?.unsafe ? `<b class="bad">Ne programme pas cet ordre : rejoué dans la météo du jeu, il mène dans une zone interdite ou à la côte. Renvoie ta position.</b>`
  : w.order?.guard === "twa" ? "Cap fixe : la TWA verrouillée menait dans une zone interdite."
  : w.order?.mode === "twa" ? `Le vent tourne de ${w.order.spread_cap}° sur ce segment : programme une TWA fixe.`
  : w.order?.spread_twa >= 10 ? `Cap fixe : l'angle au vent varie de ${w.order.spread_twa}° sur ce segment.` : "");

function parseCoord(txt, isLat) {
  // Accepte « 46.2083 », « -23.668 », « 46°12,5 N », « 46 12.5 N », « 46°12'30" N »
  const s = String(txt).trim().toUpperCase().replace(",", ".");
  const neg = /[SWO]/.test(s) || s.startsWith("-");
  const nums = s.match(/\d+(\.\d+)?/g);
  if (!nums) return NaN;
  const [d, m = 0, sec = 0] = nums.map(Number);
  let v = d + m / 60 + sec / 3600;
  if (neg) v = -v;
  return Math.abs(v) <= (isLat ? 90 : 180) ? v : NaN;
}

// Position saisie au téléphone : sans hémisphère, on est forcément au nord et à l'ouest (Saint-Malo → Guadeloupe).
function parseGame(txt, isLat) {
  let v = parseCoord(txt, isLat);
  if (!Number.isNaN(v) && !/[NSEWO-]/i.test(String(txt))) v = isLat ? Math.abs(v) : -Math.abs(v);
  return v;
}

function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toast.h); toast.h = setTimeout(() => t.classList.remove("show"), 1600);
}
async function copyText(txt) {
  try { await navigator.clipboard.writeText(txt); }
  catch { // http sur le réseau local : pas d'API presse-papiers sécurisée
    const ta = document.createElement("textarea"); ta.value = txt; ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove();
  }
  toast(`Copié : ${txt}`);
}

// --- données ----------------------------------------------------------------------------------
// Fichiers propres au bateau affiché (route, scénarios, explication) ; le reste est partagé.
const bpath = (name) => (state.boat ? `data/bateaux/${state.boat}/${name}` : `data/${name}`);
const boatName = () => state.boats.find((b) => b.id === state.boat)?.name || "";

async function getJSON(path) {
  const r = await fetch(`${path}?_=${Date.now()}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`${path} : ${r.status}`);
  return r.json();
}

function trackAt(t) {
  // Position, vent et vitesse sur la route à l'instant t (interpolation linéaire)
  const tr = state.route?.track; if (!tr?.length) return null;
  const T = tr.map((p) => ts(p[2]));
  if (t <= T[0]) return { i: 0, lat: tr[0][0], lon: tr[0][1], p: tr[0], before: true };
  if (t >= T[T.length - 1]) return { i: tr.length - 1, lat: tr.at(-1)[0], lon: tr.at(-1)[1], p: tr.at(-1), after: true };
  let i = T.findIndex((x) => x > t) - 1;
  const f = (t - T[i]) / (T[i + 1] - T[i]);
  return { i, lat: tr[i][0] + (tr[i + 1][0] - tr[i][0]) * f, lon: tr[i][1] + (tr[i + 1][1] - tr[i][1]) * f, p: tr[i] };
}
function hav(a, b, c, d) {
  const R = 3440.065, r = Math.PI / 180, dp = (c - a) * r, dl = (d - b) * r;
  const x = Math.sin(dp / 2) ** 2 + Math.cos(a * r) * Math.cos(c * r) * Math.sin(dl / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(x));
}
function windAt(lat, lon, t) {
  const W = state.wind; if (!W) return null;
  const k = Math.max(0, Math.min(W.frames.length - 1, Math.round((t - ts(W.frames[0].t)) / 21600000)));
  const fr = frameData(k);
  const j = Math.round((lat - W.lat0) / W.step), i = Math.round((lon - W.lon0) / W.step);
  if (j < 0 || i < 0 || j >= W.nlat || i >= W.nlon) return null;
  const n = W.nlat * W.nlon, u = fr[j * W.nlon + i] * W.scale_ms, v = fr[n + j * W.nlon + i] * W.scale_ms;
  return { tws: Math.hypot(u, v) / 0.514444, twd: (Math.atan2(-u, -v) * 180 / Math.PI + 360) % 360 };
}
const frameCache = new Map();
function frameData(k) {
  if (!frameCache.has(k)) {
    const b = atob(state.wind.frames[k].uv), a = new Int8Array(b.length);
    for (let x = 0; x < b.length; x++) a[x] = (b.charCodeAt(x) << 24) >> 24;
    frameCache.set(k, a);
  }
  return frameCache.get(k);
}

// --- tableau de bord --------------------------------------------------------------------------
// Candidat des scénarios qui correspond à la route affichée (conseillée ou GFS seule).
const shownCand = () => state.ens?.candidates.find((c) => c.id === (state.route === state.safe ? state.ens.recommended : "gfs"));

// Frise des arrivées : un point par version de la météo, la bande = 8 cas sur 10, le trait = la plus probable.
function fanHtml(c) {
  const T = (c.etas || []).map(ts).filter(Number.isFinite);
  const p10 = ts(c.p10_eta), p90 = ts(c.p90_eta), med = ts(c.median_eta);
  const lo0 = Math.min(p10, ...T), hi0 = Math.max(p90, ...T);
  const padT = Math.max((hi0 - lo0) * 0.08, 3 * 3600e3), lo = lo0 - padT, hi = hi0 + padT;
  const X = (t) => ((t - lo) / (hi - lo)) * 100;
  const bins = 28, lvl = new Map();
  const dots = T.map((t) => {
    const b = Math.min(bins - 1, Math.floor(((t - lo) / (hi - lo)) * bins)), l = lvl.get(b) || 0;
    lvl.set(b, l + 1);
    return `<i style="left:${(((b + 0.5) / bins) * 100).toFixed(2)}%;--l:${l}"></i>`;
  });
  const days = [];
  const d = new Date(lo); d.setHours(0, 0, 0, 0);
  for (; d.getTime() < hi; d.setDate(d.getDate() + 1)) {
    const m = d.getTime(), noon = m + 12 * 3600e3;
    if (m > lo) days.push(`<b class="mid" style="left:${X(m).toFixed(2)}%"></b>`);
    if (noon > lo + 2 * 3600e3 && noon < hi - 2 * 3600e3) days.push(`<span class="day" style="left:${X(noon).toFixed(2)}%">${dtDayShort.format(new Date(noon))}</span>`);
  }
  const label = `${T.length || "Plusieurs"} arrivées possibles, la plus probable ${fmtT(c.median_eta)}`;
  return `<div class="fan" style="--rows:${Math.max(1, ...lvl.values())}" role="img" aria-label="${label}">
    <div class="band" style="left:${X(p10).toFixed(2)}%;width:${(X(p90) - X(p10)).toFixed(2)}%"></div>
    ${days.join("")}${dots.join("")}<b class="med" style="left:${X(med).toFixed(2)}%"></b></div>`;
}

function renderBord() {
  const R = state.route, S = state.status, now = Date.now();
  if (!R) {
    $("#arrive").innerHTML = `<h1>Pas encore de route</h1><p class="sub">Elle apparaît dès que la première météo est calculée.</p>`;
    for (const k of ["#next-wp", "#next-sail", "#stats", "#cmp", "#states"]) $(k).innerHTML = "";
    return;
  }
  const names = R.sail_names, cand = shownCand();
  // Avec les scénarios : l'arrivée la plus probable (médiane) de la route affichée, et sa fourchette.
  const eta = cand?.median_eta || R.eta;
  let h = eta ? `<h1><span>Arrivée</span> ${dtLong.format(new Date(eta))} à ${hm(eta)}</h1>
    <p class="sub">${cand?.median_eta ? "La plus probable" : "Estimée"}, à l'heure de ton téléphone. En Guadeloupe : ${dtGwada.format(new Date(eta))}.</p>`
    : `<h1>Arrivée hors de la durée de calcul</h1>`;
  if (cand?.median_eta) {
    const c = confidence(cand), n = cand.etas?.length;
    h += fanHtml(cand) + `<p class="fan-cap">${n ? `Chaque point est une version de la météo (${n}). ` : ""}8 sur 10 arrivent entre
      <b>${fmtT(cand.p10_eta)}</b> et <b>${fmtT(cand.p90_eta)}</b>. Fiabilité <b class="${c.cls}">${c.label}</b>.</p>`;
  }
  $("#arrive").innerHTML = h;

  const at = trackAt(now);
  const cur = at && !at.before ? at : { i: 0, lat: R.track[0][0], lon: R.track[0][1], p: R.track[0] };
  let rest = 0; const tr = R.track;
  rest += hav(cur.lat, cur.lon, tr[Math.min(cur.i + 1, tr.length - 1)][0], tr[Math.min(cur.i + 1, tr.length - 1)][1]);
  for (let k = cur.i + 1; k < tr.length - 1; k++) rest += hav(tr[k][0], tr[k][1], tr[k + 1][0], tr[k + 1][1]);
  const p = cur.p, wd = windAt(cur.lat, cur.lon, Math.max(now, ts(R.start_time)));
  $("#stats").innerHTML = `
    <div><dt>Distance restante</dt><dd>${Math.round(rest).toLocaleString("fr-FR")}<small>milles</small></dd></div>
    <div><dt>Vitesse ${at?.before ? "au départ" : "prévue"}</dt><dd>${fr1(p[6])}<small>kt</small></dd></div>
    <div><dt>Vent ${at?.before ? "au départ" : "maintenant"}</dt><dd>${wd ? `${deg(wd.twd)} · ${Math.round(wd.tws)}` : Math.round(p[4])}<small>kt</small></dd></div>
    <div><dt>Voile</dt><dd class="wrap">${swatch(names[p[3]])}${sailLabel(names[p[3]])}</dd></div>`;

  const wp = R.waypoints.find((w) => ts(w.t) > now);
  $("#next-wp").innerHTML = wp ? `<h2>${wp.n === 0 ? "Premier ordre, au départ" : "Prochain ordre"} <span class="tag">WP${pad(wp.n)}</span></h2>
    <p class="when">${ico("clock")}${fmtT(wp.t)} · dans ${until(ts(wp.t) - now)}</p>
    <p class="order-main"><span>${orderS(wp)}</span>${lockS(wp)}<span class="sail">${swatch(wp.sail)}${sailLabel(wp.sail)}</span></p>
    ${coordsHtml(wp)}
    <p class="why-line">${[wp.reason, orderWhy(wp)].filter(Boolean).join(" · ")}</p>` : "";
  const sc = R.sail_changes.find((c) => ts(c.t) > now);
  $("#next-sail").innerHTML = sc ? `${ico("sail")}<span>Changement de voile ${fmtT(sc.t)} (dans ${until(ts(sc.t) - now)}) :
    ${sailLabel(sc.sail_from)} → <b>${sailLabel(sc.sail_to)}</b>, +${String(sc.gain_pct).replace(".", ",")} % de vitesse.</span>` : "";

  const C = R.comparison;
  $("#cmp").innerHTML = C ? `<h3>Par rapport à la route précédente</h3>
    <p>Arrivée <b class="${C.eta_delta_h > 0 ? "warn" : "ok"}">${C.eta_delta_h == null ? "–" : (C.eta_delta_h > 0 ? "+" : "") + fr1(C.eta_delta_h) + " h"}</b>,
      écart de trajectoire ${C.max_deviation_nm ?? "–"} milles au plus, ${C.mean_deviation_nm ?? "–"} en moyenne.</p>
    <p class="note">Ancienne route : ${C.previous_cycle ? cycleS(C.previous_cycle) : "?"}, calculée ${fmtT(C.previous_computed_at)}.</p>` : "";
  const w = S?.weather, r = S?.route, x = state.expl;
  $("#states").innerHTML = `
    <dt>Météo</dt><dd class="${w?.stale ? "warn" : ""}">${w ? cycleS(w.cycle) + " · âge " + fr1(w.age_h) + " h" : "–"}</dd>
    <dt>Calcul de route</dt><dd class="${r?.state === "ok" ? "" : r?.state === "erreur" ? "bad" : "warn"}">${r ? r.state + (r.compute_s ? " · " + Math.round(r.compute_s) + " s" : "") : "–"}</dd>
    <dt>Calculée le</dt><dd>${fmtT(R.computed_at)}</dd>
    <dt>Départ du calcul</dt><dd>${R.start_source}</dd>
    ${R.game_switch ? `<dt>Météo du jeu</dt><dd>${cycleS(R.game_switch.before_cycle)} jusqu'à ${fmtT(R.game_switch.at)}, puis ${cycleS(R.gfs_cycle)}</dd>` : ""}
    ${x?.state === "pas de clé" ? `<dt>Explication</dt><dd>clé Claude absente</dd>` : ""}`;
  const beyond = R.beyond_forecast_from ? ` Au-delà du ${fmtT(R.beyond_forecast_from)}, la route utilise la dernière échéance disponible.` : "";
  $("#disclaimer").textContent = `Route estimée, pas une optimale garantie : GFS 0,25° interpolé, calcul par étapes de 15 min au début puis d'1 h, polaire ${R.boat} reconstruite et pénalités en partie supposées.${beyond}`;
}
const cycleS = (c) => (c ? `GFS ${c.slice(6, 8)}/${c.slice(4, 6)} ${c.slice(8)}z` : "–");

// Âge réel de la prévision (le fichier d'état peut dater) et durée lisible.
const wxAgeH = (w) => (w ? (Date.now() - ts(w.run)) / 3600e3 : NaN);
// Âge normal jusqu'à ~12 h (un run toutes les 6 h, complet ~5 h après) : même seuil que STALE_AFTER_H du routeur.
const WX_OLD_H = 13;
function until(ms) {
  const m = Math.max(0, Math.round(ms / 60000)), d = Math.floor(m / 1440), h = Math.floor((m % 1440) / 60);
  return d ? `${d} j ${h} h` : h ? `${h} h ${pad(m % 60)}` : `${m} min`;
}

// Pastille de l'en-tête : un seul état, le plus important.
function renderStatus() {
  const w = state.status?.weather, r = state.status?.route, d = state.wx, age = wxAgeH(w), el = $("#status");
  let cls = "ok", txt;
  if (r?.state === "calcul") { cls = "warn"; txt = "Calcul en cours…"; }
  else if (d?.state === "téléchargement") { cls = "warn"; txt = `Météo ${d.done}/${d.total}`; }
  else if (!w) { cls = "bad"; txt = "Pas de météo"; }
  else if (r && r.state !== "ok") { cls = "bad"; txt = "Route : problème"; }
  else { cls = age > WX_OLD_H ? "warn" : "ok"; txt = `Météo d'il y a ${Math.round(age)} h`; }
  el.className = `status ${cls}`;
  el.querySelector("span").textContent = txt;
  el.title = w ? `${cycleS(w.cycle)} · route ${r?.state || "?"}` : "";
}

// « À faire » : où on en est et l'action à faire, une ligne chacune.
function renderTodo() {
  const R = state.route, S = state.status, now = Date.now(), el = $("#todo");
  if (!R) { el.innerHTML = ""; return; }
  const start = ts(S?.race?.start_time || R.start_time), age = wxAgeH(S?.weather);
  const row = (kind, icon, title, text = "", btn = "") =>
    `<div class="todo ${kind}">${ico(icon)}<div><p class="t">${title}</p>${text ? `<p>${text}</p>` : ""}${btn}</div></div>`;
  const go = (ghost) => `<button class="btn${ghost ? " ghost" : ""}" data-go="pos">${ico("pin")}Envoyer ma position</button>`;
  const rows = [];
  if (S?.route?.state === "calcul") rows.push(row("busy", "sync", "Nouveau calcul en cours", "Environ 3 min."));
  const pend = pending();
  if (pend) {
    const late = now / 1000 - pend.t > 1800;
    rows.push(row(late ? "warn" : "busy", late ? "alert" : "sync", `${pend.what || "Position envoyée"} à ${hm(pend.t * 1000)}`,
      late ? "Toujours pas de nouvelle route après 30 min. Réessaie." : "Nouvelle route dans 5 à 15 min, la page se met à jour toute seule."));
  }
  const prog = progUntil() * 1000, progOn = prog > now;
  if (progOn) rows.push(row("ok", "clock", `Reviens avant ${whenS(prog)}`,
    `Tes ordres programmés s'arrêtent là. Ton téléphone sonne vers ${whenS(prog - RETURN_BEFORE_MS)}.`));
  else if (now >= start && (!R.eta || now < ts(R.eta)))
    rows.push(row("warn", "clock", "Programme tes prochains ordres", "Puis choisis le dernier dans Ordres : ton téléphone te dira quand revenir.",
      `<button class="btn" data-go="route">${ico("sail")}Voir les ordres</button>`));
  const chosen = chosenOpts();
  if (!pend && chosen && R.options && !sameOpts(chosen, R.options))
    rows.push(row("warn", "alert", "Route calculée avec d'autres options", "Le prochain calcul prendra les tiennes, dans l'heure au plus tard."));
  if (now < start) rows.push(row("calm", "clock", `Départ dans ${until(start - now)}`,
    `${fmtT(new Date(start).toISOString())}. Rien à faire : la route se recalcule toute seule à chaque nouvelle météo, et bougera encore d'ici là.`));
  else if (!R.eta || now < ts(R.eta) + 6 * 3600e3) {
    // Plus la dernière position est vieille, plus la route repose sur « le bateau a suivi la route ».
    const lp = R.last_position, lpAge = lp ? (now - ts(lp.time)) / 3600e3 : Infinity;
    // Ordres programmés en cours : le bateau suit la route, pas besoin de position.
    if (!pend && !progOn) rows.push(!lp ? row("warn", "pin", "Envoie ta position", "Sinon le routeur suppose que tu as suivi sa route.", go())
      : lpAge >= 6 ? row("warn", "pin", `Ta position date de ${until(now - ts(lp.time))}`, "La route peut être fausse si tu t'es écarté.", go())
      : lpAge >= 4 ? row("calm", "pin", `Position envoyée il y a ${until(now - ts(lp.time))}`, "Pense à la renvoyer bientôt.", go(true))
      : row("ok", "check", `Position envoyée il y a ${until(now - ts(lp.time))}`));
  } else rows.push(row("ok", "flag", "Course terminée"));
  if (age > WX_OLD_H) rows.push(row("warn", "alert", `Météo vieille de ${Math.round(age)} h`, "Le prochain calcul la remettra à jour tout seul."));
  el.innerHTML = rows.join("");
}

// Lignes courtes sous la frise : quelle route est affichée, et ce qui a changé au dernier calcul.
function renderNotes() {
  const R = state.route, C = R?.comparison, v = verdict();
  const shown = state.route && state.route === state.safe ? "safe" : "gfs";
  const vh = !v ? "" : `<b>Suis la route ${v.id === "safe" ? "conseillée" : "GFS"}</b> : ${v.why}`
    + (v.id !== shown ? ` <button class="link" type="button" data-follow>Afficher cette route</button>` : "");
  document.querySelectorAll(".verdict").forEach((el) => (el.innerHTML = vh));
  let ch = "";
  if (C && C.eta_delta_h != null) {
    const d = C.eta_delta_h, same = Math.abs(d) < 0.5 && (C.mean_deviation_nm ?? 0) < 5;
    const dir = C.mean_lat_shift_deg > 0.3 ? ", plus au nord" : C.mean_lat_shift_deg < -0.3 ? ", plus au sud" : "";
    ch = `Mise à jour ${fmtT(R.computed_at)} : ` + (same ? "route quasi identique."
      : `arrivée <b>${fr1(Math.abs(d))} h ${d < 0 ? "plus tôt" : "plus tard"}</b>, route décalée de ${Math.round(C.mean_deviation_nm)} milles en moyenne${dir}.`);
  }
  $("#change").innerHTML = ch;
  const x = state.expl;
  if (x?.state === "ok" && x.text) {
    // « Intitulé : texte » -> intitulé sur sa propre ligne, texte dessous.
    const esc = (t) => t.replace(/&/g, "&amp;").replace(/</g, "&lt;");
    const rows = x.text.split(/\n+/).filter((t) => t.trim()).map((t) => {
      const m = t.match(/^\s*([^:]{2,22})\s*:\s*(.+)$/);
      return m ? `<div class="why-row"><b>${esc(m[1])}</b><span>${esc(m[2])}</span></div>` : `<p>${esc(t)}</p>`;
    });
    $("#why").innerHTML = `<h2>Le point de l'équipier</h2>${rows.join("")}`;
  } else $("#why").innerHTML = "";
}

// --- feuille de route -------------------------------------------------------------------------
function renderRoute() {
  const R = state.route, ol = $("#wps"); if (!R) { ol.innerHTML = ""; return; }
  const now = Date.now(), only = $("#only-next").checked;
  const prev = R.comparison?.previous_waypoints || [];
  const items = [];
  for (const w of R.waypoints) items.push({ t: ts(w.t), w });
  for (const c of R.sail_changes) items.push({ t: ts(c.t), c });
  items.sort((a, b) => a.t - b.t);
  const firstFuture = items.findIndex((x) => x.t > now);
  const when = (iso) => `<div class="when"><b>${hm(iso)}</b><span>${dtDay.format(new Date(iso))}</span></div>`;
  const html = items.filter((x, k) => !only || (x.t > now - 3600e3 && x.t < now + 48 * 3600e3) || (now < ts(R.start_time) && x.t < ts(R.start_time) + 48 * 3600e3) || k === firstFuture)
    .map(({ t, w, c }) => {
      const past = t < now ? " past" : "";
      if (c) return `<li class="sc${past}">${when(c.t)}<div class="body">${swatch(c.sail_to)}Voile : ${sailLabel(c.sail_from)} → <b>${sailLabel(c.sail_to)}</b>
        <span class="note">· +${String(c.gain_pct).replace(".", ",")} % · vent ${c.tws} kt</span></div></li>`;
      const changed = prev.length && !prev.some(([a, b]) => hav(a, b, w.lat, w.lon) < 10);
      return `<li class="${past}">${when(w.t)}<div class="body">
        <p class="act"><span class="n">WP${pad(w.n)}</span><span>${orderS(w)}</span>${lockS(w)}<span class="sail">${swatch(w.sail)}${sailLabel(w.sail)}</span>${changed ? '<span class="badge warn">modifié</span>' : ""}${w.beyond_forecast ? '<span class="badge warn">hors prévision</span>' : ""}${w.order?.unsafe ? '<span class="badge bad">danger</span>' : ""}</p>
        ${coordsHtml(w, false)}
        <p class="m"><span>TWA <b>${twaS(w.twa)}</b></span><span>vent <b>${deg(w.twd)} · ${w.tws.toFixed(0)} kt</b></span><span><b>${fr1(w.speed)} kt</b> prévus</span><span>${fmtZ(w.t)}</span></p>
        <p class="why">${[w.reason, orderWhy(w)].filter(Boolean).join(" · ")}</p></div></li>`;
    });
  ol.innerHTML = html.join("") || `<li class="note">Aucun point dans les 48 prochaines heures.</li>`;
}

// --- météo ------------------------------------------------------------------------------------
function renderMeteo() {
  const w = state.status?.weather, d = state.wx, r = state.status?.route;
  $("#wx-detail").innerHTML = `
    <dt>Cycle utilisé</dt><dd>${w ? cycleS(w.cycle) : "–"}</dd>
    <dt>Date de génération</dt><dd>${w ? fmtZ(w.run) : "–"}</dd>
    <dt>Âge des données</dt><dd class="${w?.stale ? "warn" : ""}">${w ? w.age_h.toFixed(1) + " h" + (w.stale ? " · ancienne" : "") : "–"}</dd>
    <dt>Échéance max</dt><dd class="${w?.incomplete ? "warn" : ""}">${w ? "+" + w.max_hour + " h" + (w.incomplete ? " · incomplète" : "") : "–"}</dd>
    <dt>Téléchargée le</dt><dd>${w ? fmtT(w.fetched_at) : "–"}</dd>
    <dt>Source</dt><dd>NOAA NOMADS (secours AWS)</dd>
    <dt>Route</dt><dd>${r ? r.state + " · " + (r.message || "") : "–"}</dd>`;
  const pct = d && d.total ? Math.round((d.done / d.total) * 100) : 0;
  $("#dl").innerHTML = d ? `<h3>Dernière vérification météo</h3>
    <div class="line"><span class="${d.state === "erreur" ? "bad" : ""}">${d.state}</span><span class="mono">${fmtT(d.updated_at)}</span></div>
    ${d.state === "téléchargement" ? `<div class="bar"><i style="width:${pct}%"></i></div>` : ""}
    <div class="note">${d.message || ""}</div>` : "";
  $("#api-note").textContent = state.api
    ? "Serveur local connecté : la tâche planifiée vérifie le GFS toutes les heures et recalcule à chaque nouveau cycle."
    : $("#gh").hidden ? "Version en lecture seule : les données sont mises à jour automatiquement." : "";
}

// --- carte ------------------------------------------------------------------------------------
let map, layers = {}, gridRenderer;
// Couleurs du vent (flèches, fond coloré et légende), par force en nœuds.
const WIND_BANDS = [[8, "#4b6c8a"], [14, "#4cc3d9"], [20, "#5fcf80"], [26, "#f2b84b"], [34, "#ef7b5a"], [Infinity, "#ef6461"]];
const windBand = (kt) => WIND_BANDS.findIndex(([max]) => kt < max);
function initMap() {
  map = L.map("map", { preferCanvas: true, zoomControl: false, zoomSnap: 0.25, worldCopyJump: false }).setView([33, -32], 3);
  L.control.zoom({ position: "topright" }).addTo(map);
  // Sous le zoom : recentrer sur le bateau (position estimée maintenant) et règle cap/distance.
  const Tools = L.Control.extend({ onAdd() {
    const bar = L.DomUtil.create("div", "leaflet-bar");
    const btn = (cls, label, icon, fn) => {
      const a = L.DomUtil.create("a", `tool ${cls}`, bar);
      a.href = "#"; a.title = label; a.setAttribute("role", "button"); a.setAttribute("aria-label", label);
      a.innerHTML = ico(icon);
      L.DomEvent.on(a, "click", (e) => { L.DomEvent.preventDefault(e); fn(a); });
    };
    btn("locate", "Centrer sur le bateau", "locate", centerBoat);
    btn("ruler", "Règle : touche deux points pour le cap et la distance", "ruler", toggleRuler);
    L.DomEvent.disableClickPropagation(bar);
    return bar;
  } });
  new Tools({ position: "topright" }).addTo(map);
  // Pas de fond de carte tiers : on affiche les côtes GSHHG, celles qu'utilise le routeur.
  map.attributionControl.addAttribution("Côtes GSHHG 2.3.7 · vent NOAA GFS");
  // Sous les tracés : fond coloré du vent, puis grille (les terres opaques passent par-dessus).
  map.createPane("fill").style.zIndex = 350;
  map.createPane("grid").style.zIndex = 390;
  gridRenderer = L.canvas({ pane: "grid" });
  for (const k of ["grid", "coast", "zones", "gates", "ens", "prev", "iso", "route", "wps", "wind", "boat", "ruler"]) layers[k] = L.layerGroup().addTo(map);
  $("#show-wind").onchange = drawWind; $("#show-iso").onchange = drawRoute; $("#show-prev").onchange = drawRoute;
  $("#show-ens").onchange = drawRoute; $("#show-fill").onchange = drawFill; $("#show-grid").onchange = drawGrid;
  $("#slider").oninput = (e) => { state.slider = +e.target.value; drawWind(); drawBoat(); };
  map.on("moveend", drawWind); map.on("moveend", drawGrid); map.on("click", rulerClick);
  // Rotation du téléphone ou fenêtre redimensionnée : la carte doit reprendre sa taille.
  let rz; addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(() => { map.invalidateSize(); fitOnce(); }, 150); });
}
async function loadStatic() {
  const land = { color: "#5b7083", weight: 1, fillColor: "#1d2a38", fillOpacity: 1, interactive: false };
  try { L.geoJSON(await getJSON("data/coast.geojson"), { style: land }).addTo(layers.coast); } catch { /* facultatif */ }
  try {
    const detail = L.geoJSON(await getJSON("data/coast-detail.geojson"), { style: { ...land, color: "#7a90a5" } });
    const sync = () => (map.getZoom() >= 8 ? layers.coast.addLayer(detail) : layers.coast.removeLayer(detail));
    map.on("zoomend", sync); sync();
  } catch { /* facultatif */ }
  try {
    const course = await getJSON("data/course.geojson");
    L.geoJSON(course, {
      filter: (f) => f.geometry && f.properties.kind !== "forbidden_boundary",
      style: (f) => f.properties.kind === "forbidden" ? { color: "#ef6461", weight: 1, fillOpacity: 0.18 }
        : f.properties.kind === "vigilance" ? { color: "#f2b84b", weight: 1, dashArray: "4 4", fillOpacity: 0.05 }
        : { color: "#f2b84b", weight: 3 },
      pointToLayer: (f, ll) => L.circleMarker(ll, { radius: 5, color: "#f2b84b", weight: 2, fillOpacity: 0.4 }),
      onEachFeature: (f, l) => l.bindTooltip(f.properties.name, { className: "wp-tip" }),
    }).addTo(layers.zones);
  } catch { /* parcours facultatif */ }
}
function drawRoute() {
  for (const k of ["route", "wps", "prev", "iso", "gates", "ens"]) layers[k].clearLayers();
  if (state.ens && $("#show-ens").checked)
    for (const c of state.ens.candidates)
      if (c.id !== "gfs") L.polyline(c.track, { color: "#8b9bab", weight: 1, opacity: 0.35, interactive: false }).addTo(layers.ens);
  const R = state.route; if (!R) return;
  const tr = R.track, names = R.sail_names;
  let seg = [[tr[0][0], tr[0][1]]], sail = tr[0][3];
  const flush = () => seg.length > 1 && L.polyline(seg, { color: SAIL_COLORS[names[sail]] || "#4cc3d9", weight: 3 }).addTo(layers.route);
  for (let k = 1; k < tr.length; k++) {
    seg.push([tr[k][0], tr[k][1]]);
    if (tr[k][3] !== sail || k === tr.length - 1) { flush(); seg = [[tr[k][0], tr[k][1]]]; sail = tr[k][3]; }
  }
  for (const g of R.gates) L.polyline([g.a, g.b], { color: "#f2b84b", weight: 4 }).bindTooltip(g.name, { className: "wp-tip" }).addTo(layers.gates);
  for (const w of R.waypoints) {
    L.circleMarker([w.lat, w.lon], { radius: 3, color: "#e6edf3", weight: 1, fillColor: "#0b1118", fillOpacity: 1 })
      .bindTooltip(`WP${pad(w.n)} · ${fmtT(w.t)}<br>${latS(w.lat)} ${lonS(w.lon)}<br>cap ${deg(w.heading)} · ${sailLabel(w.sail)}<br>${w.reason}`, { className: "wp-tip" })
      .addTo(layers.wps);
  }
  if ($("#show-prev").checked && R.comparison?.previous_track)
    L.polyline(R.comparison.previous_track, { color: "#8b9bab", weight: 2, dashArray: "6 6", opacity: 0.8 }).addTo(layers.prev);
  if ($("#show-iso").checked)
    for (const iso of R.isochrones || []) {
      const pts = iso.lat.map((a, k) => [a, iso.lon[k]]);
      L.polyline(pts, { color: "#4cc3d9", weight: 0.6, opacity: 0.35, interactive: false }).addTo(layers.iso);
    }
  fitOnce();
}
function fitOnce() {
  // La carte n'a de taille qu'une fois son onglet visible : on cadre la route à ce moment-là.
  const R = state.route, el = $("#map");
  if (fitOnce.done || !R || !el.clientHeight) return;
  map.invalidateSize();
  map.fitBounds(L.latLngBounds(R.track.map((p) => [p[0], p[1]])), { padding: [12, 12] });
  fitOnce.done = true;
}
function setupSlider() {
  const W = state.wind, s = $("#slider");
  if (!W) return;
  s.max = W.frames.length - 1;
  const t0 = Math.max(Date.now(), state.route ? ts(state.route.start_time) : 0);
  let k = W.frames.findIndex((f) => ts(f.t) >= t0 - 3 * 3600e3);
  if (state.slider && state.slider <= s.max) k = state.slider;
  s.value = Math.max(0, k); state.slider = +s.value;
}
function drawWind() {
  layers.wind.clearLayers();
  drawFill();
  const W = state.wind; if (!W) return;
  const fr = W.frames[state.slider]; if (!fr) return;
  const lead = Math.round((ts(fr.t) - ts(W.run)) / 3600e3);
  $("#wx-time").innerHTML = `Vent du ${fmtT(fr.t)}<small>${cycleS(state.status?.weather?.cycle)} +${lead} h</small>`;
  if (!$("#show-wind").checked) return;
  const a = frameData(state.slider), n = W.nlat * W.nlon, b = map.getBounds().pad(0.1);
  const z = map.getZoom(), stride = z <= 3 ? 4 : z === 4 ? 2 : 1;
  for (let j = 0; j < W.nlat; j += stride) for (let i = 0; i < W.nlon; i += stride) {
    const lat = W.lat0 + j * W.step, lon = W.lon0 + i * W.step;
    if (!b.contains([lat, lon])) continue;
    const u = a[j * W.nlon + i] * W.scale_ms, v = a[n + j * W.nlon + i] * W.scale_ms;
    const kt = Math.hypot(u, v) / 0.514444; if (kt < 0.5) continue;
    const len = 0.32 * W.step * stride, ang = Math.atan2(u, v); // vers où va le vent
    const dy = Math.cos(ang) * len, dx = Math.sin(ang) * len / Math.cos(lat * Math.PI / 180);
    const tip = [lat + dy, lon + dx], tail = [lat - dy, lon - dx];
    const side = 0.35 * len;
    const l1 = [tip[0] - Math.cos(ang - 0.5) * side, tip[1] - Math.sin(ang - 0.5) * side / Math.cos(lat * Math.PI / 180)];
    const l2 = [tip[0] - Math.cos(ang + 0.5) * side, tip[1] - Math.sin(ang + 0.5) * side / Math.cos(lat * Math.PI / 180)];
    const col = WIND_BANDS[windBand(kt)][1];
    L.polyline([tail, tip, l1, tip, l2], { color: col, weight: 1.2, opacity: 0.85, interactive: false }).addTo(layers.wind);
  }
}
// Fond coloré par force du vent : on voit d'un coup les zones sans vent et les couloirs de vent fort.
// L'image est rééchantillonnée en Mercator (comme la carte) pour tomber juste sous les flèches.
const fill = { layer: null, w: null, k: -1 };
function drawFill() {
  const W = state.wind, on = W && $("#show-fill").checked && W.frames[state.slider];
  if (on && fill.layer && fill.w === W && fill.k === state.slider) return;
  if (fill.layer) { fill.layer.remove(); fill.layer = null; }
  if (!on) return;
  const a = frameData(state.slider), n = W.nlat * W.nlon, sp = new Float32Array(n);
  for (let k = 0; k < n; k++) sp[k] = Math.hypot(a[k], a[n + k]) * W.scale_ms / 0.514444;
  const lat1 = W.lat0 + (W.nlat - 1) * W.step, lon1 = W.lon0 + (W.nlon - 1) * W.step;
  const merc = (lat) => Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360)), y0 = merc(W.lat0), y1 = merc(lat1);
  const w = W.nlon * 4, h = W.nlat * 6, cv = document.createElement("canvas"); cv.width = w; cv.height = h;
  const cx = cv.getContext("2d"), img = cx.createImageData(w, h);
  const rgb = WIND_BANDS.map(([, c]) => [1, 3, 5].map((x) => parseInt(c.slice(x, x + 2), 16)));
  for (let py = 0; py < h; py++) {
    const lat = Math.atan(Math.sinh(y1 - (py + 0.5) / h * (y1 - y0))) * 180 / Math.PI;
    const fj = Math.min(Math.max((lat - W.lat0) / W.step, 0), W.nlat - 1.001), j = Math.floor(fj), dj = fj - j;
    for (let px = 0; px < w; px++) {
      const fi = Math.min((px + 0.5) / w * (W.nlon - 1), W.nlon - 1.001), i = Math.floor(fi), di = fi - i, k = j * W.nlon + i;
      const s = (sp[k] * (1 - di) + sp[k + 1] * di) * (1 - dj) + (sp[k + W.nlon] * (1 - di) + sp[k + W.nlon + 1] * di) * dj;
      const c = rgb[windBand(s)], o = (py * w + px) * 4;
      img.data[o] = c[0]; img.data[o + 1] = c[1]; img.data[o + 2] = c[2]; img.data[o + 3] = 80;
    }
  }
  cx.putImageData(img, 0, 0);
  fill.layer = L.imageOverlay(cv.toDataURL(), [[W.lat0, W.lon0], [lat1, lon1]], { pane: "fill", interactive: false }).addTo(map);
  fill.w = W; fill.k = state.slider;
}
// Grille lat/lon, plus fine quand on zoome, valeurs au bord : pour retrouver une position du jeu sur la carte.
const gridS = (v, pos, neg) => {
  const tm = Math.round(Math.abs(v) * 60), m = tm % 60;
  return `${Math.floor(tm / 60)}°${m ? `${pad(m)}'` : ""} ${v >= 0 ? pos : neg}`;
};
function drawGrid() {
  layers.grid.clearLayers();
  if (!$("#show-grid").checked) return;
  const z = map.getZoom(), st = z < 4 ? 10 : z < 5 ? 5 : z < 6 ? 2 : z < 7.5 ? 1 : z < 9 ? 0.5 : 1 / 6;
  const b = map.getBounds(), s = Math.max(b.getSouth(), -85), nn = Math.min(b.getNorth(), 85), we = b.getWest(), ea = b.getEast();
  const line = { renderer: gridRenderer, color: "#8fa0b1", weight: 0.6, opacity: 0.4, interactive: false };
  const lab = (txt, ll, cls) => L.marker(ll, { interactive: false, keyboard: false,
    icon: L.divIcon({ className: `grid-lab ${cls}`, html: `<span>${txt}</span>`, iconSize: null }) }).addTo(layers.grid);
  for (let k = Math.ceil(s / st); k * st <= nn; k++) {
    const la = k * st;
    L.polyline([[la, we], [la, ea]], line).addTo(layers.grid); lab(gridS(la, "N", "S"), [la, we], "lat");
  }
  for (let k = Math.ceil(we / st); k * st <= ea; k++) {
    const lo = k * st;
    L.polyline([[s, lo], [nn, lo]], line).addTo(layers.grid); lab(gridS(lo, "E", "W"), [nn, lo], "lon");
  }
}
// Règle : deux touches sur la carte donnent le cap et la distance en loxodromie, comme un cap fixe dans le jeu.
const ruler = { on: false, pts: [] };
function rhumb(a, b) {
  const r = Math.PI / 180, p1 = a.lat * r, p2 = b.lat * r, dl = (b.lng - a.lng) * r;
  const dpsi = Math.log(Math.tan(Math.PI / 4 + p2 / 2) / Math.tan(Math.PI / 4 + p1 / 2));
  const q = Math.abs(dpsi) > 1e-12 ? (p2 - p1) / dpsi : Math.cos(p1);
  return { cap: Math.atan2(dl, dpsi) / r, nm: Math.hypot(p2 - p1, q * dl) * 3440.065 };
}
function toggleRuler(btn) {
  ruler.on = !ruler.on; ruler.pts = []; layers.ruler.clearLayers();
  btn.classList.toggle("on", ruler.on);
  map.getContainer().classList.toggle("measuring", ruler.on);
}
function rulerClick(e) {
  if (!ruler.on) return;
  if (ruler.pts.length === 2) { ruler.pts = []; layers.ruler.clearLayers(); }
  ruler.pts.push(e.latlng);
  const [a, b] = ruler.pts, dot = (ll) => L.circleMarker(ll, { radius: 4, color: "#fff", weight: 2, fillColor: "#f2b84b", fillOpacity: 1 });
  if (!b) { dot(a).bindTooltip("Touche l'arrivée", { className: "wp-tip", permanent: true, direction: "top" }).addTo(layers.ruler); return; }
  layers.ruler.clearLayers();
  const { cap, nm } = rhumb(a, b);
  L.polyline([a, b], { color: "#f2b84b", weight: 2, dashArray: "6 5", interactive: false }).addTo(layers.ruler);
  dot(a).addTo(layers.ruler);
  dot(b).bindTooltip(`cap ${deg(cap)} · ${nm.toFixed(1).replace(".", ",")} milles`,
    { className: "wp-tip", permanent: true, direction: "top" }).addTo(layers.ruler);
}
function drawBoat() {
  layers.boat.clearLayers();
  if (!state.route) return;
  // Anneau : le bateau maintenant (la route part de la dernière position envoyée) ; point plein : à l'heure du curseur.
  const now = trackAt(Date.now());
  if (now) L.circleMarker([now.lat, now.lon], { radius: 10, color: "#4cc3d9", weight: 2, fill: false })
    .bindTooltip("Bateau maintenant (estimé)", { className: "wp-tip" }).addTo(layers.boat);
  const fr = state.wind?.frames[state.slider]; if (!fr) return;
  const at = trackAt(ts(fr.t)); if (!at) return;
  L.circleMarker([at.lat, at.lon], { radius: 7, color: "#fff", weight: 2, fillColor: "#4cc3d9", fillOpacity: 1 })
    .bindTooltip(`Bateau prévu ${fmtT(fr.t)}`, { className: "wp-tip" }).addTo(layers.boat);
}
function centerBoat() {
  const at = trackAt(Date.now()); if (!at) return;
  map.setView([at.lat, at.lon], Math.max(map.getZoom(), 7));
}

// --- actions (serveur local seulement) --------------------------------------------------------
async function detectApi() {
  try { const r = await fetch("/api/ping", { cache: "no-store" }); state.api = r.ok; } catch { state.api = false; }
  $("#actions").hidden = !state.api;
  // Version publiée sur GitHub Pages : position, options et recalcul passent par le relais ntfy.
  $("#gh").hidden = state.api || !/\.github\.io$/.test(location.hostname);
  $("#relay").hidden = state.api || !state.topic;
}
function fillForm() {
  const R = state.route; if (!R) return;
  for (const f of [$("#pos-form"), $("#relay-form")]) {
    f.sail.innerHTML = `<option value="">je ne sais pas</option>` + R.sail_names.map((s) => `<option value="${s}">${sailLabel(s)}</option>`).join("");
    f.gate.innerHTML = R.gates.map((g, k) => `<option value="${k}">${g.name}</option>`).join("");
    f.gate.onchange = () => (f.gate.dataset.touched = "1");
  }
  nextGate();
}
// Prochaine marque proposée : la première que la route n'a pas encore passée (Porte Fréhel juste après le départ),
// sauf si on l'a changée à la main.
function nextGate() {
  const R = state.route; if (!R?.gates) return;
  const passed = (g) => R.waypoints.some((w) => w.reason === `Porte : ${g.name}` && ts(w.t) <= Date.now());
  const k = R.gates.findIndex((g) => !passed(g));
  for (const f of [$("#pos-form"), $("#relay-form")])
    if (!f.gate.dataset.touched && f.gate.options.length) f.gate.value = String(k < 0 ? R.gates.length - 1 : k);
}
async function post(path, body) {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok && r.status !== 409) throw new Error(j.error || `erreur ${r.status}`);
  return j;
}
async function pollJob() {
  try {
    const j = await getJSON("/api/job");
    $("#job").textContent = j.state === "en cours" ? `Calcul en cours (${j.label})…` : j.state === "erreur" ? `Échec : ${j.message}` : j.state === "terminé" ? `Terminé ${fmtT(j.finished_at)}` : "";
    if (j.state === "en cours") setTimeout(pollJob, 4000); else refresh();
  } catch { /* serveur arrêté */ }
}

// --- scénarios météo ---------------------------------------------------------------------------
// Quelle route suivre : une seule réponse avec sa raison, au lieu de comparer deux routes à la main (01/11).
const MIN_GAIN_H = 1;   // en dessous, l'écart entre les deux routes ne dépasse pas l'imprécision du calcul
function verdict() {
  const M = state.main, S = state.safe, e = state.ens;
  if (!M) return null;
  const gfs = (why) => ({ id: "gfs", why }), safe = (why) => ({ id: "safe", why });
  const failed = "échoue au contrôle : un de ses ordres, rejoué dans la météo du jeu, mène dans une zone interdite ou à la côte.";
  if (M.guard && !M.guard.ok && S && S.guard?.ok) return safe(`la route GFS ${failed}`);
  if (!e) return gfs("les scénarios météo ne sont pas encore calculés.");
  if (e.recommended === "gfs" || !S) return gfs(`c'est aussi la meilleure sur les ${e.judges} versions de la météo.`);
  if (S.guard && !S.guard.ok) return gfs(`la route conseillée ${failed}`);
  const lp = M.last_position;
  if (lp && ts(lp.time) > ts(S.start_time) + 10 * 60e3)
    return gfs(`la route conseillée part de ta position de ${hm(S.start_time)}, d'avant ta dernière position. Elle sera recalculée dans l'heure.`);
  const g = e.gain_vs_gfs_h ?? 0;
  if (g < MIN_GAIN_H) return gfs(`la route conseillée ne gagne que ${Math.max(0, Math.round(g * 60))} min, pas assez pour changer.`);
  return safe(`elle arrive ${fr1(g)} h plus tôt que la route GFS en moyenne sur ${e.judges} versions de la météo, et ses ordres passent le contrôle.`);
}
function pickRoute() {
  // Route affichée partout : celle du verdict, sauf si un bouton a été touché pendant cette visite.
  const useSafe = (state.choice || verdict()?.id) === "safe" && state.safe;
  state.route = useSafe ? state.safe : state.main;
  document.querySelectorAll(".choice button").forEach((b) => b.classList.toggle("on", b.dataset.c === (useSafe ? "safe" : "gfs")));
  document.querySelectorAll(".choice").forEach((el) => (el.hidden = !state.safe));
}
// Fiabilité d'une route : largeur de la fourchette « 8 cas sur 10 » de ses arrivées.
function confidence(r) {
  const h = (ts(r.p90_eta) - ts(r.p10_eta)) / 3600e3;
  return { h, label: h < 8 ? "élevée" : h < 20 ? "moyenne" : "faible", cls: h < 8 ? "ok" : h < 20 ? "warn" : "bad", r };
}
function renderScenarios() {
  const e = state.ens, st = state.ensSt, el = $("#scen");
  const busy = st && (st.state === "téléchargement" || st.state === "calcul");
  if (!e && !busy) { el.innerHTML = ""; return; }
  let h = `<h3>Scénarios météo</h3>`;
  if (busy) h += `<p class="warn">${st.message}…</p><div class="bar"><i style="width:${Math.round(100 * st.done / Math.max(st.total, 1))}%"></i></div>`;
  if (e) {
    const r = e.candidates.find((x) => x.id === e.recommended), c = confidence(r);
    const same = e.recommended === "gfs";
    h += `<p>${e.judges} versions de la météo testées (${cycleS(e.gefs_cycle).replace("GFS", "GEFS")}). Fiabilité
      <b class="${c.cls}">${c.label}</b> : ${Math.round(c.h)} h d'écart entre les cas.</p>
      <p>${same ? "La route GFS est aussi la plus sûre : elle tient dans la plupart des scénarios."
        : `La route conseillée est plus sûre que la route GFS seule : <b>${Math.abs(e.gain_vs_gfs_h).toFixed(1).replace(".", ",")} h ${e.gain_vs_gfs_h >= 0 ? "gagnées" : "perdues"}</b> en moyenne sur les scénarios.`}</p>
      <p class="note">${same || r.beats_gfs == null ? "" : `Elle fait mieux que la route GFS dans ${r.beats_gfs} scénarios sur ${e.judges}. `}Méthode : chaque route est suivie ${e.commit_h} h dans chaque scénario, puis on suppose un recalcul. Mise à jour ${fmtT(e.computed_at)}.</p>`;
  }
  el.innerHTML = h;
}

// --- boucle -----------------------------------------------------------------------------------
async function refresh() {
  const boat = state.boat;
  const [st, wx, bst] = await Promise.allSettled([getJSON("data/status.json"), getJSON("data/weather-status.json"),
    getJSON(bpath("status.json"))]);
  if (boat !== state.boat) return; // bateau changé pendant le chargement
  // Ancienne version (un seul bateau) : l'état de la route est dans status.json.
  if (st.value) state.status = { ...st.value, route: bst.value || st.value.route };
  state.wx = wx.value || state.wx;
  if (!state.main || state.status?.route?.computed_at !== state.main.computed_at) {
    try { state.main = await getJSON(bpath("route.json")); } catch { /* pas encore de route */ }
  }
  try { state.ensSt = await getJSON("data/ensemble-status.json"); } catch { state.ensSt = null; }
  try { state.expl = await getJSON(bpath("explain.json")); } catch { state.expl = null; }
  try {
    const e = await getJSON(bpath("ensemble.json"));
    if (e.computed_at !== state.ens?.computed_at) {
      state.ens = e;
      state.safe = e.recommended !== "gfs" ? await getJSON(bpath("route-safe.json")).catch(() => null) : null;
    }
  } catch { state.ens = null; state.safe = null; }
  try { const b = await getJSON("data/boats.json"); if (Array.isArray(b?.boats) && b.boats.length) state.boats = b.boats; } catch { /* inchangé */ }
  if (boat !== state.boat) return;
  checkPending(); checkSentOpts(); renderSetup();
  pickRoute();
  const run = state.status?.weather?.run;
  if (!state.wind || (run && state.wind.run.slice(0, 13) !== run.slice(0, 13))) {
    try { state.wind = await getJSON("data/wind.json"); frameCache.clear(); setupSlider(); } catch { /* pas de vent */ }
  }
  renderStatus(); renderAll(); renderMeteo();
  if (map) { drawRoute(); drawWind(); drawBoat(); drawGrid(); }
  if (state.route && !fillForm.done) { fillForm(); fillForm.done = true; } else nextGate();
}

// --- bateaux ----------------------------------------------------------------------------------
async function loadBoats() {
  let b = null;
  try { b = await getJSON("data/boats.json"); } catch { /* ancienne version : un seul bateau */ }
  state.boats = Array.isArray(b) ? b : b?.boats || [];
  state.topic = Array.isArray(b) ? null : b?.ntfy_topic || null;
  if (!state.boats.length) return;
  const ids = state.boats.map((x) => x.id);
  const asked = new URLSearchParams(location.search).get("bateau");
  const id = ids.includes(asked) ? asked : ids.includes(store.get("bateau")) ? store.get("bateau") : ids[0];
  const el = $("#boats");
  el.innerHTML = state.boats.map((x) => `<button data-b="${x.id}">${x.name}</button>`).join("");
  el.hidden = state.boats.length < 2;
  el.onclick = (e) => { const t = e.target.closest("[data-b]"); if (t && t.dataset.b !== state.boat) setBoat(t.dataset.b); };
  setBoat(id, false);
}
function setBoat(id, reload = true) {
  state.boat = id; store.set("bateau", id);
  const url = new URL(location.href);
  if (state.boats.length > 1) { url.searchParams.set("bateau", id); history.replaceState(null, "", url); }
  document.querySelectorAll("#boats button").forEach((b) => b.classList.toggle("on", b.dataset.b === id));
  document.querySelectorAll("[data-file]").forEach((a) => (a.href = bpath(a.dataset.file)));
  document.title = state.boats.length > 1 ? `Routeur Rhum · ${boatName()}` : "Routeur Rhum · Ultim";
  $("#relay-boat").textContent = boatName();
  $("#alerts-boat").textContent = boatName();
  $("#alerts-topic").textContent = state.topic ? `${state.topic}-${id}` : "";
  $("#alerts").hidden = !state.topic;
  store.del(`code-${id}`);  // ancien code du bateau retenu sur ce téléphone : il ne sert plus
  $("#relay-msg").textContent = "";
  renderSetup();
  if (!reload) return;
  Object.assign(state, { main: null, safe: null, ens: null, expl: null, route: null });
  fitOnce.done = false;
  refresh().then(() => { if (map && $("#map").clientHeight) fitOnce(); });
}

// --- envoi sans compte (page publiée → ntfy.sh → routeur) ---------------------------------------
function relayPreview() {
  const f = $("#relay-form"), lat = parseGame(f.lat.value, true), lon = parseGame(f.lon.value, false);
  $("#relay-preview").textContent = f.lat.value && f.lon.value
    ? (Number.isNaN(lat) || Number.isNaN(lon) ? "Position illisible" : `Compris : ${latS(lat)}  ${lonS(lon)}`) : "";
}
// Publie un message pour le bateau affiché. Renvoie l'heure d'envoi (s), ou 0 si l'envoi a échoué.
async function sendRelay(fields, btn, msg, what) {
  if (!state.topic) { msg.textContent = "L'envoi n'est pas disponible sur cette page."; return 0; }
  const t = Date.now() / 1000;
  btn.disabled = true; msg.textContent = "Envoi…";
  try {
    const data = JSON.stringify({ bateau: state.boat, ...fields, t });
    const r = await fetch(`https://ntfy.sh/${state.topic}`, { method: "POST", body: JSON.stringify({ data }) });
    if (!r.ok) throw new Error(`erreur ${r.status}`);
    if (what) store.set(`pending-${state.boat}`, JSON.stringify({ t, what }));
    msg.textContent = "";
    renderTodo();
    return t;
  } catch (err) { msg.textContent = `Envoi impossible (${err.message}). Vérifie la connexion et réessaie.`; return 0; }
  finally { btn.disabled = false; }
}
async function sendPosition(e) {
  e.preventDefault();
  const f = e.target, lat = parseGame(f.lat.value, true), lon = parseGame(f.lon.value, false);
  const msg = $("#relay-msg");
  if (Number.isNaN(lat) || Number.isNaN(lon)) { msg.textContent = "Latitude ou longitude illisible."; return; }
  if (lat < 5 || lat > 55 || lon < -70 || lon > 5) { msg.textContent = "Cette position est hors du parcours : vérifie N/S et E/W."; return; }
  // TWA : degrés (0 à 180) + bâbord/tribord, envoyée signée au routeur (bâbord = négative).
  let twa = "";
  const deg = f.twa.value.trim().replace(",", ".");
  if (deg) {
    const v = Math.abs(Number(deg));
    if (Number.isNaN(v) || v > 180) { msg.textContent = "TWA illisible : un nombre de 0 à 180."; f.twa.focus(); return; }
    if (!f.side.value && v > 0 && v < 180) { msg.textContent = "Pour le TWA, choisis bâbord ou tribord."; return; }
    twa = String(f.side.value === "-1" ? -v : v);
  }
  const ok = await sendRelay({ lat, lon, voile: f.sail.value, porte: +f.gate.value, twa },
    f.querySelector("button[type=submit]"), msg, "Position envoyée");
  if (!ok) return;
  msg.textContent = `Position ${latS(lat)} ${lonS(lon)} envoyée. ${SOON}`;
  f.lat.value = ""; f.lon.value = ""; f.twa.value = ""; f.querySelectorAll("[name=side]").forEach((r) => (r.checked = false));
  relayPreview();
}
// « -125 » tapé ou collé : 125 bâbord.
function twaInput(e) {
  const t = e.target;
  if (t.name !== "twa" || !t.value.trim().startsWith("-")) return;
  t.value = t.value.trim().slice(1);
  t.form.querySelector('input[name=side][value="-1"]').checked = true;
}
const SOON = "Nouvelle route dans 5 à 15 min : la page se met à jour toute seule.";
async function askRecalc(e) {
  if (await sendRelay({ action: "recalcul" }, e.currentTarget, $("#relay-msg"), "Recalcul demandé"))
    $("#relay-msg").textContent = `Recalcul demandé. ${SOON}`;
}

// --- rappel pour revenir : fin des ordres programmés dans le jeu -------------------------------------
const RETURN_BEFORE_MS = 45 * 60e3;  // RETURN_BEFORE_MIN du routeur (alerts.py)
// Heure (s) où s'arrêtent les ordres programmés, gardée sur ce téléphone ; 0 si aucune.
function progUntil() {
  try { return JSON.parse(store.get(`prog-${state.boat}`, "") || "null")?.until || 0; } catch { return 0; }
}
// « 18:40 » aujourd'hui, « lun. 2 18:40 » un autre jour.
const whenS = (t) => (new Date(t).toDateString() === new Date().toDateString() ? hm(t) : `${dtDayShort.format(new Date(t))} ${hm(t)}`);
function renderProg() {
  const R = state.route, sel = $("#prog-last"), now = Date.now();
  if (!R) { sel.innerHTML = ""; return; }
  const W = R.waypoints, until = progUntil();
  // Chaque ordre court jusqu'au waypoint suivant (ou l'arrivée) : c'est l'heure où il faut avoir programmé la suite.
  const opts = W.map((w, k) => ({ w, end: ts(W[k + 1]?.t || R.eta) })).filter((o) => o.end > now && o.end - now < 72 * 3600e3);
  sel.innerHTML = `<option value="">Dernier ordre entré dans le jeu…</option>` + opts.map(({ w, end }) =>
    `<option value="${end / 1000}" ${Math.abs(end / 1000 - until) < 60 ? "selected" : ""}>WP${pad(w.n)} · ${whenS(ts(w.t))} · ${orderTxt(w)}</option>`).join("");
  if (!$("#prog-msg").dataset.busy)
    $("#prog-msg").textContent = until * 1000 > now ? `Rappel vers ${whenS(until * 1000 - RETURN_BEFORE_MS)}. Reviens avant ${whenS(until * 1000)}.` : "";
}
async function sendProg(e) {
  const until = Number($("#prog-last").value), msg = $("#prog-msg");
  if (!until) { msg.textContent = "Choisis d'abord le dernier ordre que tu as entré dans le jeu."; return; }
  msg.dataset.busy = "1";
  const t = await sendRelay({ action: "programme", jusqu: until }, e.currentTarget, msg, null);
  delete msg.dataset.busy;
  if (!t) return;
  store.set(`prog-${state.boat}`, JSON.stringify({ t, until }));
  renderProg(); renderTodo();
  toast(`Rappel vers ${whenS(until * 1000 - RETURN_BEFORE_MS)}`);
}

// --- options du bateau : obligatoires avant le reste, le routeur calcule toute la route avec -------
const curBoat = () => state.boats.find((b) => b.id === state.boat);
// Options envoyées depuis ce téléphone que le routeur n'a pas encore publiées dans boats.json.
function sentOpts() {
  try { return JSON.parse(store.get(`opts-${state.boat}`, "") || "null"); } catch { return null; }
}
function chosenOpts() {
  const b = curBoat(), sent = sentOpts();
  return sent ? sent.options : b?.options_set ? b.options : null;
}
const sameOpts = (a, b) => !!a && !!b && OPTIONS.every(([k]) => !!a[k] === !!b[k]);
const optsSummary = (o) => OPTIONS.filter(([k]) => o[k]).map(([, n]) => n).join(", ") || "Aucune option : bateau de base.";
let setupOpen = false;  // écran rouvert par « Modifier mes options »
function renderSetup() {
  const b = curBoat(), chosen = chosenOpts();
  const gate = !!state.topic && !!b && (setupOpen || !chosen);
  const was = document.body.classList.contains("gated");
  document.body.classList.toggle("gated", gate);
  $("#setup-boat").textContent = state.boats.length > 1 ? boatName() : "ton bateau";
  $("#setup-cancel").hidden = !chosen;
  $("#opts-card").hidden = !b || !state.topic;
  $("#opts-boat").textContent = boatName();
  $("#opts-sum").textContent = chosen ? optsSummary(chosen) : "Pas encore choisies.";
  if (gate && !was) {  // cases remplies à l'ouverture seulement, pas pendant qu'on coche
    const cur = chosen || {};
    $("#setup-list").innerHTML = OPTIONS.map(([k, name, help]) => `<label class="opt switch"><span><b>${name}</b><small>${help}</small></span>
      <input type="checkbox" name="${k}" ${cur[k] ? "checked" : ""}></label>`).join("");
    $("#setup-msg").textContent = "";
    setupCount();
  }
}
function setupCount() {
  const n = OPTIONS.filter(([k]) => $("#setup-form")[k]?.checked).length;
  $("#setup-ok").textContent = n === OPTIONS.length ? "Valider : pack complet"
    : n ? `Valider : ${n} option${n > 1 ? "s" : ""}` : "Valider : aucune option";
}
async function sendOptions(e) {
  e.preventDefault();
  const f = e.target, options = Object.fromEntries(OPTIONS.map(([k]) => [k, f[k].checked]));
  const t = await sendRelay({ action: "options", options }, $("#setup-ok"), $("#setup-msg"), "Options envoyées");
  if (!t) return;
  store.set(`opts-${state.boat}`, JSON.stringify({ t, options }));
  setupOpen = false; renderSetup(); showTab("bord");
  toast("Options envoyées : nouvelle route dans 5 à 15 min");
}
// boats.json à jour (le routeur a reçu les options) : celles gardées sur le téléphone ne servent plus.
function checkSentOpts() {
  const b = curBoat(), sent = sentOpts();
  if (sent && b?.options_set && (sameOpts(b.options, sent.options) || ts(state.main?.computed_at) / 1000 > sent.t + 60))
    store.del(`opts-${state.boat}`);
}
// Position envoyée mais pas encore prise en compte ? (effacée dès qu'une route plus récente est publiée)
function pending() {
  try { return JSON.parse(store.get(`pending-${state.boat}`, "") || "null"); } catch { return null; }
}
function checkPending() {
  const p = pending(), R = state.main;
  if (p && R && ts(R.published_at || R.computed_at) / 1000 >= p.t) store.set(`pending-${state.boat}`, "");
}

function showTab(name) {
  document.querySelectorAll(".tabs button").forEach((x) => {
    x.classList.toggle("on", x.dataset.tab === name);
    if (x.dataset.tab === name) x.setAttribute("aria-current", "page"); else x.removeAttribute("aria-current");
  });
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.id === `tab-${name}`));
  if (name === "carte") setTimeout(() => { map.invalidateSize(); fitOnce(); drawWind(); drawGrid(); }, 50);
}
const renderAll = () => { renderTodo(); renderNotes(); renderScenarios(); renderBord(); renderRoute(); renderProg(); };

function initUi() {
  state.fmt = store.get("fmt", "dms");
  // Route affichée = verdict ; un bouton la change pour cette visite seulement.
  state.choice = null;
  const choose = (c) => { state.choice = c; pickRoute(); renderAll(); if (map) { drawRoute(); drawBoat(); } };
  document.querySelectorAll(".choice button").forEach((b) => (b.onclick = () => choose(b.dataset.c)));
  const sel = $("#fmt");
  sel.value = state.fmt;
  sel.onchange = () => { state.fmt = sel.value; store.set("fmt", state.fmt); renderRoute(); renderBord(); };
  $("#only-next").onchange = renderRoute;
  $("#relay-form").onsubmit = sendPosition;
  $("#relay-recalc").onclick = askRecalc;
  $("#alerts-copy").onclick = () => copyText($("#alerts-topic").textContent);
  $("#relay-form").oninput = (e) => { twaInput(e); relayPreview(); };
  $("#setup-form").onsubmit = sendOptions;
  $("#prog-ok").onclick = sendProg;
  $("#setup-form").onchange = setupCount;
  $("#setup-all").onclick = () => { OPTIONS.forEach(([k]) => ($("#setup-form")[k].checked = true)); setupCount(); };
  $("#setup-cancel").onclick = () => { setupOpen = false; renderSetup(); };
  $("#opts-edit").onclick = () => { setupOpen = true; renderSetup(); };
  document.querySelectorAll(".tabs button").forEach((b) => (b.onclick = () => showTab(b.dataset.tab)));
  document.body.addEventListener("click", (e) => {
    const c = e.target.closest("[data-copy]"); if (c) copyText(c.dataset.copy);
    const g = e.target.closest("[data-go]"); if (g) showTab(g.dataset.go);
    if (e.target.closest("[data-follow]")) choose(null);
  });
  $("#btn-recalc").onclick = async () => { try { const j = await post("/api/recalcul"); toast(j.accepted ? "Recalcul lancé" : "Un calcul est déjà en cours"); pollJob(); } catch (err) { toast(err.message); } };
  $("#pos-form").onsubmit = async (e) => {
    e.preventDefault();
    const f = e.target, lat = parseCoord(f.lat.value, true), lon = parseCoord(f.lon.value, false);
    if (Number.isNaN(lat) || Number.isNaN(lon)) { toast("Coordonnées illisibles"); return; }
    try { await post("/api/position", { bateau: state.boat, lat, lon, voile: f.sail.value, porte: +f.gate.value, twa: f.twa.value });
      toast(`Position ${latS(lat)} ${lonS(lon)} enregistrée`); pollJob(); } catch (err) { toast(err.message); }
  };
}

(async function main() {
  initUi(); initMap(); await loadBoats(); await detectApi(); await loadStatic(); await refresh();
  setInterval(refresh, 60000);
})();
