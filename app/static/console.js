// Growth Command: operator console for Parinita GrowthOS.
// No framework, no build step, no third-party origin. Every piece of content is written with textContent
// (never innerHTML): release copy and ingested feed items are untrusted input.

const PUSH = new Set(["webhook", "rest_json", "smtp", "linkedin", "x", "mastodon", "bluesky", "transistor", "buzzsprout", "pr_wire",
                      "slack", "teams", "discord", "telegram", "whatsapp", "wordpress", "mcp", "vaak", "ai_studio",
  "reddit", "facebook", "instagram", "threads", "pinterest", "tiktok", "tumblr", "lemmy", "etsy", "shopify", "google_business", "devto", "ghost", "buttondown", "mailchimp", "google_chat", "mattermost", "matrix", "zulip"]);
const HIGH_RISK = new Set(["investor", "regulated", "legal", "health", "financial"]);
const TABS = [["work", "Needs work", ["draft", "blocked"]], ["ready", "Ready", ["approved"]], ["sent", "Sent", ["published"]]];
const STATE_WORD = { draft: "Draft", blocked: "Blocked", approved: "Ready", published: "Sent" };

const S = { cfg: null, key: sessionStorage.getItem("growthos.key") || "", me: null, view: "overview", tab: "work", items: [], sel: null,
            detail: null, openLine: null, feeds: [], err: "", ok: "", editing: false, creating: false, audit: null, chain: null, intelligence: null };
const root = document.getElementById("app");

// ---------------------------------------------------------------- helpers
function h(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (v === true) n.setAttribute(k, "");
    else n.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    n.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return n;
}
const safeHref = (u) => (/^https?:\/\//i.test(u || "") || (u || "").startsWith("/") ? u : null);
const can = (role) => !!S.me && (S.me.roles.includes(role) || (S.me.roles.includes("admin") && role !== "approver"));
const humanOk = () => !S.cfg.approvals_need_sso || S.me.source === "sso";
const when = (iso) => { const d = new Date(iso); return isNaN(d) ? "" : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }); };
const val = (id) => (document.getElementById(id)?.value ?? "").trim();

async function api(path, { method = "GET", body } = {}) {
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (S.key) headers["X-API-Key"] = S.key;
  else if (S.me?.csrf && method !== "GET") headers["X-CSRF-Token"] = S.me.csrf;
  const r = await fetch(path, { method, headers, credentials: "same-origin", body: body === undefined ? undefined : JSON.stringify(body) });
  const text = await r.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!r.ok) {
    const d = data && data.detail;
    const msg = typeof d === "string" ? d : Array.isArray(d) ? d.map((x) => x.msg).join("; ") : `The server answered ${r.status}.`;
    throw Object.assign(new Error(msg), { status: r.status });
  }
  return data;
}

// Run an action, then repaint. Errors are shown where the person is working, in plain words.
async function act(fn, okMessage = "") {
  S.err = ""; S.ok = "";
  root.setAttribute("aria-busy", "true");
  try { await fn(); S.ok = okMessage; }
  catch (e) {
    if (e.status === 401) { S.me = null; S.key = ""; sessionStorage.removeItem("growthos.key"); S.err = "Your session ended. Sign in again."; }
    else S.err = e.message;
  }
  root.removeAttribute("aria-busy");
  render();
}

const metric = (label, number, detail) => h("div", { class: "metric" }, h("span", {}, label), h("strong", {}, number), h("small", {}, detail));

// ---------------------------------------------------------------- data
async function loadQueue() { S.items = await api("/v1/content?limit=200"); }
async function loadDetail(id) {
  const [item, gate, ledger, deliveries] = await Promise.all([
    api(`/v1/content/${encodeURIComponent(id)}`), api(`/v1/content/${encodeURIComponent(id)}/gate`),
    api(`/v1/content/${encodeURIComponent(id)}/assertions`), api(`/v1/content/${encodeURIComponent(id)}/deliveries`)]);
  S.detail = { item, gate, ledger: ledger.sentences, deliveries };
  S.sel = id;
}
async function refresh() {
  await loadQueue();
  S.feeds = await api("/v1/feeds");
  S.connectors = await api("/v1/connectors");
  S.credentialVault = can("admin") ? await api("/v1/connector-credentials") : null;
  S.connectorReadiness = can("admin") ? await api("/v1/connectors/readiness") : null;
  if (S.sel && S.items.some((i) => i.id === S.sel)) {
    await loadDetail(S.sel);
    const home = TABS.find(([, , states]) => states.includes(S.detail.item.state));
    if (home) S.tab = home[0];   // follow the release when its state changes
  } else { S.sel = null; S.detail = null; }
}
const path = (suffix = "") => `/v1/content/${encodeURIComponent(S.sel)}${suffix}`;

// ---------------------------------------------------------------- sign in
function viewSignIn() {
  const box = h("div", { class: "signin" }, h("h1", {}, "Growth Command"),
    h("p", {}, "Review, approve and send governed releases."));
  if (S.err) box.append(h("p", { class: "error", role: "alert" }, S.err));
  if (S.cfg.sso) box.append(h("a", { class: "btn primary", href: "/auth/login?next=/console" }, `Sign in with ${S.cfg.sso_label || "your company account"}`));
  if (S.cfg.sso && S.cfg.api_keys) box.append(h("hr"));
  if (S.cfg.api_keys) {
    box.append(h("form", { onsubmit: (e) => { e.preventDefault(); const k = val("key"); act(async () => {
      S.key = k; const cfg = await api("/auth/config");
      if (!cfg.me) { S.key = ""; throw new Error("That access key was not recognised."); }
      S.me = cfg.me;
      sessionStorage.setItem("growthos.key", k); await refresh(); }); } },
      h("div", { class: "field" }, h("label", { for: "key" }, "Access key"), h("input", { id: "key", type: "password", autocomplete: "off", required: true })),
      h("button", { class: S.cfg.sso ? "btn" : "btn primary", type: "submit" }, "Sign in with an access key"),
      S.cfg.approvals_need_sso ? h("p", { class: "note" }, "Access keys cannot approve releases here. Approvals need a company sign-in.") : null));
  }
  return h("div", { class: "auth-layout" }, h("section", { class: "auth-story" },
    h("div", { class: "brand" }, "parinita", h("span", {}, "GROWTH OS")),
    h("div", {}, h("p", { class: "eyebrow" }, "THE GROWTH COMMAND CENTER"), h("h2", {}, "Good stories.\nGrounded in proof."),
      h("p", {}, "Bring your content, evidence, approvals and distribution into one accountable workspace."),
      h("div", { class: "auth-path" }, "Prepare", h("span", {}, "→"), "Prove", h("span", {}, "→"), "Publish")),
    h("p", { class: "auth-caption" }, "Agents prepare. People authorize. Every release leaves a record.")), box);
}

// ---------------------------------------------------------------- frame
function bar() {
  const nav = h("nav", { "aria-label": "Sections" },
    ...[["overview", "Overview", "◫"], ...(can("admin") ? [["setup", "Company setup", "⚙"]] : []), ["create", "Drafting studio", "✎"], ["brand", "Brand voice", "◎"], ["releases", "Releases", "▤"], ["podcast", "Podcast", "◉"], ["intelligence", "Intelligence", "◈"], ["agents", "Agents", "✧"], ["destinations", "Destinations", "↗"], ["audit", "Audit", "☷"]].map(([v, label, icon]) =>
      h("button", { type: "button", "aria-current": S.view === v ? "page" : null, onclick: () => navigate(v) }, h("span", { class: "nav-icon", "aria-hidden": "true" }, icon), label)));
  return h("header", { class: "bar" }, h("div", { class: "brand" }, "parinita", h("span", {}, "GROWTH OS")),
    h("div", { class: "workspace-label" }, h("span", { class: "workspace-avatar", "aria-hidden": "true" }, "P"), h("div", {}, S.cfg.company_name || "Growth workspace", h("small", {}, "Communications & growth"))),
    h("p", { class: "nav-label" }, "WORKSPACE"), nav,
    h("div", { class: "side-message" }, h("strong", {}, "One release. One proof path."), h("p", {}, "Human authority at every gate.")),
    h("div", { class: "who" }, h("strong", { title: S.me.principal }, S.me.principal), h("span", {}, S.me.roles.join(", ") || "no role assigned"),
      h("button", { type: "button", onclick: () => act(async () => {
        if (!S.key) await api("/auth/logout", { method: "POST" });
        S.key = ""; sessionStorage.removeItem("growthos.key"); S.me = null; S.detail = null; S.sel = null; }) }, "Sign out")));
}
const notices = () => [S.err ? h("p", { class: "error", role: "alert" }, S.err) : null, S.ok ? h("p", { class: "done", role: "status" }, S.ok) : null];

function navigate(v) {
  return act(async () => { S.view = v; if (v === "audit") await loadAudit(); else if (v === "intelligence") await loadIntelligence();
    else if (v === "agents") S.agents = await api("/v1/agents");
    else if (v === "setup") S.setup = await api("/v1/workspace/setup");
    else if (v === "brand") S.brand = await api("/v1/drafting/brand");
    else if (v === "create" || v === "podcast") { S.draftFormat = v === "podcast" ? "podcast" : (S.draftFormat || "press_release"); S.drafting = null; S.drafting = await api("/v1/drafting/status"); }
    else await refresh(); });
}
function beginRelease() { S.view = "releases"; S.creating = true; S.sel = null; S.detail = null; S.err = ""; S.ok = ""; render(); }
function openRelease(id) { return act(async () => { S.view = "releases"; S.creating = false; S.editing = false; S.openLine = null; await loadDetail(id);
  S.tab = (TABS.find(([, , states]) => states.includes(S.detail.item.state)) || TABS[0])[0]; }); }
const eyebrow = (text) => h("p", { class: "eyebrow" }, text);
function topstrip() {
  const labels = { setup: "Company setup", overview: "Overview", create: "Drafting studio", brand: "Brand voice", podcast: "Podcast studio", releases: "Release desk", intelligence: "Intelligence", agents: "Agent directory", destinations: "Distribution", audit: "Audit trail" };
  return h("div", { class: "topstrip" }, h("div", {}, h("span", {}, "Workspace"), h("span", { class: "crumb-divider" }, "/"), h("strong", {}, labels[S.view])),
    h("div", { class: "row" }, h("span", { class: "connection-badge" }, location.hostname === "127.0.0.1" || location.hostname === "localhost" ? "Local workspace" : "Connected workspace"),
      h("button", { class: "btn quiet", type: "button", onclick: () => navigate(S.view), "aria-label": "Refresh workspace" }, "↻ Refresh")));
}
function viewSetup() {
  const setup = S.setup;
  const actions = {credentials:["Manage account credentials","destinations"],brand:["Set brand voice","brand"],sources:["Connect source feeds","destinations"],destinations:["Connect accounts","destinations"],model:["Open drafting studio","create"]};
  return h("div",{class:"page"},h("h1",{},setup?.company_name || "Company setup"), ...notices(),
    h("p",{},"Set up this company's sources, brand voice and distribution accounts."),
    h("div",{class:"metrics"},...(setup?.checks || []).map(c=>h("section",{class:"panel"},h("h2",{},c.label),
      h("strong",{},c.ready?"Configured":"Needs setup"),h("p",{},c.detail),actions[c.id]?h("button",{class:"btn",type:"button",onclick:()=>navigate(actions[c.id][1])},actions[c.id][0]):null))),
    h("p",{class:"note"},"Configured means settings are present. Confirm account access, test delivery, and complete production checks before launch."));
}

function viewOverview() {
  const working = S.items.filter(i => ["draft", "blocked"].includes(i.state)).length;
  const ready = S.items.filter(i => i.state === "approved").length;
  const sent = S.items.filter(i => i.state === "published").length;
  const enabled = S.feeds.filter(f => f.enabled).length;

  const action = (label, fn, primary = false) => h("button", { class: primary ? "btn primary" : "btn", type: "button", onclick: fn }, label);
  const step = (n, title, description, complete, fn) => h("button", { class: "setup-step", type: "button", onclick: fn },
    h("span", { class: complete ? "step-index complete" : "step-index", "aria-hidden": "true" }, complete ? "✓" : n), h("span", {}, h("strong", {}, title), h("small", {}, description)), h("span", { "aria-hidden": "true" }, "↗"));
  const recent = h("section", { class: "panel recent queue" }, h("div", { class: "panel-heading" }, h("div", {}, eyebrow("THE RELEASE DESK"), h("h2", {}, "Your latest stories")), action("View all", () => navigate("releases"))),
    S.items.length ? h("ul", {}, ...S.items.slice(0, 6).map(i => h("li", {}, h("button", { type: "button", onclick: () => openRelease(i.id) },
      h("span", { class: "release-symbol", "aria-hidden": "true" }, "▤"), h("span", { class: "recent-copy" }, h("span", { class: "t" }, i.title), h("span", { class: "m" }, i.classification, " · ", when(i.updated_at || i.created_at))),
      h("span", { class: `status-pill ${i.state}` }, STATE_WORD[i.state] || i.state))))) :
    h("div", { class: "welcome-empty" }, h("div", { class: "empty-symbol", "aria-hidden": "true" }, "▤"), h("h3", {}, "Your first story starts here."),
      h("p", {}, "Give GrowthOS a brief and source material. Get a draft to refine and bring through review."), can("editor") ? action("Create your first release", () => navigate("create"), true) : h("p", { class: "note" }, "An editor can create your first release.")));
  return h("div", { class: "page overview" }, h("div", { class: "page-heading" }, h("div", {}, eyebrow("YOUR GROWTH, GOVERNED"), h("h1", {}, "Your growth, in focus."),
    h("p", {}, "The work, the proof and the next move. All in one place.")), can("editor") ? action("＋ Create content", () => navigate("create"), true) : null), ...notices(),
    h("section", { class: "command-banner" }, h("div", {}, eyebrow(S.items.length ? "KEEP THE WORK MOVING" : "WELCOME TO YOUR WORKSPACE"), h("h2", {}, S.items.length ? `${working} ${working === 1 ? "story needs" : "stories need"} your attention.` : "Build momentum. Start with one story."),
      h("p", {}, "Move from a clear message to evidence-backed content, human review and coordinated distribution."),
      action(S.items.length ? "Open the release desk →" : "Draft with GrowthOS →", S.items.length ? () => navigate("releases") : () => navigate("create"), true)),
      h("div", { class: "workflow-map", "aria-label": "Release workflow" }, ...["01 / Prepare", "02 / Prove", "03 / Approve", "04 / Distribute"].map(t => h("div", {}, h("span", {}, t.split(" / ")[0]), h("strong", {}, t.split(" / ")[1]))))),
    h("div", { class: "metrics" }, metric("In progress", working, "Drafts & releases needing work"), metric("Ready to release", ready, "Current approved releases"), metric("Published", sent, "Releases with a sent state"), metric("Enabled destinations", enabled, `${S.feeds.length} configured · credentials not verified`)),
    h("div", { class: "overview-grid" }, recent, h("section", { class: "panel setup" }, h("div", { class: "panel-heading" }, h("div", {}, eyebrow("A CLEAR PATH FORWARD"), h("h2", {}, "Workspace essentials"))),
      step("01", "Create a governed release", "One master message, with sources attached.", S.items.length > 0, () => navigate("releases")),
      step("02", "Set up distribution", "Connect where your approved content goes.", S.feeds.length > 0, () => navigate("destinations")),
      step("03", "Explore your growth team", "Discover the agents and their responsibilities.", false, () => navigate("agents")),
      step("04", "Read the signals", "Review observed outcomes and opportunities.", false, () => navigate("intelligence")),
      h("p", { class: "setup-note" }, "No sample activity. This workspace reflects your actual application data."))),
    h("p", { class: "dashboard-footnote" }, "Release counts cover the latest 200 records. Publishing still requires the release gate and your destination configuration."));
}
function viewAgents() {
  const entries = Object.entries(S.agents || {});
  return h("div", { class: "page agents-page" }, eyebrow("SPECIALIST CAPABILITIES"), h("h1", {}, "Meet your growth team."), h("p", {}, `${entries.length} capabilities, each with a defined role. Agents prepare work; human approval remains separate.`), ...notices(),
    h("div", { class: "agent-grid" }, ...entries.map(([id, a]) => h("section", { class: "panel agent-card" },
      h("div", { class: "agent-avatar", "aria-hidden": "true" }, (a.identity || a.name || id).slice(0, 1)), h("span", { class: "agent-mode" }, a.mode),
      h("h2", {}, a.name.replace("Parinita GrowthOS ", "")), h("p", { class: "agent-function" }, id === "feed" ? "Governed distribution" : id.replaceAll("_", " ")),
      h("ul", {}, ...(a.actions || []).map(t => h("li", {}, t.replaceAll("-", " ")))), h("p", { class: "note" }, a.can_publish ? "Can transmit only through publishing controls." : "Cannot publish or grant human approval.")))),
    h("div", { class: "agent-next" }, h("p", {}, "Agent work starts with a governed release. Open a release to run its preparation checks."), h("button", { class: "btn primary", type: "button", onclick: () => navigate("releases") }, "Go to release desk")));
}

function viewCreation() {
  const podcast = S.view === "podcast";
  const formats = [["press_release", "Press release", "▤"], ["social", "Social message", "↗"], ["email", "Email message", "✉"], ["podcast", "Podcast script", "◉"]];
  const connected = S.drafting?.configured;
  const field = (id, label, control) => h("div", { class: "field" }, h("label", { for: id }, label), control);
  const note = connected ? `Connected to ${S.drafting.model}. Generated copy is saved as a draft for your review.` :
    "A language model has not been connected yet. Once connected, GrowthOS can turn your brief into original copy. You can write a draft manually now.";
  return h("div", { class: "page creation-studio" }, eyebrow(podcast ? "ORATOR / PODCAST STUDIO" : "FROM BRIEF TO FIRST DRAFT"),
    h("h1", {}, podcast ? "Give your story a voice." : "What would you like to create?"),
    h("p", {}, podcast ? "Prepare a spoken script and show notes from your source material. Audio production is a separate step." : "Bring the facts and the goal. GrowthOS prepares the words for your review."), ...notices(),
    h("div", { class: "generation-note", role: "status" }, h("strong", {}, connected ? "Drafting is connected" : "Model connection needed"), h("p", {}, note)),
    h("div", { class: "format-grid", "aria-label": "Content format" }, ...formats.map(([id, label, icon]) => h("button", { type: "button", class: "format-card", "aria-pressed": String(S.draftFormat === id),
      onclick: () => { S.draftFormat = id; render(); } }, h("span", { "aria-hidden": "true" }, icon), label))),
    h("form", { class: "panel studio-form", onsubmit: e => { e.preventDefault(); if (S.generating) return; S.generating = true;
      const pack = e.submitter?.dataset.campaign === "true";
      e.currentTarget.querySelectorAll('button[type="submit"]').forEach(b => { b.disabled = true; }); e.submitter.textContent = pack ? "Preparing four drafts…" : "Drafting…";
      const brief = { format: S.draftFormat, brief: val("brief-goal"), source_material: val("brief-sources"), audience: val("brief-audience"), tone: val("brief-tone"), classification: val("brief-class"), parent_id: S.reviseSource?.id || null };
      act(async () => { try { const result = await api(pack ? "/v1/drafting/campaign" : "/v1/drafting/drafts", { method: "POST", body: brief }); const item = pack ? result.items[0] : result;
          await loadQueue(); await loadDetail(item.id); S.view = "releases"; S.creating = false; S.tab = "work"; S.reviseSource = null; }
        finally { S.generating = false; } }, "Draft generated. Review the copy and attach evidence before running release checks."); } },
      h("h2", {}, S.reviseSource ? "Create another version" : "Your brief"),
      h("p", {class:"note"}, S.reviseSource ? "Your original draft is preserved. Describe what the next version should change." : `${S.drafting?.specialists?.[S.draftFormat]?.agent || "Your specialist"} writes this format using your saved brand voice.`),
      field("brief-goal", "What should this content achieve?", h("textarea", { id: "brief-goal", rows: "3", minlength: "10", maxlength: "6000", required: true, placeholder: "Describe the announcement, message or episode you want to create…" }, S.reviseSource?.metadata?.drafting?.brief || "")),
      field("source-library", "Use material already in your workspace", h("select",{id:"source-library",onchange:e=>{
        const source=S.items.find(x=>x.id===e.target.value);const box=document.getElementById("brief-sources");
        if(source && box){const addition=`${source.title}\n${source.body}\nSource: ${source.source || source.id}`;
          if(box.value.length+addition.length+2>24000){S.err="Source material exceeds 24,000 characters. Shorten it before adding another item.";render();return;}
          box.value += (box.value?"\n\n":"")+addition;}e.target.value="";
      }},h("option",{value:""},"Choose a source or previous release"),...S.items.map(x=>h("option",{value:x.id},x.title)))),
      field("brief-sources", "Facts and source material", h("textarea", { id: "brief-sources", rows: "6", minlength: "10", maxlength: "24000", required: true, placeholder: "Paste the confirmed facts, product notes or supporting material. Include source references where available. Links alone are not fetched." }, S.reviseSource?.metadata?.drafting?.source_material || "")),
      h("div", { class: "draft-options" }, field("brief-audience", "Who is this for?", h("input", { id: "brief-audience", type: "text", maxlength: "500", placeholder: "For example: customers, journalists or podcast listeners" })),
        field("brief-tone", "Tone", h("select", { id: "brief-tone" }, ...["professional", "conversational", "concise"].map(t => h("option", { value: t }, t[0].toUpperCase() + t.slice(1))))),
        field("brief-class", "Review category", h("select", { id: "brief-class" }, ...["pr", "social", "general", "investor", "regulated", "financial", "legal", "health"].map(t => h("option", { value: t }, t))))),
      h("p", { class: "note" }, "Source notes guide drafting; they are not automatically marked as verified evidence. Nothing is approved, voiced or sent by this action."),
      h("div", { class: "row" }, h("button", { type: "submit", class: "btn primary", disabled: !connected || !can("editor") || S.generating }, S.generating ? "Drafting…" : "Generate draft"),
        h("button", { type: "submit", "data-campaign": "true", class: "btn", disabled: !connected || !can("editor") || S.generating }, "Create four-format campaign"),
        h("button", { type: "button", class: "btn", disabled: !can("editor"), onclick: beginRelease }, "Write manually"))),
    podcast ? h("section", { class: "podcast-production" }, h("h2", {}, "From script to episode"),
      h("p", { class: "note" }, "Review the generated script in the release desk. Voice production requires a configured Vaak voice and consent. Approved audio can then use Podcast RSS, Transistor or Buzzsprout destinations."),
      h("button", { class: "btn", type: "button", onclick: () => navigate("destinations") }, "View production destinations")) : null);
}

function viewBrand() {
  const fields = [["name", "Brand name", 1], ["voice", "Voice and writing rules", 4], ["audience", "Default audience", 2], ["example", "Example of your preferred writing", 6], ["excluded_phrases", "Phrases to avoid (one per line)", 3]];
  return h("div", {class:"page creation-studio"}, eyebrow("CONSISTENT ACROSS EVERY CHANNEL"), h("h1", {}, "Make it sound like you."),
    h("p", {}, "These instructions guide every writing specialist. Examples guide style; they are not used as factual sources."), ...notices(),
    h("form", {class:"panel studio-form", onsubmit:e=>{e.preventDefault(); act(async()=>{
      const body = Object.fromEntries(fields.map(([key])=>[key,val(`brand-${key}`)]));
      S.brand = await api("/v1/drafting/brand", {method:"PUT",body});
    },"Brand voice saved for future drafts.");}}, ...fields.map(([key,label,rows])=>h("div", {class:"field"},
      h("label", {for:`brand-${key}`},label), h("textarea", {id:`brand-${key}`,rows,disabled:!can("admin")},S.brand?.[key]||""))),
      h("button", {type:"submit",class:"btn primary",disabled:!can("admin")},"Save brand voice"),
      !can("admin") ? h("p", {class:"note"},"An administrator can update the shared brand voice.") : null));
}

function draftingNotes(item) {
  const d = item.metadata?.drafting;
  if (!d) return null;
  const review = item.metadata?.editorial_review;
  const current = review?.content_hash === item.content_hash;
  const siblings = S.items.filter(i => item.campaign_id && i.campaign_id === item.campaign_id && i.id !== item.id);
  return h("section", {class:"drafting-notes"}, h("h2", {}, "Writing & review"),
    h("p", {class:"note"}, `${d.agent || "Specialist"} · ${d.model} · ${d.quality?.word_count ?? item.body.split(/\s+/).length} words at generation. Human source review is still required.`),
    h("div", {class:"row"}, h("button", {class:"btn",type:"button",disabled:!can("editor"),onclick:()=>act(async()=>{
      await api(`/v1/drafting/${encodeURIComponent(item.id)}/review`,{method:"POST"}); await loadDetail(item.id);
    },"AI editorial review recorded. This does not approve the draft.")}, "Review with AI"),
    h("button", {class:"btn",type:"button",disabled:!can("editor"),onclick:()=>{S.reviseSource=item;S.draftFormat=d.format;return navigate("create");}},"Create another version"),
    h("button", {class:"btn",type:"button",onclick:()=>{
      const file = new Blob([`DRAFT — FOR REVIEW\n\n${item.title}\n\n${item.body}\n\n${item.summary}`],{type:"text/plain;charset=utf-8"});
      const url=URL.createObjectURL(file);const a=h("a",{href:url,download:`growthos-${item.id}.txt`});a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    }},"Download draft")),
    siblings.length ? h("div", {class:"campaign-links"},h("strong",{},"In this campaign"),...siblings.map(i=>h("button",{class:"btn quiet",type:"button",onclick:()=>openRelease(i.id)},i.content_type))) : null,
    h("details",{},h("summary",{},"Original brief and sources"),h("p",{},d.brief),h("pre",{class:"source-notes"},d.source_material)),
    d.quality?.issues?.length ? h("div",{class:"editorial-findings"},h("h3",{},"Checks at generation"),...d.quality.issues.map(i=>h("p",{},`${i.text}: ${i.message}`))) : h("p",{class:"note"},"Mechanical checks at generation found no issues. This is not a factual verification."),
    review ? h("div",{class:"editorial-findings"},h("h3",{},current?"AI editorial suggestions":"Earlier AI review — rerun after edits"),
      ...review.findings.map(f=>h("p",{},h("strong",{},f.excerpt)," — ",f.reason)),
      h("p",{class:"note"},review.findings.length?review.scope:"No unsupported passages detected by the model. Review sources yourself before approval.")) : null);
}

// ---------------------------------------------------------------- releases
function queue() {
  const groups = Object.fromEntries(TABS.map(([k, , states]) => [k, S.items.filter((i) => states.includes(i.state))]));
  const list = groups[S.tab];
  return h("aside", { class: "queue", "aria-label": "Releases" },
    h("div", { class: "tabs", role: "tablist" }, ...TABS.map(([k, label]) =>
      h("button", { type: "button", role: "tab", "aria-selected": String(S.tab === k), onclick: () => { S.tab = k; render(); } },
        label, h("span", { class: "n" }, groups[k].length)))),
    list.length ? h("ul", {}, ...list.map((i) => h("li", {}, h("button", { type: "button", "aria-current": S.sel === i.id ? "true" : null,
      onclick: () => act(async () => { S.creating = false; S.editing = false; S.openLine = null; await loadDetail(i.id); }) },
      h("span", { class: "t" }, i.title), h("span", { class: "m" }, h("span", { class: `state ${i.state}` }, STATE_WORD[i.state] || i.state),
        h("span", {}, i.classification), h("span", {}, when(i.updated_at || i.created_at)))))))
      : h("p", { class: "empty" }, S.tab === "work" ? "Nothing is waiting. New and blocked releases appear here." : "Nothing here yet."),
    can("editor") ? h("div", { class: "new" }, h("button", { class: "btn", type: "button", onclick: () => { S.creating = true; S.sel = null; S.detail = null; S.err = ""; S.ok = ""; render(); } }, "New release")) : null);
}

function newRelease() {
  return h("div", { class: "proofwrap" }, h("form", { class: "proof", style: null, onsubmit: (e) => { e.preventDefault(); act(async () => {
      const created = await api("/v1/content", { method: "POST", body: { title: val("n-title"), body: document.getElementById("n-body").value,
        classification: val("n-class"), cta_url: val("n-cta"), content_type: val("n-class") === "pr" ? "press_release" : "article" } });
      S.creating = false; S.tab = "work"; await loadQueue(); await loadDetail(created.id); }, "Draft saved. Every sentence now needs evidence or a reviewer's decision."); } },
    h("div", { class: "editor" }, ...notices(), h("h2", {}, "New release"),
      h("div", { class: "field" }, h("label", { for: "n-title" }, "Headline"), h("input", { id: "n-title", type: "text", required: true, maxlength: "500" })),
      h("div", { class: "field" }, h("label", { for: "n-class" }, "Kind"), h("select", { id: "n-class" },
        ...["pr", "social", "general", "investor", "regulated", "financial", "legal", "health"].map((c) => h("option", { value: c }, c)))),
      h("div", { class: "field" }, h("label", { for: "n-body" }, "Copy"), h("textarea", { id: "n-body", required: true, rows: "10" })),
      h("div", { class: "field" }, h("label", { for: "n-cta" }, "Link for readers (optional)"), h("input", { id: "n-cta", type: "url", placeholder: "https://" })),
      h("div", { class: "row" }, h("button", { class: "btn primary", type: "submit" }, "Save draft"),
        h("button", { class: "btn", type: "button", onclick: () => { S.creating = false; render(); } }, "Cancel")))));
}

function resolvePanel(row, item) {
  const waiverRole = S.cfg.waiver_role || "approver";
  const mayWaive = can(waiverRole) && humanOk();
  const left = h("div", {}, h("h3", {}, "Add evidence"),
    h("div", { class: "field" }, h("label", { for: "c-text" }, "What the source supports"), h("textarea", { id: "c-text", rows: "3" }, row.text)),
    h("div", { class: "field" }, h("label", { for: "c-src" }, "Source"), h("input", { id: "c-src", type: "text", placeholder: "https://…  or  internal://memo-id" })),
    h("div", { class: "field" }, h("label", { for: "c-type" }, "Type"), h("select", { id: "c-type" },
      h("option", { value: "fact" }, "Fact"), h("option", { value: "quote" }, "Quotation"), h("option", { value: "forecast" }, "Forecast"))),
    h("button", { class: "btn primary", type: "button", disabled: !can("editor"), onclick: () => act(async () => {
      const type = val("c-type"), src = val("c-src");
      if (type !== "forecast" && !src) throw new Error("Give the source for this statement, for example a URL or internal://memo-id.");
      const claim = { text: val("c-text") || row.text, claim_type: type, sources: src ? [{ uri: src }] : [], covers: [row.hash] };
      await api(path(), { method: "PATCH", body: { claims: [...item.claims, claim] } });
      S.openLine = null; await refresh(); }, "Evidence added. Run checks to update the verdict.") }, "Add evidence"),
    can("editor") ? null : h("p", { class: "note" }, "Adding evidence needs the editor role."));
  const right = h("div", {}, h("h3", {}, "Let it stand"),
    row.suggestion === "opinion" ? h("p", { class: "note" }, "This reads as a statement of opinion.") : null,
    h("div", { class: "field" }, h("label", { for: "d-kind" }, "Why no evidence is needed"), h("select", { id: "d-kind" },
      h("option", { value: "opinion" }, "Opinion or stance"), h("option", { value: "boilerplate" }, "Standard wording"), h("option", { value: "not_factual" }, "Not a factual statement"))),
    h("div", { class: "field" }, h("label", { for: "d-note" }, "Note for the record (optional)"), h("input", { id: "d-note", type: "text", maxlength: "500" })),
    h("button", { class: "btn", type: "button", disabled: !mayWaive, onclick: () => act(async () => {
      await api(path(`/assertions/${row.hash}/disposition`), { method: "PUT", body: { disposition: val("d-kind"), note: val("d-note") } });
      S.openLine = null; await refresh(); }, "Marked stet. Run checks to update the verdict.") }, "Let it stand"),
    mayWaive ? null : h("p", { class: "note" }, !can(waiverRole) ? `Only the ${waiverRole} role can let a sentence stand.` : "This needs a company sign-in, not an access key."));
  return h("div", { class: "resolve" }, h("div", { class: "split" }, left, right));
}

function proof() {
  const { item, ledger } = S.detail;
  if (S.editing) {
    return h("div", { class: "proofwrap" }, h("form", { class: "proof", onsubmit: (e) => { e.preventDefault(); act(async () => {
        await api(path(), { method: "PATCH", body: { title: val("e-title"), summary: document.getElementById("e-summary").value, body: document.getElementById("e-body").value } });
        S.editing = false; await refresh(); }, "Copy saved as a new version. Earlier approval no longer applies."); } },
      h("div", { class: "editor" }, ...notices(),
        h("div", { class: "field" }, h("label", { for: "e-title" }, "Headline"), h("input", { id: "e-title", type: "text", value: item.title, required: true })),
        h("div", { class: "field" }, h("label", { for: "e-summary" }, "Summary"), h("textarea", { id: "e-summary", rows: "2" }, item.summary)),
        h("div", { class: "field" }, h("label", { for: "e-body" }, "Copy"), h("textarea", { id: "e-body", rows: "14", required: true }, item.body)),
        h("div", { class: "row" }, h("button", { class: "btn primary", type: "submit" }, "Save copy"),
          h("button", { class: "btn", type: "button", onclick: () => { S.editing = false; render(); } }, "Cancel")))));
  }
  const lines = ledger.map((row) => {
    const mark = row.status === "covered" ? `\u00A7${row.claim_index + 1}` : row.status === "waived" ? "stet" : row.status === "open" ? "unsourced" : "";
    const interactive = row.status === "open" || row.status === "waived";
    const label = { covered: "supported by evidence", waived: `let stand by ${row.by}`, open: "has no evidence yet", exempt: "needs no evidence" }[row.status];
    const txt = interactive
      ? h("button", { class: "txt", type: "button", "aria-expanded": String(S.openLine === row.hash), "aria-label": `${row.text} (${label})`,
          onclick: () => { S.openLine = S.openLine === row.hash ? null : row.hash; S.err = ""; S.ok = ""; render(); } }, row.text)
      : h("span", { class: "txt", title: label }, row.text);
    const kids = [h("span", { class: "mark", "aria-hidden": "true" }, mark), txt];
    if (S.openLine === row.hash && row.status === "open") kids.push(resolvePanel(row, item));
    if (S.openLine === row.hash && row.status === "waived") kids.push(h("div", { class: "resolve" },
      h("p", {}, `Let stand by ${row.by} on ${when(row.at)} as ${String(row.disposition).replace("_", " ")}.`),
      h("button", { class: "btn danger", type: "button", disabled: !(can(S.cfg.waiver_role || "approver") && humanOk()), onclick: () => act(async () => {
        await api(path(`/assertions/${row.hash}/disposition`), { method: "DELETE" }); S.openLine = null; await refresh(); }, "Stet removed.") }, "Remove stet")));
    return h("div", { class: `line ${row.field} ${row.status}`, "data-hash": row.hash }, ...kids);
  });
  return h("div", { class: "proofwrap" }, h("article", { class: "proof" },
    h("header", {}, ...notices(), h("div", { class: "meta" },
      h("span", { class: `state ${item.state}` }, STATE_WORD[item.state] || item.state), h("span", {}, item.classification),
      h("span", {}, "version ", h("code", {}, item.content_hash.slice(0, 10))), h("span", {}, `by ${item.created_by || "unknown"}`),
      h("span", { class: "tools" }, can("editor") ? h("button", { class: "btn quiet", type: "button", onclick: () => { S.editing = true; S.err = ""; S.ok = ""; render(); } }, "Edit copy") : null))),
    ...lines, draftingNotes(item)));
}

function sheet() {
  const { item, gate, deliveries } = S.detail;
  const approval = item.approval || {};
  const current = gate.checks.human_approved;
  const verdict = h("section", {}, h("p", { class: `verdict ${gate.passed ? "pass" : "block"}` }, gate.passed ? "Clear to release" : "Blocked"),
    gate.blockers.length || gate.warnings.length ? h("ul", {}, ...gate.blockers.map((b) => h("li", {}, b)), ...gate.warnings.map((w) => h("li", { class: "warn" }, w))) : null,
    h("div", { class: "row", style: null }, h("button", { class: "btn", type: "button", disabled: !can("editor"),
      onclick: () => act(async () => { await api(path("/pipeline"), { method: "POST" }); await refresh(); }, "Checks finished.") }, "Run checks")));

  const evidence = h("section", {}, h("h2", {}, `Evidence (${item.claims.length})`),
    item.claims.length ? h("ul", { class: "claims" }, ...item.claims.map((c, i) => {
      const uris = (c.sources || []).map((s) => s.uri);
      return h("li", {}, h("span", { class: "ref" }, `\u00A7${i + 1}`), h("span", {}, c.text,
        h("span", { class: uris.length || c.claim_type === "forecast" || c.claim_type === "opinion" ? "src" : "src unsourced" },
          uris.length ? uris.join(", ") : c.claim_type === "fact" || c.claim_type === "quote" ? "no source" : c.claim_type)));
    })) : h("p", { class: "note" }, "No evidence attached. Select an unsourced sentence to add some."));

  const needsApproval = HIGH_RISK.has(item.classification);
  const mayApprove = can("approver") && humanOk();
  const approvalBox = h("section", {}, h("h2", {}, "Approval"),
    approval.approved_by ? h("p", {}, `${current ? "Approved" : "Approved an earlier version"} by ${approval.approved_by}, ${when(approval.approved_at)}.`)
      : h("p", { class: "note" }, needsApproval ? `${item.classification} releases need a named approver.` : "Not required for this kind of release."),
    approval.approved_by && current
      ? h("button", { class: "btn danger", type: "button", disabled: !mayApprove, onclick: () => act(async () => {
          await api(path("/revoke"), { method: "POST", body: { note: "withdrawn in console" } }); await refresh(); }, "Approval withdrawn.") }, "Withdraw approval")
      : h("div", {}, h("div", { class: "field" }, h("label", { for: "a-note" }, "Note for the record (optional)"), h("input", { id: "a-note", type: "text", maxlength: "2000" })),
          h("button", { class: needsApproval ? "btn primary" : "btn", type: "button", disabled: !mayApprove, onclick: () => act(async () => {
            const r = await api(path("/approve"), { method: "POST", body: { note: val("a-note") } }); await refresh();
            if (r.state !== "approved" && r.state !== "published") throw new Error("Approval recorded, but the release is still blocked: " + r.gate.blockers.join("; "));
          }, "Approved this version.") }, "Approve this version")),
    mayApprove ? null : h("p", { class: "note" }, !can("approver") ? "Approving needs the approver role." : "Approving needs a company sign-in, not an access key."));

  const latest = (epId) => deliveries.find((d) => d.endpoint_id === epId && d.content_hash === gate.checks.content_hash);
  const accepts = (ep) => (ep.config.classifications || (ep.config.classification ? [ep.config.classification] : ["general", "pr", "social"])).includes(item.classification);
  const pushes = S.feeds.filter((f) => PUSH.has(f.protocol) && f.enabled && f.direction !== "inbound");
  const send = h("section", {}, h("h2", {}, "Send to"),
    pushes.length ? h("div", {}, ...pushes.map((ep) => {
      const d = latest(ep.id);
      return h("div", { class: "dest" }, h("span", {}, ep.name, h("span", { class: "k" }, accepts(ep) ? ep.protocol : `${ep.protocol}, does not take ${item.classification} releases`)),
        d && d.status === "sent" ? h("span", { class: "sent" }, ep.protocol === "vaak" ? "Rendered" : "Sent")
          : h("button", { class: "btn", type: "button", disabled: !(can("publisher") && gate.passed && accepts(ep)), "data-send": ep.slug,
              onclick: () => act(async () => { await api(path("/publish"), { method: "POST", body: { endpoint_id: ep.id } }); await refresh(); },
                ep.protocol === "vaak" ? `Audio rendered by ${ep.name}.` : `Sent to ${ep.name}.`) },
              ep.protocol === "vaak" ? (d && d.status === "failed" ? "Render again" : "Render audio") : d && d.status === "failed" ? "Send again" : "Send"));
    })) : h("p", { class: "note" }, "No destinations are set up. An admin adds them under Destinations."),
    !gate.passed ? h("p", { class: "note" }, "Sending opens once the release is clear.") : !can("publisher") ? h("p", { class: "note" }, "Sending needs the publisher role.") : null);

  const history = deliveries.length ? h("section", {}, h("h2", {}, "Delivery record"), h("ul", {}, ...deliveries.map((d) => {
    const ep = S.feeds.find((f) => f.id === d.endpoint_id);
    return h("li", {}, h("span", { class: d.status === "sent" ? "sent" : "failed" }, d.status === "sent" ? "Sent" : d.status === "failed" ? "Failed" : "In progress"),
      ` to ${ep ? ep.name : "a removed destination"}, ${when(d.updated_at)}`, d.provider_id ? `, reference ${d.provider_id}` : "", d.error ? `. ${d.error}` : "");
  }))) : null;
  const v = (item.metadata || {}).vaak;
  const audioPath = (() => { try { return new URL(item.metadata.audio_url).pathname; } catch { return null; } })();
  const voice = v && v.rendered_hash === item.content_hash && audioPath && audioPath.startsWith("/media/") ? h("section", {}, h("h2", {}, "Voice"),
    h("audio", { controls: true, preload: "none", src: audioPath }),
    h("p", { class: "note" }, `Rendered by Vaak as ${v.twin_id}. Manifest ${String(v.manifest_hash).slice(0, 16)}${v.anchored_root ? ", anchored" : ", not anchored"}.`)) : null;
  const shortVideo = can("editor") ? h("button", {class:"btn", type:"button", onclick:()=>act(async()=>{
    const headers = S.key ? {"X-API-Key":S.key} : {"X-CSRF-Token":S.me?.csrf || ""};
    const response = await fetch(`/v1/content/${encodeURIComponent(item.id)}/video`, {method:"POST", headers, credentials:"same-origin"});
    if(!response.ok) { const error=await response.json(); throw new Error(error.detail || "Video creation failed"); }
    const url=URL.createObjectURL(await response.blob()); const a=document.createElement("a");
    a.href=url; a.download="growthos-15s.mp4"; a.click(); setTimeout(()=>URL.revokeObjectURL(url),60000);
  },"15-second video downloaded. Review it before upload.")}, "Create 15-second video") : null;
  return h("aside", { class: "sheet", "aria-label": "Release status" }, shortVideo, verdict, evidence, approvalBox, send, voice, history);
}

function viewReleases() {
  const main = S.creating ? newRelease() : S.detail ? proof()
    : h("div", { class: "proofwrap" }, ...notices(), h("p", { class: "empty" }, S.items.length ? "Choose a release from the list to check its evidence." : "No releases yet. Start one with New release."));
  return h("div", { class: "desk" }, queue(), main, S.detail && !S.creating ? sheet() : h("aside", { class: "sheet" }));
}

// ---------------------------------------------------------------- destinations
function connectorForm() {
  if (!can("admin")) return null;
  const editing = S.editDestination;
  const selected = editing?.protocol || S.connectorType || "rss";
  const spec = (S.connectors || []).find(c => c.protocol === selected);
  if (!spec) return null;
  const config = editing?.config || spec.defaults;
  const labels = {author_urn:"Author URN", bearer_token_env:"Access token variable", webhook_url_env:"Webhook URL variable", api_key_env:"API key variable", app_password_env:"Application password variable", bot_token_env:"Bot token variable", recipients_env:"Recipient list variable", keystring:"Public app key", twin_id:"Enrolled voice ID", to:"Recipient email", ig_user_id:"Instagram account ID"};
  const fields = spec.fields.map(f => {
    const label = labels[f.key] || f.key.replace(/_env$/, " variable").replaceAll("_", " ");
    return h("div",{class:"field"},h("label",{for:`connector-${f.key}`},label + (f.required ? " *" : "")),
      h("input",{id:`connector-${f.key}`,type:"text",value:config[f.key] ?? "",required:f.required,
        pattern:f.secret_reference?"GROWTHOS_SECRET_[A-Z0-9_]+":null,
        list:f.secret_reference?"saved-credential-names":null,
        placeholder:f.secret_reference?`GROWTHOS_SECRET_${selected.toUpperCase()}_${f.key.replace(/_env$/, "").toUpperCase()}`:""}));
  });
  const advanced = Object.fromEntries(Object.entries(config).filter(([k])=>!spec.fields.some(f=>f.key===k)));
  const form = h("form",{class:"panel studio-form",onsubmit:e=>{e.preventDefault();act(async()=>{
    let cfg;
    try { cfg=JSON.parse(val("dest-advanced") || "{}"); } catch { throw new Error("Advanced settings must be valid JSON."); }
    if (!cfg || typeof cfg!=="object" || Array.isArray(cfg)) throw new Error("Advanced settings must be a JSON object.");
    for(const f of spec.fields) { const v=val(`connector-${f.key}`); if(v) cfg[f.key]=v; else delete cfg[f.key]; }
    const body={name:val("dest-name"),url:val("dest-url"),config:cfg};
    if(editing) await api(`/v1/feeds/${encodeURIComponent(editing.id)}`,{method:"PATCH",body});
    else await api("/v1/feeds",{method:"POST",body:{...body,slug:val("dest-slug"),protocol:selected,direction:val("dest-direction"),enabled:false}});
    S.editDestination=null; await refresh();
  },editing?"Destination settings updated.":"Destination saved, switched off. Review readiness before enabling it.");}},
    h("h2",{},editing?`Edit ${editing.name}`:"Add a destination"),
    h("datalist",{id:"saved-credential-names"},...(S.credentialVault?.credentials||[]).map(c=>h("option",{value:c.name}))),
    h("div",{class:"draft-options"},
      h("div",{class:"field"},h("label",{for:"dest-type"},"Destination type"),h("select",{id:"dest-type",disabled:!!editing,onchange:e=>{S.connectorType=e.target.value;render();}},
        ...(S.connectors||[]).map(c=>h("option",{value:c.protocol,selected:c.protocol===selected},`${c.group} · ${c.name}`)))),
      h("div",{class:"field"},h("label",{for:"dest-name"},"Destination name"),h("input",{id:"dest-name",type:"text",required:true,value:editing?.name||""})),
      h("div",{class:"field"},h("label",{for:"dest-slug"},"Short identifier"),h("input",{id:"dest-slug",type:"text",required:true,disabled:!!editing,pattern:"[a-z0-9][a-z0-9_\\-]*",value:editing?.slug||""}))),
    h("div",{class:"field"},h("label",{for:"dest-direction"},"Direction"),h("select",{id:"dest-direction",disabled:!!editing},
      ...spec.directions.map(d=>h("option",{value:d,selected:d===(editing?.direction||"outbound")},d)))),
    h("p",{class:"note"},spec.note),
    h("div",{class:"field"},h("label",{for:"dest-url"},"Service or feed URL"),h("input",{id:"dest-url",type:"url",required:spec.url_required,value:editing?.url||"",placeholder:"https://…"})),
    h("div",{class:"draft-options"},...fields),
    h("details",{},h("summary",{},"Advanced settings"),h("p",{class:"note"},"Additional provider options and destination policy. Use variable names for credentials, never secret values."),
      h("div",{class:"field"},h("label",{for:"dest-advanced"},"Provider settings (JSON)"),h("textarea",{id:"dest-advanced",rows:"6",spellcheck:"false"},JSON.stringify(advanced,null,2)))),
    h("p",{class:"note"},"Save credentials in Account credentials above, or use server-managed credential names. Saving never sends a message. Configuration checks do not verify live account permissions or token expiry."),
    h("div",{class:"row"},h("button",{type:"submit",class:"btn primary"},"Save destination"),editing?h("button",{type:"button",class:"btn",onclick:()=>{S.editDestination=null;render();}},"Cancel editing"):null));
  return form;
}

function credentialForm() {
  if(!can("admin")) return null;
  const vault=S.credentialVault;
  return h("section",{class:"panel"},h("h2",{},"Account credentials"),
    h("p",{},"Save this company's account token, then select its credential name in the destination settings. Saved values cannot be read back."),
    !vault?.storage_configured?h("p",{class:"note"},"Secure credential storage needs to be enabled by your workspace operator."):h("form",{onsubmit:e=>{
      e.preventDefault();const name=val("credential-name");const input=document.getElementById("credential-value");const value=input.value;input.value="";
      act(async()=>{await api("/v1/connector-credentials",{method:"PUT",body:{name,value}});await refresh();},"Credential saved securely. It is available to this workspace's connectors.");
    }},h("div",{class:"field"},h("label",{for:"credential-name"},"Credential name"),h("input",{id:"credential-name",type:"text",required:true,pattern:"GROWTHOS_SECRET_[A-Z0-9_]+",placeholder:"GROWTHOS_SECRET_COMPANY_TIKTOK"})),
       h("div",{class:"field"},h("label",{for:"credential-value"},"Account token or secret"),h("input",{id:"credential-value",type:"password",required:true,autocomplete:"new-password",maxlength:"20000"})),
       h("button",{class:"btn",type:"submit"},"Save credential")),
    h("ul",{},...(vault?.credentials||[]).map(c=>h("li",{},c.name," ",h("button",{class:"btn",type:"button",onclick:()=>act(async()=>{
      await api(`/v1/connector-credentials/${encodeURIComponent(c.name)}`,{method:"DELETE"});await refresh();
    },"Credential removed. Destinations that need it cannot send until reconnected.")},"Disconnect")))));
}

function viewDestinations() {
  const readiness = S.connectorReadiness?.endpoints || [];
  const rows = S.feeds.map(f => {
    const r=readiness.find(x=>x.endpoint_id===f.id);
    return h("tr",{},h("td",{},f.name,h("div",{class:"note"},f.slug)),h("td",{},(S.connectors||[]).find(c=>c.protocol===f.protocol)?.name||f.protocol),
      h("td",{},f.direction),h("td",{},f.enabled?"On":"Off",
        r?h("div",{class:"note"},r.configuration_ready?"Settings ready · live verification pending":r.problems.join(" ")):null,
        f.last_status?h("div",{class:"note"},`Last sync: ${f.last_status}`):null),
      h("td",{},safeHref(f.public_url)?h("a",{href:safeHref(f.public_url),target:"_blank",rel:"noopener noreferrer"},"Public feed"):null),
      h("td",{},h("div",{class:"row"},
        h("button",{class:"btn",type:"button",disabled:!can("admin"),onclick:()=>{S.editDestination=f;render();document.getElementById("dest-name")?.focus();}},"Edit settings"),
        h("button",{class:"btn",type:"button",disabled:!can("admin")||(!f.enabled&&r&&!r.configuration_ready),onclick:()=>act(async()=>{
          await api(`/v1/feeds/${encodeURIComponent(f.id)}`,{method:"PATCH",body:{enabled:!f.enabled}});await refresh();
        },`${f.name} turned ${f.enabled?"off":"on"}.`)},f.enabled?"Turn off":"Turn on"),
        f.direction!=="outbound"?h("button",{class:"btn",type:"button",disabled:!can("admin"),onclick:()=>act(async()=>{
          await api(`/v1/feeds/${encodeURIComponent(f.id)}/sync`,{method:"POST"});await refresh();
        },"Feed sync finished.")},"Sync now"):null)));
  });
  return h("div",{class:"page"},h("h1",{},"Destinations"),
    h("p",{},`${(S.connectors||[]).length} feed and connector types available. Configure accounts, review missing credentials, and control where approved releases go.`),...notices(),
    can("admin")?h("button",{class:"btn",type:"button",onclick:()=>act(refresh,"Configuration readiness refreshed. No messages were sent.")},"Check configuration"):null,
    S.connectorReadiness?h("div",{class:"metrics"},...S.connectorReadiness.services.map(s=>metric(s.name,s.configured?"Configured":"Needs setup","Live acceptance still required"))):null,
    rows.length?h("div",{class:"tablewrap"},h("table",{},h("thead",{},h("tr",{},...["Name","Connector","Direction","Readiness","Feed","Actions"].map(t=>h("th",{},t)))),h("tbody",{},...rows))):h("p",{class:"empty"},"No destinations yet. Choose a connector below."),
    credentialForm(), connectorForm());
}

// ---------------------------------------------------------------- intelligence
async function loadIntelligence() {
  const [perf, aeo, inbox, schedules, opportunities, media, chrysalis] = await Promise.all([
    api("/v1/performance?days=30"), api("/v1/aeo/visibility?brand=Parinita&days=30"),
    api("/v1/engagement/inbox?limit=20"), api("/v1/schedules?limit=20"),
    api("/v1/opportunities?status=new&limit=20"), api("/v1/media/coverage?days=30&limit=20"),
    api("/v1/chrysalis/status")]);
  S.intelligence = { perf, aeo, inbox, schedules, opportunities, media, chrysalis };
}
function viewIntelligence() {
  const x = S.intelligence || { perf: {totals:{},derived:{},by_channel:{}}, aeo:{}, inbox:[], schedules:[] };
  const metricRows = Object.entries(x.perf.totals || {}).map(([k,v]) => h("tr", {}, h("td", {}, k), h("td", {class:"num"}, v)));
  const channelRows = Object.entries(x.perf.by_channel || {}).map(([k,v]) => h("tr", {}, h("td", {}, k), h("td", {class:"num"}, v.ctr || 0), h("td", {class:"num"}, v.engagement_rate || 0), h("td", {class:"num"}, v.conversion_rate || 0)));
  const citeRows = (x.aeo.top_citation_domains || []).slice(0,10).map((r) => h("tr", {}, h("td", {}, r.domain), h("td", {class:"num"}, r.citations)));
  const inboxRows = (x.inbox || []).map((r) => h("tr", {}, h("td", {}, r.provider), h("td", {}, r.priority), h("td", {}, r.intent), h("td", {}, r.body.slice(0,120)), h("td", {}, r.state)));
  const schedRows = (x.schedules || []).map((r) => h("tr", {}, h("td", {}, when(r.run_at)), h("td", {}, r.status), h("td", {}, r.content_id), h("td", {}, r.endpoint_id)));
  const oppRows = (x.opportunities || []).map((r) => h("tr", {}, h("td", {class:"num"}, r.score), h("td", {}, r.kind), h("td", {}, r.title), h("td", {}, r.recommendation?.action || "review")));
  const coverageRows = (x.media?.items || []).slice(0,10).map((r) => h("tr", {}, h("td", {}, r.outlet || "—"), h("td", {}, r.author || "—"), h("td", {}, r.title), h("td", {}, r.sentiment)));
  const chr = x.chrysalis || {};
  return h("div", {class:"page"}, h("h1", {}, "Intelligence"),
    h("p", {}, "Outcome telemetry, answer-engine visibility, engagement inbox and scheduled distribution. These views report observed data; they do not infer causation."), ...notices(),
    h("section", {}, h("h2", {}, "Performance · 30 days"), h("p", {}, `CTR ${x.perf.derived?.click_through_rate || 0} · engagement ${x.perf.derived?.engagement_rate || 0} · conversion ${x.perf.derived?.conversion_rate || 0}`),
      metricRows.length ? h("div", {class:"tablewrap"}, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Metric"), h("th", {}, "Total"))), h("tbody", {}, ...metricRows))) : h("p", {class:"note"}, "No performance events yet."),
      channelRows.length ? h("div", {class:"tablewrap"}, h("table", {}, h("thead", {}, h("tr", {}, ...["Channel","CTR","Engagement","Conversion"].map((t)=>h("th",{},t)))), h("tbody", {}, ...channelRows))) : null),
    h("section", {}, h("h2", {}, "AEO / GEO visibility"), h("p", {}, `${x.aeo.mentions || 0} mentions in ${x.aeo.probes || 0} observed answer-engine responses · visibility ${(x.aeo.visibility_rate || 0)}`),
      citeRows.length ? h("div", {class:"tablewrap"}, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Cited domain"), h("th", {}, "Citations"))), h("tbody", {}, ...citeRows))) : h("p", {class:"note"}, "No AEO probes yet.")),
    h("section", {}, h("h2", {}, "Engagement inbox"), inboxRows.length ? h("div", {class:"tablewrap"}, h("table", {}, h("thead", {}, h("tr", {}, ...["Provider","Priority","Intent","Message","State"].map((t)=>h("th",{},t)))), h("tbody", {}, ...inboxRows))) : h("p", {class:"note"}, "No inbound messages yet.")),
    h("section", {}, h("h2", {}, "Opportunity Queue"), h("p", {class:"note"}, "Signal combines earned media, AEO, inbox pressure and observed performance into ranked next actions. Nothing here is an approval to publish."),
      oppRows.length ? h("div", {class:"tablewrap"}, h("table", {}, h("thead", {}, h("tr", {}, ...["Score","Lane","Opportunity","Next action"].map((t)=>h("th",{},t)))), h("tbody", {}, ...oppRows))) : h("p", {class:"note"}, "No open opportunities from the available observations."),
      h("button",{class:"btn",type:"button",disabled:!can("editor"),onclick:()=>act(async()=>{await api('/v1/opportunities/refresh',{method:'POST'});await loadIntelligence();},"Opportunities recalculated from available observations.")},"Refresh opportunities")),
    h("section", {}, h("h2", {}, "Earned media"), coverageRows.length ? h("div", {class:"tablewrap"}, h("table", {}, h("thead", {}, h("tr", {}, ...["Outlet","Author","Coverage","Sentiment"].map((t)=>h("th",{},t)))), h("tbody", {}, ...coverageRows))) : h("p", {class:"note"}, "No licensed/provider coverage observations yet.")),
    h("section", {}, h("h2", {}, "Chrysalis trust anchor"),
      h("p", {}, chr.enabled ? `Enabled · ${chr.latest?.status || "no receipt yet"}` : "Not enabled in this environment"),
      chr.latest?.chrysalis_ref ? h("code", {}, `receipt ${chr.latest.chrysalis_ref}`) : null,
      h("p", {class:"note"}, chr.architecture || "GrowthOS local audit chain → Chrysalis external assurance anchor")),
    h("section", {}, h("h2", {}, "Scheduled distribution"), schedRows.length ? h("div", {class:"tablewrap"}, h("table", {}, h("thead", {}, h("tr", {}, ...["When","State","Release","Destination"].map((t)=>h("th",{},t)))), h("tbody", {}, ...schedRows))) : h("p", {class:"note"}, "No scheduled sends.")),
    h("button", {class:"btn", type:"button", onclick:()=>act(loadIntelligence,"Intelligence refreshed.")}, "Refresh"));
}

// ---------------------------------------------------------------- audit
async function loadAudit() { S.audit = null; S.chain = null; if (can("auditor")) { S.audit = await api("/v1/audit?limit=100"); S.chain = await api("/v1/audit/verify"); } }
function viewAudit() {
  if (!can("auditor")) return h("div", { class: "page" }, h("h1", {}, "Audit"), h("p", {}, "The audit trail needs the auditor role."));
  const c = S.chain;
  return h("div", { class: "page" }, h("h1", {}, "Audit"),
    h("p", {}, "Every change, check, approval and send, in order. Each record carries the hash of the one before it, so a removed or altered record breaks the chain."), ...notices(),
    c ? h("div", { class: "chain" }, h("p", { class: `verdict ${c.ok ? "pass" : "block"}` }, c.ok ? "Chain intact" : `Chain broken at record ${c.break_at_seq}`),
      h("span", {}, `${c.events} records`), c.ok ? h("code", {}, `head ${c.head_hash}`) : h("span", {}, c.reason),
      h("button", { class: "btn", type: "button", onclick: () => act(loadAudit, "Chain checked again.") }, "Check again")) : null,
    h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", { class: "num" }, "No."), ...["When", "Who", "What", "Outcome", "Release"].map((t) => h("th", {}, t)))),
      h("tbody", {}, ...(S.audit || []).map((e) => h("tr", {}, h("td", { class: "num" }, e.seq), h("td", {}, when(e.ts)), h("td", {}, e.actor), h("td", {}, e.action), h("td", {}, e.decision),
        h("td", {}, e.content_id ? h("button", { class: "btn quiet", type: "button", onclick: () => act(async () => { S.view = "releases"; await refresh(); await loadDetail(e.content_id);
          const st = S.detail.item.state; S.tab = (TABS.find(([, , states]) => states.includes(st)) || TABS[0])[0]; }) }, "Open") : "")))))));
}

// ---------------------------------------------------------------- render + boot
// A repaint can be triggered by an action that finishes while someone is typing in another form (for example
// "Run checks" completing while a source is being entered). If the same form is still on screen afterwards,
// what was typed is put back.
let lastContext = "";
function render() {
  const context = [S.me ? S.me.principal : "", S.view, S.sel, S.openLine, S.editing, S.creating, S.connectorType, S.editDestination?.id].join("|");
  const typed = {};
  if (context === lastContext) root.querySelectorAll("input[id], textarea[id], select[id]").forEach((el) => { if (el.type !== "password") typed[el.id] = el.value; });
  const focused = document.activeElement && document.activeElement.id;
  lastContext = context;
  root.replaceChildren();
  if (!S.me) { root.append(viewSignIn()); return; }
  const content = ["create", "podcast"].includes(S.view) ? viewCreation() : S.view === "setup" ? viewSetup() : S.view === "brand" ? viewBrand() : S.view === "overview" ? viewOverview() : S.view === "agents" ? viewAgents() : S.view === "releases" ? viewReleases() : S.view === "destinations" ? viewDestinations() : S.view === "intelligence" ? viewIntelligence() : viewAudit();
  root.append(bar(), h("main", { class: "workspace-main" }, topstrip(), content));
  for (const [id, value] of Object.entries(typed)) { const el = document.getElementById(id); if (el) el.value = value; }
  if (focused && typed[focused] !== undefined) document.getElementById(focused)?.focus();
}

(async function boot() {
  try {
    S.cfg = await api("/auth/config");   // also says who is signed in, so an anonymous visit provokes no 401
    S.me = S.cfg.me;
    if (S.me) await refresh();
    else if (S.key) { S.key = ""; sessionStorage.removeItem("growthos.key"); }
  } catch (e) { root.replaceChildren(h("p", { class: "boot" }, `Growth Command could not reach the server: ${e.message}`)); return; }
  render();
})();
