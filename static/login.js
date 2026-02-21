const authUsername = document.getElementById("authUsername");
const authPassword = document.getElementById("authPassword");
const loginBtn = document.getElementById("loginBtn");
const registerBtn = document.getElementById("registerBtn");
const authError = document.getElementById("authError");

async function handleAuth(endpoint) {
  const username = authUsername.value.trim();
  const password = authPassword.value;
  if (!username || !password) {
    authError.textContent = "Enter username and password.";
    return;
  }

  const res = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  const data = await res.json().catch(() => null);
  if (!res.ok || !data?.ok) {
    authError.textContent = data?.errors?.join(" ") || "Request failed.";
    return;
  }
  window.location.href = "/app";
}

loginBtn.addEventListener("click", () => handleAuth("/api/auth/login"));
registerBtn.addEventListener("click", () => handleAuth("/api/auth/register"));
