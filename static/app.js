const people = [];
const expenses = [];

const personInput = document.getElementById("personInput");
const addPersonBtn = document.getElementById("addPersonBtn");
const peopleList = document.getElementById("peopleList");

const expenseName = document.getElementById("expenseName");
const expenseAmount = document.getElementById("expenseAmount");
const expensePayer = document.getElementById("expensePayer");
const splitType = document.getElementById("splitType");
const expenseBills = document.getElementById("expenseBills");
const splitPeople = document.getElementById("splitPeople");
const addExpenseBtn = document.getElementById("addExpenseBtn");
const expenseRows = document.getElementById("expenseRows");

const computeBtn = document.getElementById("computeBtn");
const downloadBtn = document.getElementById("downloadBtn");
const clearBtn = document.getElementById("clearBtn");
const summaryBox = document.getElementById("summaryBox");
const settlements = document.getElementById("settlements");
const errorBox = document.getElementById("errorBox");
let lastPayload = null;
const billUpload = document.getElementById("billUpload");
const billPreview = document.getElementById("billPreview");
const expenseHint = document.getElementById("expenseHint");
const billStatus = document.getElementById("billStatus");
let billToken = null;
const qrList = document.getElementById("qrList");
const saveNameInput = document.getElementById("saveNameInput");
const saveProgressBtn = document.getElementById("saveProgressBtn");
const savedSessions = document.getElementById("savedSessions");
const clearSessionsBtn = document.getElementById("clearSessionsBtn");
const logoutBtn = document.getElementById("logoutBtn");

function normalize(name) {
  return name.trim().toLowerCase();
}

function renderPeople() {
  peopleList.innerHTML = "";
  people.forEach((person, idx) => {
    const pill = document.createElement("div");
    pill.className = "pill";
    pill.textContent = person;

    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "×";
    remove.addEventListener("click", () => {
      people.splice(idx, 1);
      renderPeople();
      renderExpenseForm();
    });

    pill.appendChild(remove);
    peopleList.appendChild(pill);
  });
  renderQrList();
}

function renderExpenseForm() {
  expensePayer.innerHTML = "";
  people.forEach((person) => {
    const opt = document.createElement("option");
    opt.value = person;
    opt.textContent = person;
    expensePayer.appendChild(opt);
  });

  renderSplitPeople();
  renderExpenseRows();
  updateExpenseState();
}

function renderQrList() {
  if (!qrList) {
    return;
  }
  qrList.innerHTML = "";
  if (!people.length) {
    qrList.innerHTML = "<span class='muted'>Add people to upload QR codes.</span>";
    return;
  }
  people.forEach((person) => {
    const row = document.createElement("div");
    row.className = "qr-row";

    const label = document.createElement("div");
    label.textContent = person;

    const input = document.createElement("input");
    input.type = "file";
    input.accept = "image/*";
    input.addEventListener("change", () => uploadQr(person, input, row));

    const actions = document.createElement("div");
    actions.className = "qr-actions";

    const clearBtn = document.createElement("button");
    clearBtn.type = "button";
    clearBtn.className = "ghost";
    clearBtn.textContent = "Remove QR";
    clearBtn.addEventListener("click", () => clearQr(person, row, input));

    actions.appendChild(clearBtn);

    row.appendChild(label);
    row.appendChild(input);
    row.appendChild(actions);
    qrList.appendChild(row);
  });
}

async function uploadQr(person, input, row) {
  const file = input.files?.[0];
  if (!file) {
    return;
  }
  const formData = new FormData();
  formData.append("qr", file);
  formData.append("person", person);
  if (billToken) {
    formData.append("bill_token", billToken);
  }

  const res = await fetch("/api/upload-qr", {
    method: "POST",
    body: formData,
  });
  const data = await res.json().catch(() => null);
  if (!res.ok || !data?.ok) {
    errorBox.textContent = data?.errors?.join(" ") || "QR upload failed.";
    return;
  }
  billToken = data.bill_token;
  const preview = document.createElement("img");
  preview.className = "qr-preview";
  preview.alt = `${person} QR`;
  preview.src = URL.createObjectURL(file);
  preview.onload = () => URL.revokeObjectURL(preview.src);
  const existing = row.querySelector("img");
  if (existing) {
    existing.remove();
  }
  row.appendChild(preview);
  errorBox.textContent = "";
}

async function clearQr(person, row, input) {
  if (!billToken) {
    errorBox.textContent = "No QR has been uploaded yet.";
    return;
  }
  const formData = new FormData();
  formData.append("bill_token", billToken);
  formData.append("person", person);

  const res = await fetch("/api/qr/clear", {
    method: "POST",
    body: formData,
  });
  const data = await res.json().catch(() => null);
  if (!res.ok || !data?.ok) {
    errorBox.textContent = data?.errors?.join(" ") || "Could not clear QR.";
    return;
  }
  const existing = row.querySelector("img");
  if (existing) {
    existing.remove();
  }
  if (input) {
    input.value = "";
  }
  errorBox.textContent = "";
}

function updateExpenseState() {
  const enabled = people.length > 0;
  addExpenseBtn.disabled = !enabled;
  if (expenseHint) {
    expenseHint.textContent = enabled
      ? ""
      : "Add at least one person before creating expenses.";
  }
}

function renderSplitPeople() {
  splitPeople.innerHTML = "";
  if (splitType.value !== "custom") {
    return;
  }

  const payer = expensePayer.value;
  people
    .filter((p) => p !== payer)
    .forEach((person) => {
      const pill = document.createElement("label");
      pill.className = "pill";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.value = person;
      checkbox.checked = true;
      pill.appendChild(checkbox);
      pill.appendChild(document.createTextNode(person));
      splitPeople.appendChild(pill);
    });
}

function renderExpenseRows() {
  expenseRows.innerHTML = "";
  expenses.forEach((expense, idx) => {
    const row = document.createElement("div");
    row.className = "table-row";
    row.innerHTML = `
      <span>${expense.name}</span>
      <span>${expense.payer}</span>
      <span>${expense.split_type === "all" ? "Everyone" : expense.split_people.join(", ")}</span>
      <span>₹${expense.amount.toFixed(2)}</span>
      <span><button data-index="${idx}" class="ghost">Remove</button></span>
    `;
    row.querySelector("button").addEventListener("click", () => {
      expenses.splice(idx, 1);
      renderExpenseRows();
    });
    expenseRows.appendChild(row);
  });
}

addPersonBtn.addEventListener("click", () => {
  const raw = personInput.value.trim();
  if (!raw) {
    return;
  }
  if (people.some((p) => normalize(p) === normalize(raw))) {
    personInput.value = "";
    return;
  }
  people.push(raw);
  personInput.value = "";
  renderPeople();
  renderExpenseForm();
});

splitType.addEventListener("change", renderSplitPeople);
expensePayer.addEventListener("change", renderSplitPeople);

addExpenseBtn.addEventListener("click", async () => {
  const name = expenseName.value.trim();
  const amount = Number(expenseAmount.value);
  const payer = expensePayer.value;
  if (people.length === 0) {
    errorBox.textContent = "Add at least one person before adding expenses.";
    return;
  }
  if (!name || !amount || amount <= 0 || !payer) {
    errorBox.textContent = "Please enter a valid expense, amount, and payer.";
    return;
  }

  let split_people = [];
  if (splitType.value === "custom") {
    const checks = splitPeople.querySelectorAll("input[type='checkbox']");
    checks.forEach((check) => {
      if (check.checked) {
        split_people.push(check.value);
      }
    });
    if (!split_people.length) {
      errorBox.textContent = "Select at least one person for a custom split.";
      return;
    }
  }

  const files = Array.from(expenseBills.files || []);
  if (files.length) {
    const formData = new FormData();
    files.forEach((file) => formData.append("bills", file));
    formData.append("expense_name", name);
    if (billToken) {
      formData.append("bill_token", billToken);
    }
    errorBox.textContent = "Uploading bill photos for this expense...";
    const uploadRes = await fetch("/api/upload", {
      method: "POST",
      body: formData,
    });
    const uploadData = await uploadRes.json().catch(() => null);
    if (!uploadRes.ok || !uploadData?.ok) {
      errorBox.textContent =
        uploadData?.errors?.join(" ") || "Bill upload failed. Try again.";
      return;
    }
    billToken = uploadData.bill_token;
  }

  expenses.push({
    name,
    amount,
    payer,
    split_type: splitType.value,
    split_people,
  });

  expenseName.value = "";
  expenseAmount.value = "";
  expenseBills.value = "";
  errorBox.textContent = "";
  renderExpenseRows();
});

computeBtn.addEventListener("click", async () => {
  errorBox.textContent = "";
  summaryBox.textContent = "";
  settlements.innerHTML = "";

  if (people.length < 2) {
    errorBox.textContent = "Add at least two people.";
    return;
  }
  if (!expenses.length) {
    errorBox.textContent = "Add at least one expense.";
    return;
  }

  const payload = { people, expenses };
  if (billToken) {
    payload.bill_token = billToken;
  }
  lastPayload = payload;
  const res = await fetch("/api/compute", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  const data = await res.json();
  if (!data.ok) {
    errorBox.textContent = data.errors.join(" ");
    return;
  }

  summaryBox.textContent = data.summary;
  if (data.simplified_settlements.length === 0) {
    settlements.innerHTML = "<div class='settlement-card'>All balances are settled.</div>";
  } else {
    data.simplified_settlements.forEach((item) => {
      const card = document.createElement("div");
      card.className = "settlement-card";
      card.textContent = `${item.from} owes ${item.to} ₹${item.amount.toFixed(2)}`;
      settlements.appendChild(card);
    });
  }
});

downloadBtn.addEventListener("click", async () => {
  errorBox.textContent = "";
  if (!lastPayload) {
    errorBox.textContent = "Compute settlements first so we can build the receipt.";
    return;
  }
  const payload = { ...lastPayload };
  if (billToken) {
    payload.bill_token = billToken;
  }

  const res = await fetch("/api/receipt", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const data = await res.json().catch(() => null);
    errorBox.textContent = data?.errors?.join(" ") || "Could not download the receipt.";
    return;
  }

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "expense-receipt.txt";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
});

clearBtn.addEventListener("click", () => {
  people.length = 0;
  expenses.length = 0;
  personInput.value = "";
  expenseName.value = "";
  expenseAmount.value = "";
  expenseBills.value = "";
  summaryBox.textContent = "";
  settlements.innerHTML = "";
  errorBox.textContent = "";
  lastPayload = null;
  billToken = null;
  billUpload.value = "";
  billPreview.innerHTML = "";
  if (billStatus) {
    billStatus.textContent = "";
  }
  if (qrList) {
    qrList.innerHTML = "";
  }
  renderPeople();
  renderExpenseForm();
});

renderExpenseForm();
updateExpenseState();

billUpload.addEventListener("change", () => {
  const files = Array.from(billUpload.files || []);
  files.forEach((file) => {
    const img = document.createElement("img");
    img.alt = file.name;
    img.src = URL.createObjectURL(file);
    img.onload = () => URL.revokeObjectURL(img.src);
    billPreview.appendChild(img);
  });

  if (!files.length) {
    if (billStatus) {
      billStatus.textContent = "";
    }
    return;
  }

  if (billStatus) {
    billStatus.textContent = "Uploading bill photos...";
  }

  const formData = new FormData();
  files.forEach((file) => formData.append("bills", file));
  if (billToken) {
    formData.append("bill_token", billToken);
  }

  fetch("/api/upload", {
    method: "POST",
    body: formData,
  })
    .then((res) => res.json())
    .then((data) => {
      if (!data.ok) {
        throw new Error((data.errors || []).join(" ") || "Upload failed.");
      }
      billToken = data.bill_token;
      if (billStatus) {
        billStatus.textContent = `Uploaded ${data.count} new bill photo(s).`;
      }
    })
    .catch((err) => {
      billToken = null;
      if (billStatus) {
        billStatus.textContent = "Upload failed. Try again.";
      }
      console.error(err);
    });
});

async function refreshSavedSessions() {
  if (!savedSessions) {
    return;
  }
  const res = await fetch("/api/records");
  if (res.status === 401) {
    window.location.href = "/login";
    return;
  }
  const data = await res.json().catch(() => null);
  if (!data?.ok) {
    savedSessions.innerHTML = "<span class='muted'>No saved sessions yet.</span>";
    return;
  }
  if (!data.records.length) {
    savedSessions.innerHTML = "<span class='muted'>No saved sessions yet.</span>";
    return;
  }
  savedSessions.innerHTML = "";
  data.records.forEach((name) => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "saved-chip";
    chip.textContent = name;
    chip.addEventListener("click", () => loadSession(name));
    savedSessions.appendChild(chip);
  });
}

async function loadSession(name) {
  errorBox.textContent = "";
  const res = await fetch("/api/records/load", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (res.status === 401) {
    window.location.href = "/login";
    return;
  }
  const data = await res.json().catch(() => null);
  if (!res.ok || !data?.ok) {
    errorBox.textContent = data?.errors?.join(" ") || "Could not load session.";
    return;
  }
  const payload = data.data || {};
  people.length = 0;
  (payload.people || []).forEach((p) => {
    if (typeof p === "string" && p.trim()) {
      people.push(p.trim());
    }
  });

  expenses.length = 0;
  (payload.expenses || []).forEach((exp) => {
    if (!exp || typeof exp !== "object") {
      return;
    }
    expenses.push({
      name: String(exp.name || "").trim(),
      amount: Number(exp.amount || 0),
      payer: String(exp.payer || "").trim(),
      split_type: exp.split_type === "custom" ? "custom" : "all",
      split_people: Array.isArray(exp.split_people) ? exp.split_people : [],
    });
  });

  billToken = payload.bill_token || null;
  billPreview.innerHTML = "";
  billUpload.value = "";
  if (billStatus) {
    billStatus.textContent = billToken
      ? "Session loaded with bill photos linked."
      : "Session loaded. Bill photos must be re-uploaded.";
  }
  renderQrList();
  errorBox.textContent = "";
  summaryBox.textContent = "";
  settlements.innerHTML = "";
  lastPayload = null;

  renderPeople();
  renderExpenseForm();
}

saveProgressBtn.addEventListener("click", async () => {
  const name = saveNameInput.value.trim();
  if (!name) {
    errorBox.textContent = "Enter a name to save your progress.";
    return;
  }
  const res = await fetch("/api/records/save", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, people, expenses, bill_token: billToken }),
  });
  if (res.status === 401) {
    window.location.href = "/login";
    return;
  }
  const data = await res.json().catch(() => null);
  if (!res.ok || !data?.ok) {
    errorBox.textContent = data?.errors?.join(" ") || "Could not save session.";
    return;
  }
  errorBox.textContent = "";
  saveNameInput.value = data.name || name;
  await refreshSavedSessions();
});

refreshSavedSessions();

clearSessionsBtn.addEventListener("click", async () => {
  if (!confirm("This will delete all saved sessions. Continue?")) {
    return;
  }
  const res = await fetch("/api/records/clear", { method: "POST" });
  if (res.status === 401) {
    window.location.href = "/login";
    return;
  }
  const data = await res.json().catch(() => null);
  if (!res.ok || !data?.ok) {
    errorBox.textContent = "Could not clear saved sessions.";
    return;
  }
  errorBox.textContent = "";
  await refreshSavedSessions();
});

logoutBtn.addEventListener("click", async () => {
  await fetch("/api/auth/logout", { method: "POST" });
  window.location.href = "/login";
});

refreshSavedSessions();
