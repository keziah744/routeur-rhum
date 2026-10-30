/* Routeur Rhum · interface cockpit. Lit les fichiers publiés dans data/ ; l'API locale est facultative. */
"use strict";

const SAIL_COLORS = { Jib: "#8ecae6", Spi: "#ffb703", Staysail: "#2a9dc0", LightJib: "#a7c957",
  Code0: "#ef7b5a", HeavyGnk: "#f4a261", LightGnk: "#c8a2e0" };
// Noms des voiles tels qu'affichés dans la version française du jeu.
const SAIL_FR = { Jib: "Foc", Spi: "Spi", Staysail: "Trinquette", LightJib: "Foc léger", Code0: "Code 0",
  HeavyGnk: "Gennaker lourd", LightGnk: "Gennaker léger" };
const sailFr = (s) => SAIL_FR[s] || s;
const $ = (s) => document.querySelector(s);
const state = { route: null, main: null, safe: null, ens: null, ensSt: null, choice: "safe",
  status: null, wx: null, wind: null, api: false, fmt: "dms", slider: 0, boats: [], boat: null, topic: null };
const store = {
  get(k, d) { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* stockage indisponible */ } },
};

// --- formats ----------------------------------------------------------------------------------
const ts = (iso) => (iso ? Date.parse(iso) : NaN);
const dtLocal = new Intl.DateTimeFormat("fr-FR", { weekday: "short", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
const dtUtc = new Intl.DateTimeFormat("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", timeZone: "UTC" });
const dtGwada = new Intl.DateTimeFormat("fr-FR", { weekday: "short", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", timeZone: "America/Guadeloupe" });
const fmtT = (iso) => (iso ? dtLocal.format(new Date(iso)) : "–");
const fmtZ = (iso) => (iso ? dtUtc.format(new Date(iso)).replace(" ", " ") + " UTC" : "");
const pad = (n, w = 2) => String(n).padStart(w, "0");

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
const twaS = (v) => `${v > 0 ? "+" : ""}${Math.round(v)}°`;
const hoursS = (h) => `${Math.floor(h / 24)} j ${pad(Math.round(h % 24))} h`;

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
function renderBord() {
  const R = state.route, S = state.status;
  if (!R) { $("#eta").textContent = "–"; $("#eta-sub").textContent = "Aucune route calculée"; return; }
  const now = Date.now();
  const names = R.sail_names;
  // Avec les scénarios : l'arrivée la plus probable (médiane) de la route affichée, et sa fourchette.
  const cand = state.ens?.candidates.find((c) => c.id === (state.route === state.safe ? state.ens.recommended : "gfs"));
  if (cand?.median_eta) {
    $("#eta-label").textContent = "Arrivée la plus probable";
    $("#eta").textContent = fmtT(cand.median_eta);
    $("#eta-sub").textContent = `8 cas sur 10 : ${fmtT(cand.p10_eta)} – ${fmtT(cand.p90_eta)} · Guadeloupe ${dtGwada.format(new Date(cand.median_eta))}`;
  } else {
    $("#eta-label").textContent = "Arrivée estimée";
    $("#eta").textContent = R.eta ? fmtT(R.eta) : "non atteinte";
    $("#eta-sub").textContent = R.eta ? `${fmtZ(R.eta)} · Guadeloupe ${dtGwada.format(new Date(R.eta))} · ${hoursS(R.duration_h)} de course` : "Arrivée hors de la durée de calcul";
  }
  const at = trackAt(now);
  const cur = at && !at.before ? at : { i: 0, lat: R.track[0][0], lon: R.track[0][1], p: R.track[0] };
  let rest = 0; const tr = R.track;
  if (cur) { rest += hav(cur.lat, cur.lon, tr[Math.min(cur.i + 1, tr.length - 1)][0], tr[Math.min(cur.i + 1, tr.length - 1)][1]);
    for (let k = cur.i + 1; k < tr.length - 1; k++) rest += hav(tr[k][0], tr[k][1], tr[k + 1][0], tr[k + 1][1]); }
  $("#dist").textContent = Math.round(rest).toLocaleString("fr-FR");
  const p = cur.p;
  $("#spd").textContent = `${p[6].toFixed(1)} kt`;
  $("#spd-sub").textContent = at?.before ? "au départ" : "selon la route, maintenant";
  const wd = windAt(cur.lat, cur.lon, Math.max(now, ts(R.start_time)));
  $("#wind").textContent = wd ? `${deg(wd.twd)} ${wd.tws.toFixed(0)} kt` : `${p[4].toFixed(0)} kt`;
  $("#wind-sub").textContent = `TWA ${twaS(p[5])} sur la route`;
  $("#sail").textContent = sailFr(names[p[3]]);
  $("#sail-sub").innerHTML = `<span class="sw" style="background:${SAIL_COLORS[names[p[3]]] || "#999"}"></span>voile recommandée`;

  const nextWp = R.waypoints.find((w) => ts(w.t) > now) || R.waypoints[0];
  $("#next-wp").innerHTML = nextWp ? `<h3>Prochain waypoint · WP${pad(nextWp.n)}</h3>
    <div class="line"><span class="big">${latS(nextWp.lat)}  ${lonS(nextWp.lon)}</span><button class="copy" data-copy="${latS(nextWp.lat)} ${lonS(nextWp.lon)}">Copier</button></div>
    <div class="line note"><span>${fmtT(nextWp.t)} · ${fmtZ(nextWp.t)}</span><span>cap ${deg(nextWp.heading)} · ${sailFr(nextWp.sail)}</span></div>
    <div class="note">${nextWp.reason}</div>` : "";
  const nextSail = R.sail_changes.find((c) => ts(c.t) > now);
  $("#next-sail").innerHTML = nextSail ? `<h3>Prochain changement de voile</h3>
    <div class="line"><span class="big">${sailFr(nextSail.sail_from)} → ${sailFr(nextSail.sail_to)}</span><span class="mono">+${nextSail.gain_pct} %</span></div>
    <div class="note">${fmtT(nextSail.t)} · ${latS(nextSail.lat)} ${lonS(nextSail.lon)} · TWA ${twaS(nextSail.twa)} · ${nextSail.tws} kt</div>` : "";
  const C = R.comparison;
  $("#cmp").innerHTML = C ? `<h3>Par rapport à la route précédente</h3>
    <div class="line"><span>ETA</span><b class="mono ${C.eta_delta_h > 0 ? "warn" : "ok"}">${C.eta_delta_h == null ? "–" : (C.eta_delta_h > 0 ? "+" : "") + C.eta_delta_h.toFixed(1) + " h"}</b></div>
    <div class="line"><span>Écart de trajectoire</span><b class="mono">max ${C.max_deviation_nm ?? "–"} nm · moy. ${C.mean_deviation_nm ?? "–"} nm</b></div>
    <div class="note">Ancienne route : ${C.previous_cycle ? "GFS " + C.previous_cycle.slice(6, 8) + "/" + C.previous_cycle.slice(4, 6) + " " + C.previous_cycle.slice(8) + "z" : "?"}, calculée ${fmtT(C.previous_computed_at)}</div>` : "";
  const w = S?.weather, r = S?.route;
  $("#states").innerHTML = `
    <dt>Météo</dt><dd class="${w?.stale ? "warn" : "ok"}">${w ? cycleS(w.cycle) + " · âge " + w.age_h.toFixed(1) + " h" : "–"}</dd>
    <dt>Mise à jour</dt><dd>${w ? fmtT(w.fetched_at) : "–"}</dd>
    <dt>Calcul de route</dt><dd class="${r?.state === "ok" ? "ok" : r?.state === "erreur" ? "bad" : "warn"}">${r ? r.state + (r.compute_s ? " · " + Math.round(r.compute_s) + " s" : "") : "–"}</dd>
    <dt>Calculée le</dt><dd>${fmtT(R.computed_at)}</dd>
    <dt>Départ du calcul</dt><dd>${R.start_source}</dd>`;
  const beyond = R.beyond_forecast_from ? ` Au-delà du ${fmtT(R.beyond_forecast_from)}, la route utilise la dernière échéance disponible.` : "";
  $("#disclaimer").textContent = `Route estimée, pas une optimale garantie : GFS 0,25° interpolé, pas de calcul variable, polaire ${R.boat} reconstruite et pénalités en partie supposées.${beyond}`;
}
const cycleS = (c) => (c ? `GFS ${c.slice(6, 8)}/${c.slice(4, 6)} ${c.slice(8)}z` : "–");

// Âge réel de la prévision (le fichier d'état peut dater) et durée lisible.
const wxAgeH = (w) => (w ? (Date.now() - ts(w.run)) / 3600e3 : NaN);
function until(ms) {
  const m = Math.max(0, Math.round(ms / 60000)), d = Math.floor(m / 1440), h = Math.floor((m % 1440) / 60);
  return d ? `${d} j ${h} h` : h ? `${h} h ${pad(m % 60)}` : `${m} min`;
}

function renderPills() {
  const w = state.status?.weather, r = state.status?.route, d = state.wx;
  const pw = $("#pill-wx"), pr = $("#pill-rt"), age = wxAgeH(w);
  if (d?.state === "téléchargement") { pw.className = "pill warn"; pw.textContent = `Météo ${d.done}/${d.total}`; }
  else if (!w) { pw.className = "pill bad"; pw.textContent = "Pas de météo"; }
  else { pw.className = `pill ${age > 9 ? "warn" : "ok"}`; pw.textContent = `Météo : il y a ${Math.round(age)} h`; }
  if (!r) { pr.className = "pill"; pr.textContent = "Pas de route"; }
  else { pr.className = `pill ${r.state === "ok" ? "ok" : r.state === "calcul" ? "warn" : "bad"}`;
    pr.textContent = r.state === "calcul" ? "Calcul en cours…" : r.state === "ok" ? "Route à jour" : "Route : problème"; }
}

// Carte « Maintenant » : où on en est, quoi faire, pourquoi la route a bougé — en phrases simples.
function renderNow() {
  const R = state.route, S = state.status, now = Date.now(), el = $("#now");
  if (!R) { el.innerHTML = `<h3>Maintenant</h3><p>Pas encore de route. Le PC en calcule une dès que la météo est arrivée.</p>`; return; }
  const start = ts(S?.race?.start_time || R.start_time), w = S?.weather, age = wxAgeH(w), C = R.comparison;
  const p = [];
  if (S?.route?.state === "calcul") p.push(`<p class="warn">Nouveau calcul en cours (environ 3 min)…</p>`);
  const pend = pending();
  if (pend) p.push((now / 1000 - pend.t > 1800)
    ? `<p class="warn">Position envoyée ${fmtT(new Date(pend.t * 1000).toISOString())}, toujours pas de nouvelle route après 30 min. Vérifie le code et renvoie-la.</p>`
    : `<p class="warn">Position envoyée ${fmtT(new Date(pend.t * 1000).toISOString())} : nouvelle route en préparation (5 à 15 min).</p>`);
  if (now < start) {
    p.push(`<p class="lead">Départ dans <b>${until(start - now)}</b> · ${fmtT(new Date(start).toISOString())}</p>`);
    p.push(`<p><b>Rien à faire pour l'instant.</b> La route se recalcule toute seule à chaque nouvelle météo (4 fois par jour).</p>`);
    p.push(`<p class="note">Elle va encore beaucoup bouger tant que le départ est loin : c'est normal, la météo à une semaine est incertaine.</p>`);
  } else if (!R.eta || now < ts(R.eta) + 6 * 3600e3) {
    const fromPos = /position saisie/.test(R.start_source);
    p.push(`<p class="lead"><b>Course en cours.</b></p>`);
    p.push(fromPos ? `<p>Route calculée depuis ta position saisie.</p>`
      : `<p class="warn"><b>À faire :</b> envoie ta position du jeu (onglet Météo). Sinon le routeur suppose que tu as suivi sa route.</p>`);
    const wp = R.waypoints.find((x) => ts(x.t) > now);
    if (wp) p.push(`<p>Prochain ordre dans le jeu : <b>WP${pad(wp.n)}</b> vers ${fmtT(wp.t).split(" ").pop()}, cap <b>${deg(wp.heading)}</b>, voile <b>${sailFr(wp.sail)}</b>.</p>`);
  } else p.push(`<p class="lead"><b>Course terminée.</b></p>`);
  if (state.ens) p.push(state.route === state.safe
    ? `<p>Route affichée : <b>la plus sûre</b> sur ${state.ens.judges} scénarios météo.</p>`
    : state.ens.recommended === "gfs" ? `<p>Route affichée : la route GFS, qui est aussi <b>la plus sûre</b> sur ${state.ens.judges} scénarios.</p>`
    : `<p class="warn">Route affichée : GFS seule. La route conseillée par les scénarios est différente.</p>`);
  if (age > 9) p.push(`<p class="warn">La météo date de ${Math.round(age)} h : le PC était sans doute en veille. Elle se remettra à jour toute seule.</p>`);
  if (C && C.eta_delta_h != null) {
    const d = C.eta_delta_h, same = Math.abs(d) < 0.5 && (C.mean_deviation_nm ?? 0) < 5;
    const dir = C.mean_lat_shift_deg > 0.3 ? ", plus au nord" : C.mean_lat_shift_deg < -0.3 ? ", plus au sud" : "";
    p.push(`<p class="note">Dernière mise à jour ${fmtT(R.computed_at)} (${cycleS(R.gfs_cycle)}) : ` + (same ? "route quasi identique."
      : `arrivée <b>${Math.abs(d).toFixed(1).replace(".", ",")} h ${d < 0 ? "plus tôt" : "plus tard"}</b>, route décalée de ${Math.round(C.mean_deviation_nm)} milles en moyenne${dir}.`) + `</p>`);
  }
  const x = state.expl;
  if (x?.state === "ok" && x.text) {
    // « Intitulé : texte » -> intitulé en gras sur sa propre ligne, texte dessous.
    const esc = (t) => t.replace(/&/g, "&amp;").replace(/</g, "&lt;");
    const rows = x.text.split(/\n+/).filter((t) => t.trim()).map((t) => {
      const m = t.match(/^\s*([^:]{2,22})\s*:\s*(.+)$/);
      return m ? `<div class="why-row"><b>${esc(m[1])}</b><span>${esc(m[2])}</span></div>` : `<p>${esc(t)}</p>`;
    });
    p.push(`<div class="why-box"><h3>Le point de l'équipier</h3>${rows.join("")}</div>`);
  }
  else if (x?.state === "pas de clé") p.push(`<p class="note">Explication en français : ajoute ta clé API Anthropic (voir le guide).</p>`);
  el.innerHTML = `<h3>Maintenant</h3>${p.join("")}`;
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
  const html = items.filter((x, k) => !only || (x.t > now - 3600e3 && x.t < now + 48 * 3600e3) || (now < ts(R.start_time) && x.t < ts(R.start_time) + 48 * 3600e3) || k === firstFuture)
    .map(({ t, w, c }) => {
      const past = t < now ? " past" : "";
      if (c) return `<li class="sailchg${past}"><div class="h"><span><span class="sw" style="background:${SAIL_COLORS[c.sail_to] || "#999"}"></span><b>Changer de voile : ${sailFr(c.sail_from)} → ${sailFr(c.sail_to)}</b></span><span class="t">${fmtT(c.t)}</span></div>
        <div class="m"><span><b>+${c.gain_pct} %</b> de vitesse</span><span>vent ${c.tws} kt</span><span>${latS(c.lat)} ${lonS(c.lon)}</span></div></li>`;
      const changed = prev.length && !prev.some(([a, b]) => hav(a, b, w.lat, w.lon) < 10);
      const txt = `${latS(w.lat)} ${lonS(w.lon)}`;
      return `<li class="${changed ? "changed" : ""}${past}">
        <div class="h"><span class="n">WP${pad(w.n)}${changed ? '<span class="badge warn">modifié</span>' : ""}${w.beyond_forecast ? '<span class="badge warn">hors prévision</span>' : ""}</span>
          <span class="t">${fmtT(w.t)}<span class="tz">${fmtZ(w.t)}</span></span></div>
        <div class="act">Cap <b>${deg(w.heading)}</b> · <span class="sw" style="background:${SAIL_COLORS[w.sail] || "#999"}"></span><b>${sailFr(w.sail)}</b></div>
        <div class="c"><button class="coord" data-copy="${latS(w.lat)}" aria-label="Copier la latitude">${latS(w.lat)}</button>
          <button class="coord" data-copy="${lonS(w.lon)}" aria-label="Copier la longitude">${lonS(w.lon)}</button>
          <button class="copy" data-copy="${txt}" aria-label="Copier latitude et longitude">⧉</button></div>
        <div class="m"><span>TWA <b>${twaS(w.twa)}</b></span><span>vent ${deg(w.twd)} ${w.tws.toFixed(0)} kt</span><span>${w.speed.toFixed(1)} kt prévus</span></div>
        <div class="why">${w.reason}</div></li>`;
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
let map, layers = {};
function initMap() {
  map = L.map("map", { preferCanvas: true, zoomControl: false, zoomSnap: 0.25, worldCopyJump: false }).setView([33, -32], 3);
  L.control.zoom({ position: "topright" }).addTo(map);
  // Pas de fond de carte tiers : on affiche les côtes GSHHG, celles qu'utilise le routeur.
  map.attributionControl.addAttribution("Côtes GSHHG 2.3.7 · vent NOAA GFS");
  for (const k of ["coast", "zones", "gates", "ens", "prev", "iso", "route", "wps", "wind", "boat"]) layers[k] = L.layerGroup().addTo(map);
  $("#show-wind").onchange = drawWind; $("#show-iso").onchange = drawRoute; $("#show-prev").onchange = drawRoute;
  $("#show-ens").onchange = drawRoute;
  $("#slider").oninput = (e) => { state.slider = +e.target.value; drawWind(); drawBoat(); };
  map.on("moveend", drawWind);
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
      .bindTooltip(`WP${pad(w.n)} · ${fmtT(w.t)}<br>${latS(w.lat)} ${lonS(w.lon)}<br>cap ${deg(w.heading)} · ${sailFr(w.sail)}<br>${w.reason}`, { className: "wp-tip" })
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
  const W = state.wind; if (!W) return;
  const fr = W.frames[state.slider]; if (!fr) return;
  const lead = Math.round((ts(fr.t) - ts(W.run)) / 3600e3);
  $("#wx-time").textContent = `Vent ${fmtT(fr.t)} · ${cycleS(state.status?.weather?.cycle)} +${lead} h`;
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
    const col = kt < 8 ? "#4b6c8a" : kt < 14 ? "#4cc3d9" : kt < 20 ? "#5fcf80" : kt < 26 ? "#f2b84b" : kt < 34 ? "#ef7b5a" : "#ef6461";
    L.polyline([tail, tip, l1, tip, l2], { color: col, weight: 1.2, opacity: 0.85, interactive: false }).addTo(layers.wind);
  }
}
function drawBoat() {
  layers.boat.clearLayers();
  const W = state.wind, fr = W?.frames[state.slider]; if (!fr || !state.route) return;
  const at = trackAt(ts(fr.t)); if (!at) return;
  L.circleMarker([at.lat, at.lon], { radius: 7, color: "#fff", weight: 2, fillColor: "#4cc3d9", fillOpacity: 1 })
    .bindTooltip(`Bateau prévu ${fmtT(fr.t)}`, { className: "wp-tip" }).addTo(layers.boat);
}

// --- actions (serveur local seulement) --------------------------------------------------------
async function detectApi() {
  try { const r = await fetch("/api/ping", { cache: "no-store" }); state.api = r.ok; } catch { state.api = false; }
  $("#actions").hidden = !state.api;
  // Version publiée sur GitHub Pages : les actions passent par les formulaires GitHub Actions.
  const gh = location.hostname.match(/^([^.]+)\.github\.io$/);
  if (!state.api && gh) {
    const repo = location.pathname.split("/").filter(Boolean)[0] || "";
    const base = `https://github.com/${gh[1]}/${repo}/actions/workflows`;
    $("#gh-pos").href = `${base}/position.yml`;
    $("#gh-route").href = `${base}/route.yml`;
    $("#gh").hidden = false;
  }
  $("#relay").hidden = state.api || !state.topic;
}
function fillForm() {
  const R = state.route; if (!R) return;
  for (const f of [$("#pos-form"), $("#relay-form")]) {
    f.sail.innerHTML = `<option value="">je ne sais pas</option>` + R.sail_names.map((s) => `<option value="${s}">${sailFr(s)}</option>`).join("");
    f.gate.innerHTML = R.gates.map((g, k) => `<option value="${k}" ${k === 1 ? "selected" : ""}>${g.name}</option>`).join("");
  }
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
function pickRoute() {
  // Route affichée partout : la conseillée (scénarios) par défaut, sinon la route GFS.
  const useSafe = state.choice === "safe" && state.safe;
  state.route = useSafe ? state.safe : state.main;
  document.querySelectorAll(".choice button").forEach((b) => b.classList.toggle("on", b.dataset.c === (useSafe ? "safe" : "gfs")));
  document.querySelectorAll(".choice").forEach((el) => (el.hidden = !state.safe));
}
function confidence(e) {
  const r = e.candidates.find((c) => c.id === e.recommended);
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
    const c = confidence(e), r = c.r;
    const same = e.recommended === "gfs";
    h += `<p>${e.judges} versions de la météo testées (${cycleS(e.gefs_cycle).replace("GFS", "GEFS")}).</p>
      <p>Arrivée la plus probable : <b>${fmtT(r.median_eta)}</b>. Dans 8 cas sur 10 : entre ${fmtT(r.p10_eta)} et ${fmtT(r.p90_eta)}.</p>
      <p>Fiabilité de la prévision : <b class="${c.cls}">${c.label}</b> (écart de ${Math.round(c.h)} h entre les cas).</p>
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
  if (boat !== state.boat) return;
  checkPending();
  pickRoute();
  const run = state.status?.weather?.run;
  if (!state.wind || (run && state.wind.run.slice(0, 13) !== run.slice(0, 13))) {
    try { state.wind = await getJSON("data/wind.json"); frameCache.clear(); setupSlider(); } catch { /* pas de vent */ }
  }
  renderPills(); renderNow(); renderScenarios(); renderBord(); renderRoute(); renderMeteo();
  if (map) { drawRoute(); drawWind(); drawBoat(); }
  if (state.route && !fillForm.done) { fillForm(); fillForm.done = true; }
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
  const f = $("#relay-form");
  f.code.value = store.get(`code-${id}`, "");
  $("#relay-msg").textContent = "";
  if (!reload) return;
  Object.assign(state, { main: null, safe: null, ens: null, expl: null, route: null });
  fitOnce.done = false;
  refresh().then(() => { if (map && $("#map").clientHeight) fitOnce(); });
}

// --- envoi de la position sans compte (page publiée → ntfy.sh → routeur) ----------------------
const normCode = (c) => String(c || "").replace(/\s+/g, "").toLowerCase();
async function hmacHex(key, text) {
  const enc = new TextEncoder();
  const k = await crypto.subtle.importKey("raw", enc.encode(key), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = new Uint8Array(await crypto.subtle.sign("HMAC", k, enc.encode(text)));
  return [...sig].map((x) => x.toString(16).padStart(2, "0")).join("");
}
function relayPreview() {
  const f = $("#relay-form"), lat = parseGame(f.lat.value, true), lon = parseGame(f.lon.value, false);
  $("#relay-preview").textContent = f.lat.value && f.lon.value
    ? (Number.isNaN(lat) || Number.isNaN(lon) ? "Position illisible" : `Compris : ${latS(lat)}  ${lonS(lon)}`) : "";
}
async function sendPosition(e) {
  e.preventDefault();
  const f = e.target, msg = $("#relay-msg"), boat = state.boats.find((b) => b.id === state.boat);
  const lat = parseGame(f.lat.value, true), lon = parseGame(f.lon.value, false), code = normCode(f.code.value);
  if (Number.isNaN(lat) || Number.isNaN(lon)) { msg.textContent = "Latitude ou longitude illisible."; return; }
  if (lat < 5 || lat > 55 || lon < -70 || lon > 5) { msg.textContent = "Cette position est hors du parcours : vérifie N/S et E/W."; return; }
  if (!boat?.check) { msg.textContent = "L'envoi n'est pas encore activé pour ce bateau (code à régler par Keziah)."; return; }
  if (!globalThis.crypto?.subtle) { msg.textContent = "Ce navigateur ne permet pas l'envoi (page non sécurisée)."; return; }
  if ((await hmacHex(code, `routeur-rhum:${boat.id}`)).slice(0, 8) !== boat.check) { msg.textContent = "Code incorrect."; return; }
  const t = Date.now() / 1000;
  const data = JSON.stringify({ bateau: boat.id, lat, lon, voile: f.sail.value, porte: +f.gate.value, twa: f.twa.value.trim(), t });
  const btn = f.querySelector("button[type=submit]"); btn.disabled = true; msg.textContent = "Envoi…";
  try {
    const r = await fetch(`https://ntfy.sh/${state.topic}`, { method: "POST", body: JSON.stringify({ data, sig: await hmacHex(code, data) }) });
    if (!r.ok) throw new Error(`erreur ${r.status}`);
    store.set(`code-${boat.id}`, f.keep.checked ? f.code.value : "");
    store.set(`pending-${boat.id}`, JSON.stringify({ t, lat, lon }));
    msg.textContent = `Position ${latS(lat)} ${lonS(lon)} envoyée. Nouvelle route dans 5 à 15 min : la page se met à jour toute seule.`;
    f.lat.value = ""; f.lon.value = ""; f.twa.value = ""; relayPreview(); renderNow();
  } catch (err) { msg.textContent = `Envoi impossible (${err.message}). Vérifie la connexion et réessaie.`; }
  finally { btn.disabled = false; }
}
// Position envoyée mais pas encore prise en compte ? (effacée dès qu'une route plus récente est publiée)
function pending() {
  try { return JSON.parse(store.get(`pending-${state.boat}`, "") || "null"); } catch { return null; }
}
function checkPending() {
  const p = pending(), R = state.main;
  if (p && R && ts(R.published_at || R.computed_at) / 1000 >= p.t) store.set(`pending-${state.boat}`, "");
}

function initUi() {
  state.fmt = store.get("fmt", "dms");
  state.choice = store.get("choice", "safe");
  document.querySelectorAll(".choice button").forEach((b) => (b.onclick = () => {
    state.choice = b.dataset.c; store.set("choice", state.choice); pickRoute();
    renderNow(); renderBord(); renderRoute(); if (map) { drawRoute(); drawBoat(); }
  }));
  const sel = $("#fmt");
  sel.value = state.fmt;
  sel.onchange = () => { state.fmt = sel.value; store.set("fmt", state.fmt); renderRoute(); renderBord(); };
  $("#only-next").onchange = renderRoute;
  $("#relay-form").onsubmit = sendPosition;
  $("#relay-form").oninput = relayPreview;
  document.querySelectorAll(".tabs button").forEach((b) => (b.onclick = () => {
    document.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("on", x === b));
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.id === `tab-${b.dataset.tab}`));
    if (b.dataset.tab === "carte") setTimeout(() => { map.invalidateSize(); fitOnce(); drawWind(); }, 50);
  }));
  document.body.addEventListener("click", (e) => { const c = e.target.closest("[data-copy]"); if (c) copyText(c.dataset.copy); });
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
