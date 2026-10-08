// Growth Command: operator console for Parinita GrowthOS.
// No framework, no build step, no third-party origin. Every piece of content is written with textContent
// (never innerHTML): release copy and ingested feed items are untrusted input.

const PUSH = new Set(["webhook", "rest_json", "smtp", "linkedin", "x", "mastodon", "bluesky", "transistor", "buzzsprout", "pr_wire",
                      "slack", "teams", "discord", "telegram", "whatsapp", "wordpress", "mcp", "vaak",
  "reddit", "facebook", "instagram", "threads", "pinterest", "tiktok", "tumblr", "lemmy", "etsy", "shopify", "google_business", "devto", "ghost", "buttondown", "mailchimp", "google_chat", "mattermost", "matrix", "zulip"]);
const HIGH_RISK = new Set(["investor", "regulated", "legal", "health", "financial"]);
const TABS = [["work", "Needs work", ["draft", "blocked"]], ["ready", "Ready", ["approved"]], ["sent", "Sent", ["published"]]];
const STATE_WORD = { draft: "Draft", blocked: "Blocked", approved: "Ready", published: "Sent" };

const S = { cfg: null, key: sessionStorage.getItem("growthos.key") || "", me: null, view: "releases", tab: "work", items: [], sel: null,
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
  return box;
}

// ---------------------------------------------------------------- frame
function bar() {
  const go = (v) => () => act(async () => { S.view = v; if (v === "audit") await loadAudit(); else if (v === "intelligence") await loadIntelligence(); else await refresh(); });
  const nav = h("nav", { "aria-label": "Sections" },
    ...[["releases", "Releases"], ["destinations", "Destinations"], ["intelligence", "Intelligence"], ["audit", "Audit"]].map(([v, label]) =>
      h("button", { type: "button", "aria-current": S.view === v ? "page" : null, onclick: go(v) }, label)));
  return h("header", { class: "bar" }, h("span", { class: "mark" }, "Growth Command"), nav,
    h("div", { class: "who" }, h("strong", { title: S.me.principal }, S.me.principal), h("span", {}, S.me.roles.join(", ") || "no role assigned"),
      h("button", { type: "button", onclick: () => act(async () => {
        if (!S.key) await api("/auth/logout", { method: "POST" });
        S.key = ""; sessionStorage.removeItem("growthos.key"); S.me = null; S.detail = null; S.sel = null; }) }, "Sign out")));
}
const notices = () => [S.err ? h("p", { class: "error", role: "alert" }, S.err) : null, S.ok ? h("p", { class: "done", role: "status" }, S.ok) : null];

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
    ...lines));
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
  return h("aside", { class: "sheet", "aria-label": "Release status" }, verdict, evidence, approvalBox, send, voice, history);
}

function viewReleases() {
  const main = S.creating ? newRelease() : S.detail ? proof()
    : h("div", { class: "proofwrap" }, ...notices(), h("p", { class: "empty" }, S.items.length ? "Choose a release from the list to check its evidence." : "No releases yet. Start one with New release."));
  return h("div", { class: "desk" }, queue(), main, S.detail && !S.creating ? sheet() : h("aside", { class: "sheet" }));
}

// ---------------------------------------------------------------- destinations
function viewDestinations() {
  const rows = S.feeds.map((f) => h("tr", {}, h("td", {}, f.name, h("div", { class: "note" }, f.slug)), h("td", {}, f.protocol), h("td", {}, f.direction),
    h("td", {}, f.enabled ? "On" : "Off", f.last_status ? h("div", { class: f.last_status === "ok" ? "sent" : "failed" }, f.last_status === "ok" ? `Last sync worked, ${when(f.last_sync_at)}` : `Last sync failed: ${f.last_error}`) : null),
    h("td", {}, safeHref(f.public_url) ? h("a", { href: safeHref(f.public_url), target: "_blank", rel: "noopener noreferrer" }, "Public feed") : ""),
    h("td", {}, h("div", { class: "row" },
      h("button", { class: "btn", type: "button", disabled: !can("admin"), onclick: () => act(async () => {
        await api(`/v1/feeds/${encodeURIComponent(f.id)}`, { method: "PATCH", body: { enabled: !f.enabled } }); await refresh(); }, `${f.name} turned ${f.enabled ? "off" : "on"}.`) }, f.enabled ? "Turn off" : "Turn on"),
      f.direction !== "outbound" ? h("button", { class: "btn", type: "button", disabled: !can("admin"), onclick: () => act(async () => {
        const r = await api(`/v1/feeds/${encodeURIComponent(f.id)}/sync`, { method: "POST" }); await refresh(); S.ok = `${r.count} new item${r.count === 1 ? "" : "s"} from ${f.name}.`; }) }, "Sync now") : null))));
  return h("div", { class: "page" }, h("h1", {}, "Destinations"),
    h("p", {}, "Where releases come from and go to. Turning a destination off stops both its public feed and anything sent to it."), ...notices(),
    S.feeds.length ? h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, ...["Name", "Type", "Direction", "Status", "", ""].map((t) => h("th", {}, t)))), h("tbody", {}, ...rows)))
      : h("p", { class: "empty" }, "No destinations yet. An admin creates them with POST /v1/feeds; see the README for each type's settings."));
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
      oppRows.length ? h("div", {class:"tablewrap"}, h("table", {}, h("thead", {}, h("tr", {}, ...["Score","Lane","Opportunity","Next action"].map((t)=>h("th",{},t)))), h("tbody", {}, ...oppRows))) : h("p", {class:"note"}, "No open opportunities. Run POST /v1/opportunities/refresh to recalculate.")),
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
  const context = [S.me ? S.me.principal : "", S.view, S.sel, S.openLine, S.editing, S.creating].join("|");
  const typed = {};
  if (context === lastContext) root.querySelectorAll("input[id], textarea[id], select[id]").forEach((el) => { if (el.type !== "password") typed[el.id] = el.value; });
  const focused = document.activeElement && document.activeElement.id;
  lastContext = context;
  root.replaceChildren();
  if (!S.me) { root.append(viewSignIn()); return; }
  root.append(bar(), S.view === "releases" ? viewReleases() : S.view === "destinations" ? viewDestinations() : S.view === "intelligence" ? viewIntelligence() : viewAudit());
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
