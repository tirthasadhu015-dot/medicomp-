const API_BASE = window.location.origin;
const RECENT_SEARCH_KEY = "mediscan_recent_searches";
const MAX_RECENT = 8;

const platformStyles = {
  "Apollo Pharmacy": { badge: "AP", tone: "bg-sky text-sky-900" },
  "Tata 1mg": { badge: "1M", tone: "bg-mint text-leaf" },
  "PharmEasy": { badge: "PE", tone: "bg-sand text-amber-900" },
};

const form = document.getElementById("searchForm");
const input = document.getElementById("medicineInput");
const loadingSkeleton = document.getElementById("loadingSkeleton");
const tableBody = document.getElementById("comparisonTableBody");
const resultMeta = document.getElementById("resultMeta");
const aiInsightsContent = document.getElementById("aiInsightsContent");
const recentSearches = document.getElementById("recentSearches");
const clearRecentBtn = document.getElementById("clearRecentBtn");

function escapeHTML(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function setLoadingState(isLoading) {
  loadingSkeleton.classList.toggle("hidden", !isLoading);
}

function getRecentSearches() {
  try {
    const parsed = JSON.parse(localStorage.getItem(RECENT_SEARCH_KEY) || "[]");
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function saveRecentSearch(term) {
  const normalized = term.trim();
  if (!normalized) return;

  const next = [normalized, ...getRecentSearches().filter((item) => item.toLowerCase() !== normalized.toLowerCase())].slice(0, MAX_RECENT);
  localStorage.setItem(RECENT_SEARCH_KEY, JSON.stringify(next));
  renderRecentSearches();
}

function renderRecentSearches() {
  const items = getRecentSearches();
  recentSearches.innerHTML = "";

  if (!items.length) {
    recentSearches.innerHTML = '<p class="rounded-2xl bg-slate-50 px-4 py-3 text-sm text-slate-500">No searches yet.</p>';
    return;
  }

  items.forEach((item) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "rounded-2xl border border-slate-200 bg-white px-4 py-3 text-left text-sm font-medium text-slate-700 transition hover:border-leaf hover:text-leaf";
    button.textContent = item;
    button.addEventListener("click", () => {
      input.value = item;
      runSearch(item);
    });
    recentSearches.appendChild(button);
  });
}

function renderTable(offers, lowestPrice) {
  tableBody.innerHTML = "";

  if (!offers.length) {
    tableBody.innerHTML = '<tr><td colspan="5" class="px-6 py-8 text-center text-sm text-slate-500">No offers found.</td></tr>';
    return;
  }

  offers.forEach((offer) => {
    const style = platformStyles[offer.platform] || { badge: "RX", tone: "bg-slate-100 text-slate-700" };
    const isLowest = typeof offer.price === "number" && offer.price === lowestPrice;
    const canBuy = offer.purchase_url && offer.status === "ok";
    const tr = document.createElement("tr");
    tr.className = "align-top";

    const priceMarkup = typeof offer.price === "number"
      ? `<span class="inline-flex rounded-full px-3 py-1 text-sm font-bold ${isLowest ? "bg-green-100 text-green-700" : "bg-slate-100 text-slate-700"}">Rs ${offer.price.toFixed(2)}</span>`
      : `<span class="inline-flex rounded-full bg-rose-50 px-3 py-1 text-sm font-medium text-rose-700">${escapeHTML(offer.error || "Unavailable")}</span>`;

    tr.innerHTML = `
      <td class="px-6 py-5">
        <div class="flex items-center gap-3">
          <div class="flex h-11 w-11 items-center justify-center rounded-2xl text-xs font-bold ${style.tone}">${style.badge}</div>
          <div>
            <p class="font-semibold text-slate-900">${escapeHTML(offer.platform)}</p>
            <p class="text-xs text-slate-500">${escapeHTML(offer.manufacturer || "Manufacturer unavailable")}</p>
          </div>
        </div>
      </td>
      <td class="px-6 py-5">
        <p class="font-semibold text-slate-900">${escapeHTML(offer.product_name)}</p>
        <p class="mt-1 text-xs text-slate-500">${escapeHTML(offer.salt_composition || "Salt composition pending normalization")}</p>
      </td>
      <td class="px-6 py-5 text-sm text-slate-700">${escapeHTML(offer.quantity || "Not listed")}</td>
      <td class="px-6 py-5">${priceMarkup}</td>
      <td class="px-6 py-5">
        <a
          class="inline-flex ${canBuy ? "bg-ink text-white hover:bg-leaf" : "bg-slate-100 text-slate-400 cursor-not-allowed pointer-events-none"} rounded-2xl px-4 py-2 text-sm font-semibold transition"
          href="${canBuy ? offer.purchase_url : "#"}"
          target="_blank"
          rel="noreferrer"
        >
          ${canBuy ? "Open Store" : "Unavailable"}
        </a>
      </td>
    `;
    tableBody.appendChild(tr);
  });
}

function renderAIInsights(insights) {
  const substitutes = Array.isArray(insights.substitutes) ? insights.substitutes : [];
  const substituteMarkup = substitutes.length
    ? substitutes.map((item) => `
        <div class="rounded-3xl border border-white/70 bg-white/80 p-4">
          <p class="text-sm font-semibold text-slate-900">${escapeHTML(item.brand_name)}</p>
          <p class="mt-1 text-xs uppercase tracking-[0.18em] text-slate-500">${escapeHTML(item.strength)}</p>
          <p class="mt-2 text-sm text-slate-600">${escapeHTML(item.salt_composition)}</p>
          <p class="mt-2 text-sm text-slate-700">${escapeHTML(item.reason)}</p>
          <p class="mt-3 text-sm font-semibold text-leaf">${typeof item.estimated_price === "number" ? `Estimated price: Rs ${item.estimated_price.toFixed(2)}` : "Price not estimated"}</p>
        </div>
      `).join("")
    : '<p class="rounded-3xl bg-white/70 p-4 text-sm text-slate-600">No exact substitute suggestions were generated.</p>';

  aiInsightsContent.innerHTML = `
    <div class="rounded-3xl bg-white/75 p-4">
      <p class="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Unified Salt</p>
      <p class="mt-2 text-lg font-semibold text-slate-900">${escapeHTML(insights.unified_salt || "Not confidently identified")}</p>
    </div>
    <div>
      <p class="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Analysis</p>
      <p class="mt-2 leading-6 text-slate-700">${escapeHTML(insights.analysis || "No analysis available.")}</p>
      <p class="mt-2 text-xs text-slate-500">Insight source: ${escapeHTML(insights.source || "unknown")}</p>
    </div>
    <div class="space-y-3">
      <p class="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Cheaper Generic Alternatives</p>
      ${substituteMarkup}
    </div>
  `;
}

function renderWarnings(warnings) {
  if (!warnings.length) return;
  alert(warnings.join("\n"));
}

async function runSearch(term) {
  const medicineName = term.trim();
  if (!medicineName) return;

  setLoadingState(true);
  resultMeta.textContent = `Fetching live prices for "${medicineName}"...`;

  try {
    const response = await fetch(`${API_BASE}/api/search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ medicine_name: medicineName }),
    });

    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Search failed.");
    }

    saveRecentSearch(medicineName);
    renderTable(payload.offers || [], payload.lowest_price);
    renderAIInsights(payload.ai_insights || {});

    const okOffers = (payload.offers || []).filter((offer) => offer.status === "ok").length;
    resultMeta.textContent = `${okOffers} live offers found for "${payload.medicine_name}". Lowest price ${typeof payload.lowest_price === "number" ? `Rs ${payload.lowest_price.toFixed(2)}` : "not available"}.`;

    if (payload.warnings?.length) {
      renderWarnings(payload.warnings);
    }
  } catch (error) {
    tableBody.innerHTML = '<tr><td colspan="5" class="px-6 py-8 text-center text-sm text-rose-600">Unable to load live prices right now.</td></tr>';
    aiInsightsContent.innerHTML = `<p class="rounded-3xl bg-rose-50 p-4 text-sm text-rose-700">${error.message}</p>`;
    resultMeta.textContent = "Search failed.";
    alert(error.message);
  } finally {
    setLoadingState(false);
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  runSearch(input.value);
});

clearRecentBtn.addEventListener("click", () => {
  localStorage.removeItem(RECENT_SEARCH_KEY);
  renderRecentSearches();
});

renderRecentSearches();
