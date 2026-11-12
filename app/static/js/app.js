const $ = (s) => document.querySelector(s);
let conversationId = null;

async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `HTTP ${res.status}`);
  return data;
}

function el(tag, props = {}, ...children) {
  const n = Object.assign(document.createElement(tag), props);
  n.append(...children);
  return n;
}

// Tabs
const loaders = { documents: loadDocuments, approvals: loadApprovals, metrics: loadMetrics };
document.querySelectorAll("nav button").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll("nav button").forEach((x) => x.setAttribute("aria-selected", x === b));
  document.querySelectorAll("main section").forEach((s) => (s.hidden = s.id !== b.dataset.tab));
  loaders[b.dataset.tab]?.();
}));

// Chat
const labels = { pending_approval: "Sent for approval", no_evidence: "No evidence found",
                 guardrail_blocked: "Blocked by guardrail", error: "Error" };

function addMessage(role, text, data = {}) {
  const box = el("div", { className: `msg ${role}` });
  if (labels[data.status]) box.append(el("span", { className: `tag ${data.status}`, textContent: labels[data.status] }));
  box.append(text);
  if (data.sources?.length) {
    box.append(el("details", {}, el("summary", { textContent: `Sources (${data.sources.length})` }),
      el("ol", {}, ...data.sources.map((s) => el("li", {},
        el("strong", { textContent: `${s.title}, p.${s.page}` }), ` (score ${s.score})`, el("br"), s.excerpt)))));
  }
  if (data.status === "answered") {
    const send = (rating, btn) => api("/api/feedback", {
      rating, document_id: data.sources[0]?.document_id ?? null, note: data.question,
    }).then(() => { btn.parentElement.replaceWith(el("small", { textContent: "Thanks for the feedback" })); });
    const up = el("button", { textContent: "👍", ariaLabel: "Helpful" });
    const down = el("button", { textContent: "👎", ariaLabel: "Not helpful" });
    up.onclick = () => send(1, up); down.onclick = () => send(-1, down);
    box.append(el("div", { className: "fb" }, up, down));
  }
  $("#messages").append(box);
  box.scrollIntoView({ behavior: "smooth", block: "end" });
}

$("#chat-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = $("#question").value.trim();
  if (question.length < 3) return;
  const btn = e.target.querySelector("button[type=submit]"); btn.disabled = true;
  addMessage("user", question);
  $("#question").value = "";
  try {
    const data = await api("/api/chat", { question, conversation_id: conversationId });
    conversationId = data.conversation_id;
    addMessage("assistant", data.answer, { ...data, question });
  } catch (err) {
    addMessage("assistant", err.message, { status: /guardrail/i.test(err.message) ? "guardrail_blocked" : "error" });
  } finally { btn.disabled = false; $("#question").focus(); }
});
$("#question").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#chat-form").requestSubmit(); }
});
$("#new-chat").onclick = () => { conversationId = null; $("#messages").replaceChildren(); };

// Upload: presigned PUT straight to S3, then ask the API to ingest
$("#upload-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const file = $("#file").files[0];
  const status = $("#upload-status");
  const btn = e.target.querySelector("button[type=submit]"); btn.disabled = true;
  try {
    status.textContent = "Requesting upload URL…";
    const up = await api("/api/documents/uploads", { filename: file.name });
    status.textContent = "Uploading to S3…";
    const put = await fetch(up.upload_url, { method: "PUT", headers: up.headers, body: file });
    if (!put.ok) throw new Error(`S3 upload failed: HTTP ${put.status}`);
    status.textContent = "Ingesting (parse, chunk, embed)…";
    const done = await api("/api/documents/complete", { document_id: up.document_id });
    status.textContent = `Done: ${file.name} is ${done.status}.`;
    e.target.reset();
  } catch (err) {
    status.textContent = `Failed: ${err.message}`;
  } finally { btn.disabled = false; }
});

async function loadDocuments() {
  const docs = await api("/api/documents");
  $("#doc-rows").replaceChildren(...docs.map((d) => el("tr", {},
    el("td", { textContent: d.title }),
    el("td", { className: `status-${d.status}`, textContent: d.status, title: d.error ?? "" }),
    el("td", { textContent: d.chunk_count ?? "–" }),
    el("td", { textContent: new Date(d.created_at).toLocaleString() }))));
  if (!docs.length) $("#doc-rows").append(el("tr", {}, el("td", { colSpan: 4, textContent: "No documents yet." })));
}

async function loadApprovals() {
  const items = await api("/api/approvals");
  $("#approval-list").replaceChildren(...items.map((a) => {
    const li = el("li", {}, el("div", { textContent: a.question }),
      el("div", { className: "meta", textContent:
        `${a.requester} · ${new Date(a.created_at).toLocaleString()} · ${a.status}${a.reviewer ? ` by ${a.reviewer}` : ""}` }));
    if (a.status === "pending") {
      const decide = (approve) => api(`/api/approvals/${a.id}/decision`, { approve }).then(loadApprovals)
        .catch((err) => alert(err.message));
      const yes = el("button", { textContent: "Approve" }); yes.onclick = () => decide(true);
      const no = el("button", { className: "secondary", textContent: "Reject" }); no.onclick = () => decide(false);
      li.append(el("div", { className: "row" }, no, yes));
    }
    return li;
  }));
  if (!items.length) $("#approval-list").append(el("li", { textContent: "No approval requests." }));
}

async function loadMetrics() {
  const [m, g] = await Promise.all([api("/api/admin/metrics"), api("/api/admin/guardrails")]);
  const tiles = [
    ...["ready", "processing", "pending", "failed"].map((s) => [`Docs ${s}`, m.documents[s] ?? 0]),
    ["Feedback 👍", m.feedback.up ?? 0], ["Feedback 👎", m.feedback.down ?? 0],
    ["Input blocked", g.input_blocked], ["Output blocked", g.output_blocked],
  ];
  $("#metric-tiles").replaceChildren(...tiles.map(([k, v]) => el("div", { className: "tile" }, el("b", { textContent: v }), k)));
}
