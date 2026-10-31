/* EcoAbidjan - interface web (JavaScript sans framework) */
"use strict";

const ABIDJAN = [5.345, -4.02];
const STAFF = ["agent", "admin"];
const state = { token: null, user: null, materials: [], communes: [], relays: [], charts: [], maps: [] };
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const view = $("#view");

try { state.token = localStorage.getItem("eco_token"); } catch { /* stockage indisponible */ }

// --- Utilitaires -------------------------------------------------------------
function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
const fcfa = (n) => `${Math.round(n || 0).toLocaleString("fr-FR")} FCFA`;
const kg = (n) => `${(n || 0).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} kg`;
const num = (n) => (n || 0).toLocaleString("fr-FR");
const dt = (s) => (s ? new Date(s + (s.endsWith("Z") ? "" : "Z")).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—");
const badge = (s) => `<span class="badge ${esc(s)}">${esc(String(s).replace("_", " ").toLowerCase())}</span>`;
const isStaff = () => state.user && STAFF.includes(state.user.role);

function toast(msg, error = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (error ? " error" : "");
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.hidden = true), 3500);
}

async function api(path, { method = "GET", body, form } = {}) {
  const headers = {};
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  let payload;
  if (form) payload = form;
  else if (body !== undefined) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
  const res = await fetch(path, { method, headers, body: payload });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && state.token) { logout(); throw new Error("Session expiree, reconnecte-toi"); }
  if (!res.ok) {
    const d = data.detail;
    const msg = Array.isArray(d) ? d.map((e) => e.msg).join(" ; ") : d || `Erreur ${res.status}`;
    throw new Error(msg);
  }
  return data;
}

async function withBusy(btn, fn) {
  if (btn) btn.disabled = true;
  try { return await fn(); }
  catch (e) { toast(e.message, true); }
  finally { if (btn) btn.disabled = false; }
}

/** Petite boite de dialogue : fields = [{name,label,type,value,options,required}] */
function ask(title, fields) {
  return new Promise((resolve) => {
    const modal = $("#modal");
    $("#modal-title").textContent = title;
    $("#modal-body").innerHTML = fields.map((f) => `
      <label for="m_${f.name}">${esc(f.label)}</label>
      ${f.options
        ? `<select id="m_${f.name}" name="${f.name}">${f.options.map((o) => `<option value="${esc(o[0])}">${esc(o[1])}</option>`).join("")}</select>`
        : `<input id="m_${f.name}" name="${f.name}" type="${f.type || "text"}" step="any" value="${esc(f.value ?? "")}" ${f.required ? "required" : ""}>`}
    `).join("");
    modal.hidden = false;
    const form = $("#modal-form");
    const close = (val) => { modal.hidden = true; form.onsubmit = null; $("#modal-cancel").onclick = null; resolve(val); };
    form.onsubmit = (e) => { e.preventDefault(); close(Object.fromEntries(new FormData(form))); };
    $("#modal-cancel").onclick = () => close(null);
    setTimeout(() => $("input, select", modal)?.focus(), 50);
  });
}

function cleanup() {
  state.charts.forEach((c) => c.destroy());
  state.maps.forEach((m) => m.remove());
  state.charts = []; state.maps = [];
}

function makeMap(id, center = ABIDJAN, zoom = 12) {
  const map = L.map(id).setView(center, zoom);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19, attribution: "&copy; OpenStreetMap",
  }).addTo(map);
  state.maps.push(map);
  setTimeout(() => map.invalidateSize(), 100);
  return map;
}

const dot = (color) => ({ radius: 7, color: "#fff", weight: 2, fillColor: color, fillOpacity: 0.9 });
const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

function getPosition() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) return reject(new Error("Geolocalisation non disponible"));
    navigator.geolocation.getCurrentPosition(
      (p) => resolve([p.coords.latitude, p.coords.longitude]),
      () => reject(new Error("Position refusee : clique sur la carte pour la placer")),
      { enableHighAccuracy: true, timeout: 10000 },
    );
  });
}

/** Carte avec un marqueur deplacable ; renvoie un objet {get()} */
function positionPicker(mapId, btnSel, infoSel) {
  const map = makeMap(mapId);
  let marker = null;
  const set = (latlng) => {
    if (!marker) marker = L.marker(latlng, { draggable: true }).addTo(map);
    marker.setLatLng(latlng);
    $(infoSel).textContent = `Position : ${latlng[0].toFixed(5)}, ${latlng[1].toFixed(5)}`;
  };
  map.on("click", (e) => set([e.latlng.lat, e.latlng.lng]));
  $(btnSel).onclick = async () => {
    try { const p = await getPosition(); set(p); map.setView(p, 16); } catch (e) { toast(e.message, true); }
  };
  return { get: () => (marker ? [marker.getLatLng().lat, marker.getLatLng().lng] : null) };
}

// --- Navigation --------------------------------------------------------------
const USER_ROUTES = [
  ["accueil", "Accueil"], ["signaler", "Signaler"], ["declarer", "Declarer"],
  ["relais", "Points relais"], ["portefeuille", "Portefeuille"], ["historique", "Historique"],
];
const STAFF_ROUTES = [
  ["dashboard", "Tableau de bord"], ["signalements", "Signalements"], ["validations", "Declarations"],
  ["tournees", "Tournees"], ["paiements", "Paiements"], ["tarifs", "Tarifs & parametres"], ["snowflake", "Snowflake"],
];

function routes() {
  if (!state.user) return [];
  if (state.user.role === "admin") return STAFF_ROUTES;
  if (state.user.role === "agent") return STAFF_ROUTES.filter((r) => !["tarifs", "snowflake"].includes(r[0]));
  return USER_ROUTES;
}

function renderChrome() {
  const nav = $("#nav");
  const box = $("#userbox");
  if (!state.user) { nav.hidden = true; box.innerHTML = ""; return; }
  box.innerHTML = `<span class="name">${esc(state.user.full_name)} · ${esc(state.user.role)}</span>
    ${isStaff() ? "" : `<span>⭐ ${num(state.user.points_balance)}</span>`}
    <button class="btn sm" id="logout">Quitter</button>`;
  $("#logout").onclick = logout;
  nav.hidden = false;
  const current = location.hash.slice(1);
  nav.innerHTML = routes().map(([k, label]) => `<button data-r="${k}" class="${k === current ? "active" : ""}">${label}</button>`).join("");
  $$("button", nav).forEach((b) => (b.onclick = () => (location.hash = b.dataset.r)));
}

async function router() {
  cleanup();
  if (!state.user) return renderAuth();
  const allowed = routes().map((r) => r[0]);
  let r = location.hash.slice(1);
  if (!allowed.includes(r)) { r = allowed[0]; history.replaceState(null, "", "#" + r); }
  renderChrome();
  view.innerHTML = `<p class="muted">Chargement…</p>`;
  try { await VIEWS[r](); } catch (e) { view.innerHTML = `<div class="card">${esc(e.message)}</div>`; }
  window.scrollTo(0, 0);
}

function logout() {
  state.token = null; state.user = null;
  try { localStorage.removeItem("eco_token"); } catch { /* ignore */ }
  location.hash = "";
  router();
  Chat.userChanged();
}

async function onLogged(data) {
  state.token = data.token; state.user = data.user;
  try { localStorage.setItem("eco_token", data.token); } catch { /* ignore */ }
  location.hash = "";
  await router();
  Chat.userChanged();
}

// --- Authentification ----------------------------------------------------------
function renderAuth() {
  renderChrome();
  view.innerHTML = `
  <div class="auth">
    <div class="card">
      <h1>Bienvenue sur EcoAbidjan</h1>
      <p class="muted">Signale les depots sauvages, revends tes dechets recyclables et gagne des points.</p>
      <div class="tabs"><button class="btn" id="t-login">Connexion</button><button class="btn ghost" id="t-reg">Inscription</button></div>
      <form id="f-login">
        <label for="l-email">E-mail</label><input id="l-email" name="email" type="email" required autocomplete="username">
        <label for="l-pwd">Mot de passe</label><input id="l-pwd" name="password" type="password" required autocomplete="current-password">
        <div class="actions"><button class="btn">Se connecter</button></div>
      </form>
      <form id="f-reg" hidden>
        <label for="r-name">Nom complet</label><input id="r-name" name="full_name" required>
        <label for="r-email">E-mail</label><input id="r-email" name="email" type="email" required>
        <label for="r-phone">Telephone (Mobile Money)</label><input id="r-phone" name="phone" placeholder="+225 07 ...">
        <label for="r-role">Je suis</label>
        <select id="r-role" name="role"><option value="citoyen">Citoyen</option><option value="menage">Menage</option><option value="commercant">Commercant</option></select>
        <div id="r-extra"></div>
        <label for="r-commune">Commune</label><select id="r-commune" name="commune_id"></select>
        <label for="r-pwd">Mot de passe (8 caracteres min.)</label><input id="r-pwd" name="password" type="password" minlength="8" required autocomplete="new-password">
        <div class="actions"><button class="btn">Creer mon compte</button></div>
      </form>
    </div>
    <div class="card small">
      <strong>Comptes de demonstration</strong>
      <p class="muted">Mot de passe : voir le fichier README du projet.</p>
      <div class="demo-accounts">
        ${["citoyen", "menage", "commercant", "agent", "admin"].map((r) => `<button class="btn ghost sm" data-demo="${r}">${r}</button>`).join("")}
      </div>
    </div>
  </div>`;
  const showReg = (reg) => {
    $("#f-login").hidden = reg; $("#f-reg").hidden = !reg;
    $("#t-login").className = reg ? "btn ghost" : "btn"; $("#t-reg").className = reg ? "btn" : "btn ghost";
  };
  $("#t-login").onclick = () => showReg(false);
  $("#t-reg").onclick = () => showReg(true);
  $("#r-commune").innerHTML = `<option value="">—</option>` + state.communes.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join("");
  $("#r-role").onchange = (e) => {
    const r = e.target.value;
    $("#r-extra").innerHTML = r === "menage"
      ? `<label for="r-hh">Nombre de personnes</label><input id="r-hh" name="household_size" type="number" min="1" max="50">`
      : r === "commercant"
        ? `<label for="r-bn">Nom du commerce</label><input id="r-bn" name="business_name" required>
           <label for="r-bt">Activite</label><input id="r-bt" name="business_type" placeholder="Restauration, boutique...">`
        : "";
  };
  $("#f-login").onsubmit = (e) => {
    e.preventDefault();
    const btn = $("button", e.target);
    withBusy(btn, async () => onLogged(await api("/api/auth/login", { method: "POST", body: Object.fromEntries(new FormData(e.target)) })));
  };
  $("#f-reg").onsubmit = (e) => {
    e.preventDefault();
    const body = Object.fromEntries(new FormData(e.target));
    for (const k of Object.keys(body)) if (body[k] === "") delete body[k];
    if (body.commune_id) body.commune_id = +body.commune_id;
    if (body.household_size) body.household_size = +body.household_size;
    withBusy($("button", e.target), async () => onLogged(await api("/api/auth/register", { method: "POST", body })));
  };
  $$("[data-demo]").forEach((b) => (b.onclick = () => {
    showReg(false);
    $("#l-email").value = `${b.dataset.demo}@ecoabidjan.ci`;
    $("#l-pwd").focus();
  }));
}

// --- Vues usager ---------------------------------------------------------------
const VIEWS = {};

VIEWS.accueil = async () => {
  const [w, reports, decls, open] = await Promise.all([
    api("/api/wallet"), api("/api/reports/mine"), api("/api/declarations/mine"), api("/api/reports/map"),
  ]);
  state.user.points_balance = w.points_balance;
  renderChrome();
  view.innerHTML = `
    <h1>Bonjour ${esc(state.user.full_name.split(" ")[0])} 👋</h1>
    <div class="kpis">
      <div class="kpi"><div class="label">Points fidelite</div><div class="value">⭐ ${num(w.points_balance)}</div></div>
      <div class="kpi"><div class="label">Gains totaux</div><div class="value">${fcfa(w.total_earned_fcfa)}</div><div class="hint">dont ${fcfa(w.pending_fcfa)} en attente</div></div>
      <div class="kpi"><div class="label">Mes signalements</div><div class="value">${reports.length}</div></div>
      <div class="kpi"><div class="label">Mes declarations</div><div class="value">${decls.length}</div></div>
    </div>
    <div class="grid grid-2">
      <div class="card">
        <h2>Agir maintenant</h2>
        <p class="muted">Photographie un depot sauvage : l'IA identifie les matieres et estime le poids.</p>
        <div class="actions"><a class="btn" href="#signaler">📸 Signaler un depot</a><a class="btn ghost" href="#declarer">♻ Declarer mes dechets</a></div>
        <h3 style="margin-top:18px">Tarifs de rachat en vigueur</h3>
        ${state.materials.filter((m) => m.price_fcfa_per_kg).map((m) => `<div class="mat-row"><span>${esc(m.name)}</span><span></span><strong>${m.price_fcfa_per_kg} F/kg</strong></div>`).join("")}
        <p class="notice">Depose tes dechets en point relais pour gagner des points en plus de ta remuneration.</p>
      </div>
      <div class="card"><h2>Depots signales autour de toi</h2><div id="home-map" class="map"></div></div>
    </div>`;
  const map = makeMap("home-map");
  open.forEach((r) => L.circleMarker([r.latitude, r.longitude], dot(cssVar("--danger"))).addTo(map)
    .bindPopup(`${badge(r.status)}<br>~${kg(r.ai_estimated_weight_kg)}<br>${dt(r.created_at)}`));
};

function analysisCard(a) {
  if (!a) return "";
  const names = { PLASTIQUE: "Plastique", CARTON: "Carton", ALUMINIUM: "Aluminium", VERRE: "Verre", ORGANIQUE: "Organique", TEXTILE: "Textile", AUTRE: "Autre" };
  return `
    <h3>Analyse IA ${badge(a.status)}</h3>
    ${a.materials.map((m) => `<div class="mat-row"><span>${names[m.code] || esc(m.code)}</span>
      <div class="bar"><span style="width:${Math.round(m.share * 100)}%"></span></div><span>${Math.round(m.share * 100)}%</span></div>`).join("") || "<p class='muted'>Aucune matiere identifiee</p>"}
    <p><strong>Poids estime : ${kg(a.estimated_weight_kg)}</strong> · volume ~${a.estimated_volume_m3} m³ · confiance ${Math.round((a.confidence || 0) * 100)}%</p>
    ${a.summary ? `<p class="muted">${esc(a.summary)}</p>` : ""}
    <p class="small muted">Moteur : ${esc(a.provider)} / ${esc(a.model)} · ${a.duration_ms ?? "?"} ms. Estimation indicative, le poids reel est verifie lors de la collecte.</p>
    ${a.error ? `<p class="small muted">${esc(a.error)}</p>` : ""}`;
}

VIEWS.signaler = async () => {
  view.innerHTML = `
    <h1>Signaler un depot sauvage</h1>
    <div class="grid grid-2">
      <form class="card" id="f-report">
        <label for="photo">Photo du depot</label>
        <input id="photo" name="photo" type="file" accept="image/jpeg,image/png,image/webp" capture="environment" required>
        <img id="preview" class="preview" hidden alt="Apercu de la photo">
        <label for="desc">Description (facultatif)</label>
        <textarea id="desc" name="description" placeholder="Ex : tas de sachets au bord du caniveau"></textarea>
        <label for="addr">Repere / adresse (facultatif)</label>
        <input id="addr" name="address" placeholder="Pres de la pharmacie...">
        <div class="actions"><button class="btn" id="send">Envoyer le signalement</button></div>
      </form>
      <div class="card">
        <div class="row"><button type="button" class="btn ghost" id="geo">📍 Utiliser ma position</button></div>
        <p id="pos" class="muted small">Clique sur la carte ou utilise ta position.</p>
        <div id="pick-map" class="map"></div>
      </div>
    </div>
    <div id="result"></div>`;
  const picker = positionPicker("pick-map", "#geo", "#pos");
  $("#photo").onchange = (e) => {
    const f = e.target.files[0];
    if (f) { $("#preview").src = URL.createObjectURL(f); $("#preview").hidden = false; }
  };
  $("#f-report").onsubmit = (e) => {
    e.preventDefault();
    const pos = picker.get();
    if (!pos) return toast("Indique la position du depot", true);
    const form = new FormData(e.target);
    form.append("latitude", pos[0]); form.append("longitude", pos[1]);
    const btn = $("#send");
    btn.textContent = "Analyse IA en cours…";
    withBusy(btn, async () => {
      const r = await api("/api/reports", { method: "POST", form });
      toast("Signalement envoye, merci !");
      $("#result").innerHTML = `<div class="card"><h2>Signalement n°${r.id} ${badge(r.status)}</h2>
        <p class="muted">Commune detectee : ${esc(r.commune || "hors zone")}. Tu gagneras des points quand un agent l'aura confirme.</p>
        ${analysisCard(r.analysis)}</div>`;
      e.target.reset(); $("#preview").hidden = true;
      $("#result").scrollIntoView({ behavior: "smooth" });
    }).finally(() => (btn.textContent = "Envoyer le signalement"));
  };
};

VIEWS.declarer = async () => {
  const mats = state.materials.filter((m) => m.price_fcfa_per_kg);
  view.innerHTML = `
    <h1>Declarer mes dechets recyclables</h1>
    <div class="grid grid-2">
      <form class="card" id="f-decl">
        <label>Mode de remise</label>
        <div class="row">
          <label class="small"><input type="radio" name="mode" value="POINT_RELAIS" checked style="width:auto"> Je depose en point relais (+ points)</label>
          <label class="small"><input type="radio" name="mode" value="COLLECTE_DOMICILE" style="width:auto"> Collecte a domicile</label>
        </div>
        <div id="relay-box">
          <label for="relay">Point relais</label><select id="relay"></select>
          <button type="button" class="btn ghost sm" id="near" style="margin-top:6px">📍 Trier par distance</button>
        </div>
        <div id="home-box" hidden>
          <button type="button" class="btn ghost sm" id="geo2">📍 Utiliser ma position</button>
          <p id="pos2" class="muted small">Clique sur la carte pour indiquer ton adresse.</p>
          <div id="decl-map" class="map"></div>
        </div>
        <label>Matieres et poids estimes</label>
        <div id="items"></div>
        <button type="button" class="btn ghost sm" id="add">+ Ajouter une matiere</button>
        <label for="note">Remarque (facultatif)</label><input id="note" name="note">
        <p>Remuneration estimee : <span class="total" id="total">0 FCFA</span></p>
        <p class="small muted">Le montant final est calcule sur le poids pese par l'agent, au tarif du jour.</p>
        <div class="actions"><button class="btn" id="send">Envoyer ma declaration</button></div>
      </form>
      <div class="card"><h2>Tarifs</h2>
        ${mats.map((m) => `<div class="mat-row"><span>${esc(m.name)}</span><span class="muted small">${esc(m.description || "")}</span><strong>${m.price_fcfa_per_kg} F</strong></div>`).join("")}
      </div>
    </div>`;
  const fillRelays = (list) => {
    $("#relay").innerHTML = list.map((p) => `<option value="${p.id}">${esc(p.name)}${p.distance_km != null ? ` — ${p.distance_km} km` : ""}</option>`).join("");
  };
  fillRelays(state.relays);
  $("#near").onclick = async () => {
    try { const [la, lo] = await getPosition(); fillRelays(await api(`/api/relay-points?lat=${la}&lon=${lo}`)); }
    catch (e) { toast(e.message, true); }
  };
  let picker = null;
  $$("input[name=mode]").forEach((r) => (r.onchange = () => {
    const home = $("input[name=mode]:checked").value === "COLLECTE_DOMICILE";
    $("#relay-box").hidden = home; $("#home-box").hidden = !home;
    if (home && !picker) picker = positionPicker("decl-map", "#geo2", "#pos2");
  }));
  const addRow = () => {
    const div = document.createElement("div");
    div.className = "item-row";
    div.innerHTML = `<select aria-label="Matiere">${mats.map((m) => `<option value="${m.id}">${esc(m.name)}</option>`).join("")}</select>
      <input type="number" min="0.1" max="1000" step="0.1" placeholder="kg" aria-label="Poids en kg" required>
      <button type="button" class="btn ghost sm" aria-label="Retirer">✕</button>`;
    $("button", div).onclick = () => { div.remove(); recalc(); };
    $$("select, input", div).forEach((x) => (x.oninput = recalc));
    $("#items").appendChild(div);
  };
  const lines = () => $$(".item-row").map((r) => ({ material_id: +$("select", r).value, estimated_weight_kg: +$("input", r).value }));
  const recalc = () => {
    const total = lines().reduce((s, l) => s + (mats.find((m) => m.id === l.material_id)?.price_fcfa_per_kg || 0) * (l.estimated_weight_kg || 0), 0);
    $("#total").textContent = fcfa(total);
  };
  $("#add").onclick = addRow;
  addRow();
  $("#f-decl").onsubmit = (e) => {
    e.preventDefault();
    const mode = $("input[name=mode]:checked").value;
    const body = { mode, items: lines().filter((l) => l.estimated_weight_kg > 0), note: $("#note").value || null };
    if (mode === "POINT_RELAIS") body.relay_point_id = +$("#relay").value;
    else {
      const p = picker?.get();
      if (!p) return toast("Indique ton adresse sur la carte", true);
      [body.latitude, body.longitude] = p;
    }
    withBusy($("#send"), async () => {
      const d = await api("/api/declarations", { method: "POST", body });
      toast(`Declaration n°${d.id} envoyee`);
      location.hash = "historique";
    });
  };
};

VIEWS.relais = async () => {
  view.innerHTML = `<h1>Points relais</h1><div class="grid grid-2">
    <div class="card"><div id="relay-map" class="map tall"></div></div>
    <div class="card"><button class="btn ghost sm" id="near">📍 Les plus proches de moi</button><div id="rlist"></div></div></div>`;
  const map = makeMap("relay-map");
  const draw = (list) => {
    $("#rlist").innerHTML = list.map((p) => `<div class="list-item"><strong>${esc(p.name)}</strong>${p.distance_km != null ? ` <span class="badge">${p.distance_km} km</span>` : ""}
      <div class="small muted">${esc(p.address || "")} · ${esc(p.commune || "")}</div>
      <div class="small">${esc(p.opening_hours || "")} · ${p.accepted_materials.map(esc).join(", ")}</div></div>`).join("");
  };
  state.relays.forEach((p) => L.marker([p.latitude, p.longitude]).addTo(map).bindPopup(`<strong>${esc(p.name)}</strong><br>${esc(p.address || "")}`));
  draw(state.relays);
  $("#near").onclick = async () => {
    try {
      const [la, lo] = await getPosition();
      L.circleMarker([la, lo], dot(cssVar("--info"))).addTo(map).bindPopup("Vous etes ici");
      map.setView([la, lo], 13);
      draw(await api(`/api/relay-points?lat=${la}&lon=${lo}`));
    } catch (e) { toast(e.message, true); }
  };
};

VIEWS.portefeuille = async () => {
  const w = await api("/api/wallet");
  view.innerHTML = `<h1>Mon portefeuille</h1>
    <div class="kpis">
      <div class="kpi"><div class="label">Points</div><div class="value">⭐ ${num(w.points_balance)}</div></div>
      <div class="kpi"><div class="label">Deja paye</div><div class="value">${fcfa(w.paid_fcfa)}</div></div>
      <div class="kpi"><div class="label">En attente</div><div class="value">${fcfa(w.pending_fcfa)}</div></div>
    </div>
    <div class="grid grid-2">
      <div class="card"><h2>Remunerations</h2><div class="table-wrap"><table>
        <tr><th>Date</th><th>Declaration</th><th class="num">Montant</th><th>Statut</th></tr>
        ${w.payments.map((p) => `<tr><td>${dt(p.created_at)}</td><td>n°${p.declaration_id}</td><td class="num">${fcfa(p.amount_fcfa)}</td><td>${badge(p.status)}${p.reference ? `<div class="small muted">${esc(p.reference)}</div>` : ""}</td></tr>`).join("") || `<tr><td colspan="4" class="muted">Aucune remuneration pour l'instant</td></tr>`}
      </table></div></div>
      <div class="card"><h2>Historique des points</h2>
        ${w.points_history.map((t) => `<div class="list-item"><strong>+${t.points}</strong> ${esc(t.reason)} <span class="small muted">${dt(t.created_at)}</span></div>`).join("") || "<p class='muted'>Pas encore de points</p>"}
      </div>
    </div>`;
};

VIEWS.historique = async () => {
  const [reports, decls] = await Promise.all([api("/api/reports/mine"), api("/api/declarations/mine")]);
  view.innerHTML = `<h1>Historique</h1><div class="grid grid-2">
    <div class="card"><h2>Mes declarations</h2>
      ${decls.map((d) => `<div class="list-item">n°${d.id} ${badge(d.status)} <span class="small muted">${dt(d.created_at)}</span>
        <div class="small">${d.items.map((i) => `${esc(i.material)} ${kg(i.validated_weight_kg ?? i.estimated_weight_kg)}`).join(" · ")}</div>
        <div class="small muted">${d.mode === "POINT_RELAIS" ? esc(d.relay_point) : "Collecte a domicile"}
        ${d.total_amount_fcfa != null ? ` · <strong>${fcfa(d.total_amount_fcfa)}</strong>` : ""}${d.points_awarded ? ` · +${d.points_awarded} pts` : ""}
        ${d.rejection_reason ? ` · ${esc(d.rejection_reason)}` : ""}</div></div>`).join("") || "<p class='muted'>Aucune declaration</p>"}
    </div>
    <div class="card"><h2>Mes signalements</h2>
      ${reports.map((r) => `<div class="list-item">n°${r.id} ${badge(r.status)} <span class="small muted">${dt(r.created_at)} · ${esc(r.commune || "")}</span>
        <div class="small">IA : ~${kg(r.ai_estimated_weight_kg)}${r.validated_weight_kg ? ` · collecte : ${kg(r.validated_weight_kg)}` : ""}${r.points_awarded ? ` · +${r.points_awarded} pts` : ""}</div></div>`).join("") || "<p class='muted'>Aucun signalement</p>"}
    </div></div>`;
};

// --- Vues agents / administrateurs ----------------------------------------------

VIEWS.dashboard = async () => {
  const [d, open] = await Promise.all([api("/api/admin/dashboard"), api("/api/reports/map")]);
  const k = d.kpis;
  const tile = (label, value, hint = "") => `<div class="kpi"><div class="label">${label}</div><div class="value">${value}</div>${hint ? `<div class="hint">${hint}</div>` : ""}</div>`;
  view.innerHTML = `<h1>Tableau de bord</h1>
    <div class="kpis">
      ${tile("Signalements", num(k.reports_total), `${num(k.reports_open)} ouverts · ${num(k.reports_collected)} collectes`)}
      ${tile("Recycle (valide)", kg(k.kg_recycled))}
      ${tile("Remunerations payees", fcfa(k.amount_paid_fcfa), `${fcfa(k.amount_pending_fcfa)} en attente`)}
      ${tile("Declarations", num(k.declarations_total), `${num(k.declarations_pending)} a traiter`)}
      ${tile("Points distribues", num(k.points_distributed))}
      ${tile("Apports en point relais", `${k.relay_share_pct} %`)}
      ${tile("Ecart IA / pesee", k.ai_weight_error_pct != null ? `${k.ai_weight_error_pct} %` : "—", "erreur moyenne du poids estime par photo")}
      ${tile("Cout des tournees", fcfa(k.collection_cost_fcfa), `${num(k.collections_total)} tournees`)}
    </div>
    <div class="grid grid-2">
      <div class="card"><h2>Recyclage par mois (kg valides)</h2><div class="chart-box"><canvas id="c-month"></canvas></div></div>
      <div class="card"><h2>Matieres recyclees</h2><div class="chart-box"><canvas id="c-mat"></canvas></div></div>
      <div class="card"><h2>Signalements par commune</h2><div class="chart-box"><canvas id="c-commune"></canvas></div></div>
      <div class="card"><h2>Depots encore ouverts</h2><div id="dash-map" class="map"></div></div>
    </div>`;
  const primary = cssVar("--primary"), accent = cssVar("--accent"), muted = cssVar("--muted"), border = cssVar("--border");
  Chart.defaults.color = muted;
  Chart.defaults.borderColor = border;
  const opts = { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } };
  state.charts.push(new Chart($("#c-month"), {
    data: {
      labels: d.monthly.map((m) => m.month),
      datasets: [
        { type: "bar", label: "kg valides", data: d.monthly.map((m) => m.kg), backgroundColor: primary, borderRadius: 4, yAxisID: "y" },
        { type: "line", label: "Signalements", data: d.monthly.map((m) => m.reports), borderColor: accent, backgroundColor: accent, yAxisID: "y1" },
      ],
    },
    options: { ...opts, plugins: { legend: { display: true } }, scales: { y: { beginAtZero: true }, y1: { beginAtZero: true, position: "right", grid: { display: false } } } },
  }));
  state.charts.push(new Chart($("#c-mat"), {
    type: "bar",
    data: { labels: d.by_material.map((m) => m.material), datasets: [{ data: d.by_material.map((m) => m.kg), backgroundColor: primary, borderRadius: 4 }] },
    options: { ...opts, plugins: { legend: { display: false }, tooltip: { callbacks: { afterLabel: (c) => fcfa(d.by_material[c.dataIndex].amount_fcfa) } } } },
  }));
  const top = d.by_commune.slice(0, 10);
  state.charts.push(new Chart($("#c-commune"), {
    type: "bar",
    data: { labels: top.map((c) => c.commune), datasets: [
      { label: "Total", data: top.map((c) => c.reports), backgroundColor: primary, borderRadius: 4 },
      { label: "Ouverts", data: top.map((c) => c.open), backgroundColor: accent, borderRadius: 4 },
    ] },
    options: { ...opts, indexAxis: "y", plugins: { legend: { display: true } } },
  }));
  const map = makeMap("dash-map", ABIDJAN, 11);
  open.forEach((r) => L.circleMarker([r.latitude, r.longitude], dot(r.status === "SIGNALE" ? cssVar("--accent") : cssVar("--info"))).addTo(map)
    .bindPopup(`n°${r.id} ${badge(r.status)}<br>~${kg(r.ai_estimated_weight_kg)}`));
};

VIEWS.signalements = async () => {
  const status = sessionStorage.getItem("f_reports") ?? "SIGNALE";
  const rows = await api(`/api/admin/reports${status ? `?status=${status}` : ""}`);
  view.innerHTML = `<h1>Signalements</h1>
    <div class="card"><div class="row"><div><label for="fs">Statut</label><select id="fs">
      ${["", "SIGNALE", "CONFIRME", "PLANIFIE", "COLLECTE", "REJETE"].map((s) => `<option value="${s}" ${s === status ? "selected" : ""}>${s || "Tous"}</option>`).join("")}
    </select></div></div></div>
    <div class="card table-wrap"><table>
      <tr><th>Photo</th><th>N°</th><th>Commune</th><th>IA</th><th class="num">Estime</th><th>Statut</th><th>Actions</th></tr>
      ${rows.map((r) => `<tr>
        <td>${r.photos[0] ? `<a href="${r.photos[0]}?token=${state.token}" target="_blank" rel="noopener"><img class="thumb" src="${r.photos[0]}?token=${state.token}" alt="" onerror="this.replaceWith(document.createTextNode('—'))"></a>` : "—"}</td>
        <td>${r.id}<div class="small muted">${dt(r.created_at)}</div></td>
        <td>${esc(r.commune || "—")}<div class="small muted">${r.latitude.toFixed(4)}, ${r.longitude.toFixed(4)}</div></td>
        <td class="small">${r.analysis ? r.analysis.materials.slice(0, 3).map((m) => `${esc(m.code.toLowerCase())} ${Math.round(m.share * 100)}%`).join(", ") : "—"}</td>
        <td class="num">${kg(r.ai_estimated_weight_kg)}</td>
        <td>${badge(r.status)}</td>
        <td>${["SIGNALE", "CONFIRME", "PLANIFIE"].includes(r.status) ? `
          ${r.status === "SIGNALE" ? `<button class="btn sm" data-a="CONFIRME" data-id="${r.id}">Confirmer</button>` : ""}
          <button class="btn ghost sm" data-a="COLLECTE" data-id="${r.id}">Collecte</button>
          <button class="btn ghost sm" data-a="REJETE" data-id="${r.id}">Rejeter</button>` : ""}</td>
      </tr>`).join("") || `<tr><td colspan="7" class="muted">Aucun signalement</td></tr>`}
    </table></div>`;
  $("#fs").onchange = (e) => { sessionStorage.setItem("f_reports", e.target.value); router(); };
  $$("[data-a]").forEach((b) => (b.onclick = async () => {
    const body = { status: b.dataset.a };
    if (body.status === "COLLECTE") {
      const v = await ask("Poids reellement collecte", [{ name: "kg", label: "Poids (kg)", type: "number", required: true }]);
      if (!v) return;
      body.validated_weight_kg = +v.kg;
    }
    withBusy(b, async () => { await api(`/api/admin/reports/${b.dataset.id}/status`, { method: "PATCH", body }); toast("Signalement mis a jour"); router(); });
  }));
};

VIEWS.validations = async () => {
  const status = sessionStorage.getItem("f_decl") ?? "SOUMISE";
  const rows = await api(`/api/admin/declarations${status ? `?status=${status}` : ""}`);
  view.innerHTML = `<h1>Declarations</h1>
    <div class="card"><div class="row"><div><label for="fd">Statut</label><select id="fd">
      ${["", "SOUMISE", "PLANIFIEE", "VALIDEE", "REJETEE"].map((s) => `<option value="${s}" ${s === status ? "selected" : ""}>${s || "Toutes"}</option>`).join("")}
    </select></div></div></div>
    ${rows.map((d) => `<form class="card" data-id="${d.id}">
      <div class="row" style="align-items:center"><div><strong>n°${d.id}</strong> ${badge(d.status)} <span class="small muted">${dt(d.created_at)}</span></div>
        <div class="small">${esc(d.user)} (${esc(d.user_role)}) · ${d.mode === "POINT_RELAIS" ? esc(d.relay_point) : "Collecte a domicile"}</div></div>
      <div class="table-wrap"><table><tr><th>Matiere</th><th class="num">Declare</th><th class="num">Pese (kg)</th><th class="num">Montant</th></tr>
        ${d.items.map((i) => `<tr><td>${esc(i.material)}</td><td class="num">${kg(i.estimated_weight_kg)}</td>
          <td class="num">${["SOUMISE", "PLANIFIEE"].includes(d.status)
            ? `<input type="number" step="0.1" min="0" name="${i.id}" value="${i.estimated_weight_kg}" style="max-width:110px" aria-label="Poids pese">`
            : kg(i.validated_weight_kg)}</td>
          <td class="num">${i.amount_fcfa != null ? fcfa(i.amount_fcfa) : "—"}</td></tr>`).join("")}
      </table></div>
      ${d.total_amount_fcfa != null ? `<p>Total : <strong>${fcfa(d.total_amount_fcfa)}</strong>${d.points_awarded ? ` · +${d.points_awarded} points` : ""}</p>` : ""}
      ${d.rejection_reason ? `<p class="muted">Motif : ${esc(d.rejection_reason)}</p>` : ""}
      ${["SOUMISE", "PLANIFIEE"].includes(d.status) ? `<div class="actions"><button class="btn">Valider la pesee</button><button type="button" class="btn ghost" data-reject>Rejeter</button></div>` : ""}
    </form>`).join("") || `<div class="card muted">Aucune declaration</div>`}`;
  $("#fd").onchange = (e) => { sessionStorage.setItem("f_decl", e.target.value); router(); };
  $$("form[data-id]").forEach((f) => {
    f.onsubmit = (e) => {
      e.preventDefault();
      const items = $$("input[type=number]", f).map((i) => ({ item_id: +i.name, validated_weight_kg: +i.value }));
      withBusy($("button", f), async () => {
        const d = await api(`/api/admin/declarations/${f.dataset.id}/validate`, { method: "POST", body: { items } });
        toast(`Valide : ${fcfa(d.total_amount_fcfa)}`); router();
      });
    };
    const rj = $("[data-reject]", f);
    if (rj) rj.onclick = async () => {
      const v = await ask("Rejeter la declaration", [{ name: "reason", label: "Motif", required: true }]);
      if (v) withBusy(rj, async () => { await api(`/api/admin/declarations/${f.dataset.id}/reject`, { method: "POST", body: v }); toast("Declaration rejetee"); router(); });
    };
  });
};

function drawRoute(layer, c) {
  const pts = [[c.depot_latitude, c.depot_longitude], ...c.stops.map((s) => [s.latitude, s.longitude]), [c.depot_latitude, c.depot_longitude]];
  L.polyline(pts, { color: cssVar("--primary"), weight: 4, opacity: 0.8 }).addTo(layer);
  L.marker(pts[0]).addTo(layer).bindPopup(`Depart : ${esc(c.depot_label)}`);
  c.stops.forEach((s) => L.circleMarker([s.latitude, s.longitude], dot(s.status === "FAIT" ? cssVar("--primary") : cssVar("--accent"))).addTo(layer)
    .bindTooltip(String(s.sequence), { permanent: true, direction: "center" }));
  return pts;
}

VIEWS.tournees = async () => {
  const [cand, cols] = await Promise.all([api("/api/admin/collection-candidates"), api("/api/admin/collections")]);
  const today = new Date().toISOString().slice(0, 10);
  view.innerHTML = `<h1>Tournees de collecte</h1>
    <div class="grid grid-2">
      <form class="card" id="f-plan">
        <h2>Planifier une tournee optimisee</h2>
        <div class="row">
          <div><label for="pname">Nom</label><input id="pname" name="name" value="Tournee du ${today}" required></div>
          <div><label for="pdate">Date</label><input id="pdate" name="planned_date" type="date" value="${today}" required></div>
        </div>
        <div class="row">
          <div><label for="pdepot">Depart</label><select id="pdepot" name="depot">${state.relays.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("")}</select></div>
          <div><label for="pveh">Vehicule</label><select id="pveh" name="vehicle_type"><option>TRICYCLE</option><option>CAMIONNETTE</option><option>CAMION</option></select></div>
        </div>
        <label>Signalements confirmes (${cand.reports.length})</label>
        <div class="small">${cand.reports.map((r) => `<label class="small" style="font-weight:400"><input type="checkbox" name="r" value="${r.id}" checked style="width:auto"> n°${r.id} · ${esc(r.commune || "")} · ~${kg(r.ai_estimated_weight_kg)}</label>`).join("") || "<span class='muted'>Aucun (confirme d'abord des signalements)</span>"}</div>
        <label>Collectes a domicile (${cand.declarations.length})</label>
        <div class="small">${cand.declarations.map((d) => `<label class="small" style="font-weight:400"><input type="checkbox" name="d" value="${d.id}" checked style="width:auto"> n°${d.id} · ${esc(d.user)} · ${kg(d.total_estimated_kg)}</label>`).join("") || "<span class='muted'>Aucune</span>"}</div>
        <div class="actions"><button class="btn">Calculer l'itineraire</button></div>
      </form>
      <div class="card"><h2 id="route-title">Itineraire</h2><div id="route-map" class="map tall"></div><div id="route-info" class="small"></div></div>
    </div>
    <div class="card table-wrap"><h2>Tournees</h2><table>
      <tr><th>Date</th><th>Nom</th><th>Statut</th><th class="num">Arrets</th><th class="num">Distance</th><th class="num">Cout estime</th><th class="num">Cout reel</th><th class="num">Collecte</th><th></th></tr>
      ${cols.map((c) => `<tr><td>${c.planned_date}</td><td>${esc(c.name)}</td><td>${badge(c.status)}</td><td class="num">${c.stops.length}</td>
        <td class="num">${c.total_distance_km} km</td><td class="num">${fcfa(c.estimated_cost_fcfa)}</td><td class="num">${c.real_cost_fcfa ? fcfa(c.real_cost_fcfa) : "—"}</td>
        <td class="num">${kg(c.collected_kg)}</td><td><button class="btn ghost sm" data-col="${c.id}">Ouvrir</button></td></tr>`).join("") || `<tr><td colspan="9" class="muted">Aucune tournee</td></tr>`}
    </table></div>
    <div id="col-detail"></div>`;
  const map = makeMap("route-map");
  const layer = L.layerGroup().addTo(map);
  const show = (c) => {
    layer.clearLayers();
    map.fitBounds(drawRoute(layer, c), { padding: [30, 30] });
    $("#route-title").textContent = c.name;
    $("#route-info").innerHTML = `<p><strong>${c.total_distance_km} km</strong> · ~${Math.round(c.estimated_duration_min)} min · cout estime ${fcfa(c.estimated_cost_fcfa)}</p>`;
  };
  $("#f-plan").onsubmit = (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const body = {
      name: f.get("name"), planned_date: f.get("planned_date"), vehicle_type: f.get("vehicle_type"),
      depot_relay_point_id: +f.get("depot"), report_ids: f.getAll("r").map(Number), declaration_ids: f.getAll("d").map(Number),
    };
    withBusy($("button", e.target), async () => {
      const c = await api("/api/admin/collections", { method: "POST", body });
      toast("Tournee planifiee");
      sessionStorage.setItem("open_col", c.id);
      router();
    });
  };
  const showDetail = async (id) => {
    const c = await api(`/api/admin/collections/${id}`);
    show(c);
    $("#col-detail").innerHTML = `<div class="card"><h2>${esc(c.name)} ${badge(c.status)}</h2>
      <div class="table-wrap"><table><tr><th>#</th><th>Type</th><th>Ref.</th><th class="num">Troncon</th><th>Statut</th><th class="num">Collecte</th><th></th></tr>
      ${c.stops.map((s) => `<tr><td>${s.sequence}</td><td>${s.stop_type === "SIGNALEMENT" ? "Depot sauvage" : "Domicile"}</td>
        <td>n°${s.report_id || s.declaration_id}</td><td class="num">${s.distance_from_previous_km} km</td><td>${badge(s.status)}</td>
        <td class="num">${s.collected_weight_kg != null ? kg(s.collected_weight_kg) : "—"}</td>
        <td>${s.status === "A_FAIRE" ? `<button class="btn sm" data-stop="${s.id}">Fait</button> <button class="btn ghost sm" data-ko="${s.id}">Impossible</button>` : ""}</td></tr>`).join("")}
      </table></div>
      <h3 style="margin-top:14px">Couts reels</h3>
      ${c.costs.map((x) => `<div class="small">${esc(x.cost_type)} : ${fcfa(x.amount_fcfa)} ${esc(x.note || "")}</div>`).join("") || "<p class='small muted'>Aucun cout saisi</p>"}
      <div class="actions"><button class="btn ghost sm" id="add-cost">+ Saisir un cout</button></div></div>`;
    $$("[data-stop]").forEach((b) => (b.onclick = async () => {
      const v = await ask("Poids collecte a cet arret", [{ name: "kg", label: "Poids (kg)", type: "number", required: true }]);
      if (v) withBusy(b, async () => { await api(`/api/admin/collections/${id}/stops/${b.dataset.stop}`, { method: "PATCH", body: { status: "FAIT", collected_weight_kg: +v.kg } }); showDetail(id); });
    }));
    $$("[data-ko]").forEach((b) => (b.onclick = () => withBusy(b, async () => {
      await api(`/api/admin/collections/${id}/stops/${b.dataset.ko}`, { method: "PATCH", body: { status: "IMPOSSIBLE" } }); showDetail(id);
    })));
    $("#add-cost").onclick = async () => {
      const v = await ask("Cout de collecte", [
        { name: "cost_type", label: "Type", options: [["CARBURANT", "Carburant"], ["MAIN_OEUVRE", "Main d'oeuvre"], ["VEHICULE", "Vehicule"], ["AUTRE", "Autre"]] },
        { name: "amount_fcfa", label: "Montant (FCFA)", type: "number", required: true }, { name: "note", label: "Note" },
      ]);
      if (v) withBusy(null, async () => { await api(`/api/admin/collections/${id}/costs`, { method: "POST", body: { ...v, amount_fcfa: +v.amount_fcfa } }); showDetail(id); });
    };
    $("#col-detail").scrollIntoView({ behavior: "smooth" });
  };
  $$("[data-col]").forEach((b) => (b.onclick = () => showDetail(+b.dataset.col)));
  const pending = sessionStorage.getItem("open_col");
  if (pending) { sessionStorage.removeItem("open_col"); showDetail(+pending); }
};

VIEWS.paiements = async () => {
  const rows = await api("/api/admin/payments?status=EN_ATTENTE");
  const admin = state.user.role === "admin";
  view.innerHTML = `<h1>Paiements en attente</h1>
    <p class="muted">Total : <strong>${fcfa(rows.reduce((s, p) => s + p.amount_fcfa, 0))}</strong> pour ${rows.length} usagers.</p>
    <div class="card table-wrap"><table><tr><th>Date</th><th>Usager</th><th>Declaration</th><th class="num">Montant</th><th></th></tr>
      ${rows.map((p) => `<tr><td>${dt(p.created_at)}</td><td>${esc(p.user)}</td><td>n°${p.declaration_id}</td><td class="num">${fcfa(p.amount_fcfa)}</td>
        <td>${admin ? `<button class="btn sm" data-pay="${p.id}">Marquer paye</button>` : ""}</td></tr>`).join("") || `<tr><td colspan="5" class="muted">Rien a payer</td></tr>`}
    </table></div>`;
  $$("[data-pay]").forEach((b) => (b.onclick = async () => {
    const v = await ask("Confirmer le paiement", [
      { name: "method", label: "Moyen", options: [["MOBILE_MONEY", "Mobile Money"], ["ESPECES", "Especes"], ["VIREMENT", "Virement"]] },
      { name: "reference", label: "Reference de transaction" },
    ]);
    if (v) withBusy(b, async () => { await api(`/api/admin/payments/${b.dataset.pay}`, { method: "PATCH", body: { status: "PAYEE", ...v } }); toast("Paiement enregistre"); router(); });
  }));
};

VIEWS.tarifs = async () => {
  const [hist, params] = await Promise.all([api("/api/admin/tariffs/history"), api("/api/admin/parameters")]);
  state.materials = await api("/api/materials");
  view.innerHTML = `<h1>Tarifs et parametres</h1>
    <div class="grid grid-2">
      <div class="card"><h2>Tarifs de rachat (FCFA/kg)</h2>
        ${state.materials.map((m) => `<div class="list-item row" style="align-items:center"><div><strong>${esc(m.name)}</strong> <span class="small muted">${esc(m.code)}</span></div>
          <div>${m.price_fcfa_per_kg ? `${m.price_fcfa_per_kg} F/kg` : "<span class='muted'>non rachete</span>"}</div>
          <div><button class="btn ghost sm" data-mat="${m.id}" data-price="${m.price_fcfa_per_kg || ""}">Modifier</button></div></div>`).join("")}
        <div class="actions"><button class="btn ghost sm" id="new-mat">+ Nouvelle matiere</button></div>
      </div>
      <div class="card"><h2>Parametres metier</h2>
        ${params.map((p) => `<div class="list-item row" style="align-items:center"><div><strong>${esc(p.value)}</strong><div class="small muted">${esc(p.description || p.key)}</div></div>
          <div style="flex:0 0 auto"><button class="btn ghost sm" data-param="${esc(p.key)}" data-val="${esc(p.value)}">Modifier</button></div></div>`).join("")}
      </div>
    </div>
    <div class="card table-wrap"><h2>Historique des tarifs</h2><table>
      <tr><th>Matiere</th><th class="num">Prix</th><th>Du</th><th>Au</th><th>Note</th></tr>
      ${hist.map((t) => `<tr><td>${esc(t.material)}</td><td class="num">${t.price_fcfa_per_kg} F</td><td>${dt(t.valid_from)}</td><td>${t.valid_to ? dt(t.valid_to) : "<span class='badge OK'>en vigueur</span>"}</td><td>${esc(t.note || "")}</td></tr>`).join("")}
    </table></div>`;
  $$("[data-mat]").forEach((b) => (b.onclick = async () => {
    const v = await ask("Nouveau tarif", [{ name: "price", label: "Prix (FCFA/kg)", type: "number", value: b.dataset.price, required: true }, { name: "note", label: "Motif du changement" }]);
    if (v) withBusy(b, async () => { await api(`/api/admin/materials/${b.dataset.mat}/tariff`, { method: "PUT", body: { price_fcfa_per_kg: +v.price, note: v.note || null } }); toast("Tarif mis a jour"); router(); });
  }));
  $$("[data-param]").forEach((b) => (b.onclick = async () => {
    const v = await ask(b.dataset.param, [{ name: "value", label: "Valeur", type: "number", value: b.dataset.val, required: true }]);
    if (v) withBusy(b, async () => { await api(`/api/admin/parameters/${b.dataset.param}`, { method: "PUT", body: v }); toast("Parametre enregistre"); router(); });
  }));
  $("#new-mat").onclick = async () => {
    const v = await ask("Nouvelle matiere", [
      { name: "code", label: "Code (MAJUSCULES, ex. FER)", required: true }, { name: "name", label: "Nom", required: true },
      { name: "price", label: "Prix (FCFA/kg)", type: "number", required: true },
    ]);
    if (v) withBusy(null, async () => { await api("/api/admin/materials", { method: "POST", body: { code: v.code.toUpperCase(), name: v.name, price_fcfa_per_kg: +v.price } }); toast("Matiere ajoutee"); router(); });
  };
};

VIEWS.snowflake = async () => {
  const cfg = await api("/api/admin/snowflake/config");
  const v = (x) => esc(x ?? "");
  const browserMode = cfg.authenticator !== "snowflake";
  view.innerHTML = `<h1>Snowflake & IA</h1>
    <div class="grid grid-2">
      <form class="card" id="f-sf" autocomplete="off">
        <h2>Connexion a mon compte Snowflake ${cfg.configured ? badge("OK") : `<span class="badge REJETE">non connecte</span>`}</h2>
        <label for="sf-account">Identifiant du compte</label>
        <input id="sf-account" name="account" value="${v(cfg.account)}" placeholder="monorg-moncompte" required>
        <p class="small muted">Dans Snowsight : clique sur ton nom en bas a gauche → ton compte → « View account details ». Copie « Account identifier » (format <code>orgname-accountname</code>).</p>
        <label for="sf-user">Nom d'utilisateur Snowflake</label>
        <input id="sf-user" name="user" value="${v(cfg.user)}" required>
        <label>Mode de connexion</label>
        <label class="small" style="font-weight:400"><input type="radio" name="authenticator" value="externalbrowser" ${browserMode ? "checked" : ""} style="width:auto">
          Via mon navigateur (recommande) : la page de connexion Snowflake s'ouvre, aucun mot de passe n'est enregistre</label>
        <label class="small" style="font-weight:400"><input type="radio" name="authenticator" value="snowflake" ${browserMode ? "" : "checked"} style="width:auto">
          Mot de passe (enregistre dans le fichier .env de ce PC)</label>
        <div id="sf-pwd-box" ${browserMode ? "hidden" : ""}>
          <label for="sf-pwd">Mot de passe Snowflake</label>
          <input id="sf-pwd" name="password" type="password" autocomplete="new-password" placeholder="${cfg.has_password ? "inchange si vide" : ""}">
        </div>
        <div class="row">
          <div><label for="sf-role">Role</label><input id="sf-role" name="role" value="${v(cfg.role)}" placeholder="ex. ACCOUNTADMIN ou ECOABIDJAN_APP"></div>
          <div><label for="sf-wh">Entrepot (warehouse)</label><input id="sf-wh" name="warehouse" value="${v(cfg.warehouse)}" placeholder="ex. COMPUTE_WH"></div>
        </div>
        <div class="row">
          <div><label for="sf-db">Base</label><input id="sf-db" name="database" value="${v(cfg.database ?? "ECOABIDJAN")}"></div>
          <div><label for="sf-sc">Schema</label><input id="sf-sc" name="schema" value="${v(cfg.schema ?? "CORE")}"></div>
        </div>
        <label class="small" style="font-weight:400"><input type="checkbox" name="use_cortex_for_photos" ${cfg.ai_provider === "snowflake" ? "checked" : ""} style="width:auto">
          Analyser les photos avec Snowflake Cortex AI (sinon estimation locale)</label>
        <div class="actions"><button class="btn" id="sf-save">Enregistrer et me connecter</button></div>
        <p class="small muted">En mode navigateur, une fenetre Snowflake s'ouvre a la premiere connexion : connecte-toi puis reviens ici.</p>
      </form>
      <div class="card"><h2>Diagnostic et synchronisation</h2>
        <div class="actions"><button class="btn ghost" id="diag" ${cfg.configured ? "" : "disabled"}>Lancer le diagnostic</button>
          <button class="btn ghost" id="sync" ${cfg.configured ? "" : "disabled"}>Synchroniser les donnees</button></div>
        <div id="sf-out" class="small muted" style="margin-top:12px">${cfg.configured ? "—" : "Connecte d'abord ton compte."}</div>
        <p class="notice" style="margin-top:12px">Avant la synchronisation, execute dans Snowsight les scripts <code>snowflake/01_setup.sql</code> et <code>02_tables.sql</code> du projet.</p>
      </div>
    </div>`;
  $$("input[name=authenticator]").forEach((r) => (r.onchange = () => { $("#sf-pwd-box").hidden = r.value !== "snowflake" || !r.checked; }));
  const runDiag = async () => {
    $("#sf-out").textContent = "Connexion a Snowflake… (une fenetre de connexion peut s'ouvrir)";
    const checks = await api("/api/admin/snowflake/diagnostics");
    $("#sf-out").innerHTML = `<table>${checks.map((c) => `<tr><td>${c.ok ? "✅" : "❌"}</td><td><strong>${esc(c.check)}</strong><div class="muted">${esc(c.detail)}</div></td></tr>`).join("")}</table>`;
  };
  $("#f-sf").onsubmit = (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const body = Object.fromEntries(f);
    body.use_cortex_for_photos = f.has("use_cortex_for_photos");
    for (const k of ["password", "role", "warehouse", "database", "schema"]) if (!body[k]) body[k] = null;
    withBusy($("#sf-save"), async () => {
      await api("/api/admin/snowflake/config", { method: "PUT", body });
      $("#sf-pwd").value = "";
      $("#diag").disabled = false; $("#sync").disabled = false;
      toast("Configuration enregistree");
      await runDiag();
    });
  };
  $("#diag").onclick = (e) => withBusy(e.target, runDiag);
  $("#sync").onclick = (e) => withBusy(e.target, async () => {
    const r = await api("/api/admin/snowflake/sync", { method: "POST" });
    $("#sf-out").innerHTML = `<p>Synchronisation terminee.</p><table>${Object.entries(r.tables).map(([t, n]) => `<tr><td>${esc(t)}</td><td class="num">${num(n)} lignes</td></tr>`).join("")}</table>`;
  });
};

// --- Assistant Eco ---------------------------------------------------------------
const Chat = (() => {
  const box = $("#chat"), log = $("#chat-log"), input = $("#chat-input"), sugg = $("#chat-suggest");
  let sessionId = null, loaded = false, busy = false, tts = false, lastPos = null;
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;

  const storeKey = () => `eco_chat_${state.user ? state.user.id : "anon"}`;
  const newId = () => (crypto.randomUUID ? crypto.randomUUID().replace(/-/g, "") : String(Date.now()) + Math.random().toString(36).slice(2));
  function ensureSession() {
    try { sessionId = localStorage.getItem(storeKey()); } catch { sessionId = null; }
    if (!sessionId) { sessionId = newId(); try { localStorage.setItem(storeKey(), sessionId); } catch { /* ignore */ } }
  }

  /** Markdown minimal et sur : le texte est echappe avant mise en forme. */
  function md(text) {
    const inline = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/(^|[^*])\*(?!\s)(.+?)\*/g, "$1<em>$2</em>");
    const out = []; let list = null;
    for (const raw of String(text).split("\n")) {
      const line = raw.trimEnd();
      const ul = line.match(/^\s*[-•]\s+(.*)/), ol = line.match(/^\s*\d+[.)]\s+(.*)/);
      if (ul || ol) {
        const type = ul ? "ul" : "ol";
        if (list !== type) { if (list) out.push(`</${list}>`); out.push(`<${type}>`); list = type; }
        out.push(`<li>${inline((ul || ol)[1])}</li>`);
      } else {
        if (list) { out.push(`</${list}>`); list = null; }
        if (line.trim()) out.push(`<p>${inline(line)}</p>`);
      }
    }
    if (list) out.push(`</${list}>`);
    return out.join("");
  }

  function add(role, text, extra = {}) {
    const div = document.createElement("div");
    div.className = `msg ${role === "user" ? "user" : "bot"}`;
    div.innerHTML = role === "user" ? esc(text) : md(text);
    if (extra.links?.length && state.user) {
      div.insertAdjacentHTML("beforeend", `<div class="msg-links">${extra.links.map((l) => `<a href="#${esc(l.route)}">${esc(l.label)}</a>`).join("")}</div>`);
      $$(".msg-links a", div).forEach((a) => (a.onclick = () => { if (window.innerWidth < 600) close(); }));
    }
    if (extra.meta) div.insertAdjacentHTML("beforeend", `<div class="msg-meta">${esc(extra.meta)}</div>`);
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
    return div;
  }

  function setSuggestions(list) {
    sugg.innerHTML = (list || []).map((s) => `<button type="button">${esc(s)}</button>`).join("");
    $$("button", sugg).forEach((b) => (b.onclick = () => send(b.textContent)));
  }

  function speak(text) {
    if (!tts || !window.speechSynthesis) return;
    speechSynthesis.cancel();
    const clean = text.replace(/[*_#>`]/g, "").replace(/[\u{1F300}-\u{1FAFF}☀-➿]/gu, "");
    const u = new SpeechSynthesisUtterance(clean);
    u.lang = "fr-FR";
    const fr = speechSynthesis.getVoices().find((v) => v.lang?.startsWith("fr"));
    if (fr) u.voice = fr;
    speechSynthesis.speak(u);
  }

  const engineLabel = (p) => (p === "snowflake-cortex" ? "Propulse par Snowflake Cortex AI" : "Assistant EcoAbidjan");

  async function load() {
    ensureSession();
    log.innerHTML = "";
    try {
      const [w, hist] = await Promise.all([api("/api/assistant/welcome"), api(`/api/assistant/history?session_id=${sessionId}`)]);
      $("#chat-engine").textContent = engineLabel(w.provider);
      add("bot", w.reply);
      hist.forEach((m) => add(m.role, m.content));
      setSuggestions(w.suggestions);
      loaded = true;
    } catch (e) { add("bot", "Je n'arrive pas a joindre le serveur pour le moment."); }
  }

  async function send(text) {
    text = (text || "").trim();
    if (!text || busy) return;
    busy = true;
    input.value = "";
    add("user", text);
    setSuggestions([]);
    const typing = add("bot", "");
    typing.innerHTML = `<span class="typing" aria-label="Eco ecrit"><span></span><span></span><span></span></span>`;
    // Position pour les questions de proximite (si l'usager l'a autorisee)
    if (!lastPos && /proche|relais|pres de|deposer|où|ou est/i.test(text)) {
      try { lastPos = await Promise.race([getPosition(), new Promise((_, r) => setTimeout(() => r(new Error("delai")), 6000))]); } catch { /* sans position */ }
    }
    try {
      const body = { message: text, session_id: sessionId };
      if (lastPos) [body.latitude, body.longitude] = lastPos;
      const r = await api("/api/assistant/chat", { method: "POST", body });
      typing.remove();
      add("bot", r.reply, { links: r.links });
      $("#chat-engine").textContent = engineLabel(r.provider);
      setSuggestions(r.suggestions);
      speak(r.reply);
    } catch (e) {
      typing.remove();
      add("bot", `Desole, une erreur est survenue : ${e.message}`);
    } finally { busy = false; input.focus(); }
  }

  function open() {
    box.hidden = false; $("#chat-fab").hidden = true;
    if (!loaded) load();
    setTimeout(() => input.focus(), 50);
  }
  function close() { box.hidden = true; $("#chat-fab").hidden = false; if (window.speechSynthesis) speechSynthesis.cancel(); }

  $("#chat-fab").onclick = open;
  $("#chat-close").onclick = close;
  $("#chat-form").onsubmit = (e) => { e.preventDefault(); send(input.value); };
  $("#chat-reset").onclick = () => { try { localStorage.removeItem(storeKey()); } catch { /* ignore */ } loaded = false; load(); };
  $("#chat-tts").onclick = (e) => {
    tts = !tts; e.currentTarget.setAttribute("aria-pressed", String(tts)); e.currentTarget.textContent = tts ? "🔊" : "🔈";
    if (!window.speechSynthesis) toast("Lecture vocale non disponible sur ce navigateur", true);
  };
  const mic = $("#chat-mic");
  if (!Recognition) mic.hidden = true;
  else mic.onclick = () => {
    const rec = new Recognition();
    rec.lang = "fr-FR"; rec.interimResults = true; rec.maxAlternatives = 1;
    mic.classList.add("listening");
    rec.onresult = (ev) => {
      const t = [...ev.results].map((r) => r[0].transcript).join("");
      input.value = t;
      if (ev.results[ev.results.length - 1].isFinal) send(t);
    };
    rec.onerror = () => toast("Micro indisponible ou refuse", true);
    rec.onend = () => mic.classList.remove("listening");
    rec.start();
  };
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !box.hidden) close(); });

  return { userChanged() { loaded = false; if (!box.hidden) load(); }, open };
})();

// --- Demarrage ------------------------------------------------------------------
async function boot() {
  try {
    [state.communes, state.materials, state.relays] = await Promise.all([api("/api/communes"), api("/api/materials"), api("/api/relay-points")]);
  } catch (e) { toast("Serveur injoignable : " + e.message, true); }
  if (state.token) {
    try { state.user = await api("/api/me"); } catch { state.token = null; }
  }
  window.addEventListener("hashchange", router);
  router();
}
boot();
