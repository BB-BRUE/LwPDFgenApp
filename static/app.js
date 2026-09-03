const form = document.querySelector("#upload-form");
const input = document.querySelector("#file-input");
const choose = document.querySelector("#choose-file");
const progress = document.querySelector("#upload-progress");
const progressFilename = document.querySelector("#progress-filename");
const list = document.querySelector("#document-list");
const empty = document.querySelector("#empty-state");
const refresh = document.querySelector("#refresh");
const toast = document.querySelector("#toast");
const dialog = document.querySelector("#delete-dialog");
const deleteName = document.querySelector("#delete-name");
const confirmDelete = document.querySelector("#confirm-delete");
const API_ROOT = "/app/api";
let pendingDelete = null;
let toastTimer = null;

const icons = {
  qr: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM15 14h2v2h-2zM19 14h1v3h-3M14 19h3v1h-3z"/></svg>',
  open: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 4h6v6M20 4l-9 9M18 13v5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h5"/></svg>',
  trash: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3m3 0-1 13H7L6 7m4 4v5m4-5v5"/></svg>'
};

function showToast(message, error = false) {
  clearTimeout(toastTimer);
  toast.textContent = message;
  toast.classList.toggle("error", error);
  toast.hidden = false;
  toastTimer = setTimeout(() => { toast.hidden = true; }, 4200);
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatDate(value) {
  return new Intl.DateTimeFormat("de-AT", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function documentRow(document) {
  const row = window.document.createElement("article");
  row.className = "document";
  const badge = window.document.createElement("div");
  badge.className = "file-badge";
  badge.textContent = "PDF";

  const info = window.document.createElement("div");
  info.className = "file-info";
  const title = window.document.createElement("a");
  title.href = document.url;
  title.target = "_blank";
  title.rel = "noopener";
  title.textContent = document.name;
  const meta = window.document.createElement("span");
  meta.textContent = `${formatSize(document.size)} · ${formatDate(document.created_at)}`;
  info.append(title, meta);

  const actions = window.document.createElement("div");
  actions.className = "actions";
  const qr = window.document.createElement("a");
  qr.className = "action";
  qr.href = `${API_ROOT}/documents/${encodeURIComponent(document.name)}/qr`;
  qr.innerHTML = `${icons.qr}<span>QR-Code</span>`;
  qr.setAttribute("aria-label", `QR-Code für ${document.name} herunterladen`);
  const open = window.document.createElement("a");
  open.className = "action";
  open.href = document.url;
  open.target = "_blank";
  open.rel = "noopener";
  open.innerHTML = `${icons.open}<span>Öffnen</span>`;
  open.setAttribute("aria-label", `${document.name} öffnen`);
  const remove = window.document.createElement("button");
  remove.className = "action delete";
  remove.type = "button";
  remove.innerHTML = `${icons.trash}<span>Löschen</span>`;
  remove.setAttribute("aria-label", `${document.name} löschen`);
  remove.addEventListener("click", () => askDelete(document.name));
  actions.append(qr, open, remove);
  row.append(badge, info, actions);
  return row;
}

async function loadDocuments() {
  refresh.classList.add("loading");
  try {
    const response = await fetch(`${API_ROOT}/documents`, { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error("Die PDF-Liste konnte nicht geladen werden.");
    const data = await response.json();
    list.replaceChildren(...data.documents.map(documentRow));
    empty.hidden = data.documents.length !== 0;
  } catch (error) {
    showToast(error.message, true);
  } finally {
    refresh.classList.remove("loading");
  }
}

async function upload(file) {
  if (!file || !file.name.toLowerCase().endsWith(".pdf")) {
    showToast("Bitte eine PDF-Datei auswählen.", true);
    return;
  }
  const body = new FormData();
  body.append("file", file);
  progressFilename.textContent = file.name;
  progress.hidden = false;
  try {
    const response = await fetch(`${API_ROOT}/documents`, { method: "POST", headers: { "X-LwPDFgen": "web" }, body });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || "Die PDF konnte nicht verarbeitet werden.");
    showToast(`${data.document.name} wurde erstellt.`);
    form.reset();
    await loadDocuments();
  } catch (error) {
    showToast(error.message, true);
  } finally {
    progress.hidden = true;
    input.value = "";
  }
}

function askDelete(name) {
  pendingDelete = name;
  deleteName.textContent = name;
  dialog.showModal();
}

confirmDelete.addEventListener("click", async (event) => {
  event.preventDefault();
  if (!pendingDelete) return;
  confirmDelete.disabled = true;
  try {
    const response = await fetch(`${API_ROOT}/documents/${encodeURIComponent(pendingDelete)}`, {
      method: "DELETE",
      headers: { "X-LwPDFgen": "web" }
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || "Die PDF konnte nicht gelöscht werden.");
    dialog.close();
    showToast(`${data.deleted} wurde gelöscht.`);
    await loadDocuments();
  } catch (error) {
    showToast(error.message, true);
  } finally {
    confirmDelete.disabled = false;
    pendingDelete = null;
  }
});

choose.addEventListener("click", () => input.click());
input.addEventListener("change", () => upload(input.files[0]));
form.addEventListener("submit", (event) => event.preventDefault());
["dragenter", "dragover"].forEach((name) => form.addEventListener(name, (event) => {
  event.preventDefault();
  form.classList.add("dragover");
}));
["dragleave", "drop"].forEach((name) => form.addEventListener(name, (event) => {
  event.preventDefault();
  form.classList.remove("dragover");
}));
form.addEventListener("drop", (event) => upload(event.dataTransfer.files[0]));
refresh.addEventListener("click", loadDocuments);
loadDocuments();
