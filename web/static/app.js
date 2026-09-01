const jobsEl = document.querySelector("#jobs");
const template = document.querySelector("#job-template");
const searchEl = document.querySelector("#search");
const statusEl = document.querySelector("#status-filter");
const modeEl = document.querySelector("#mode-filter");
const countEl = document.querySelector("#result-count");
const summaryEl = document.querySelector("#summary");
const emptyEl = document.querySelector("#empty");
const messageEl = document.querySelector("#save-message");
const runSearchEl = document.querySelector("#run-search");
const searchModeEl = document.querySelector("#search-mode");
const searchProgressEl = document.querySelector("#search-progress");
const searchProgressTextEl = document.querySelector("#search-progress-text");
const searchProgressDetailEl = document.querySelector("#search-progress-detail");
const searchSpinnerEl = document.querySelector(".spinner");
let searchTimer;
let searchPollTimer;
let observedRunningSearch = false;

const labels = {
  all: "Total roles",
  unreviewed: "To review",
  applied: "Applied",
  maybe: "Maybe",
  not_applying: "Passed",
};

function escapeText(value) {
  return value ?? "";
}

function renderSummary(counts) {
  summaryEl.replaceChildren();
  ["all", "unreviewed", "applied", "maybe"].forEach((key) => {
    const item = document.createElement("div");
    item.className = `summary-item summary-${key}`;
    const number = document.createElement("strong");
    number.textContent = counts[key] ?? 0;
    const label = document.createElement("span");
    label.textContent = labels[key];
    item.append(number, label);
    summaryEl.append(item);
  });
}

function formatDate(value) {
  if (!value) return "Unknown";
  return new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" })
    .format(new Date(`${value}T12:00:00`));
}

function makeBadge(text, className) {
  const badge = document.createElement("span");
  badge.className = `badge ${className}`;
  badge.textContent = text;
  return badge;
}

function createCard(job) {
  const card = template.content.firstElementChild.cloneNode(true);
  card.dataset.status = job.status;
  card.querySelector(".job-title").textContent = escapeText(job.title) || "Untitled role";
  card.querySelector(".job-meta").textContent = [job.company, job.location].filter(Boolean).join("  ·  ");
  card.querySelector(".seen").textContent = `First found ${formatDate(job.first_seen)}  ·  Last seen ${formatDate(job.last_seen)}`;
  const link = card.querySelector(".open-job");
  link.href = job.url;
  const badges = card.querySelector(".badges");
  badges.append(makeBadge(job.easy_apply ? "Easy Apply" : "External application", job.easy_apply ? "easy" : "external"));
  if (job.status !== "unreviewed") badges.append(makeBadge(labels[job.status] || job.status, `status-${job.status}`));

  const select = card.querySelector(".status-select");
  const notes = card.querySelector("textarea");
  const save = card.querySelector(".save-button");
  select.value = job.status;
  notes.value = job.notes || "";
  const markDirty = () => { save.textContent = "Save changes"; save.classList.add("dirty"); };
  select.addEventListener("change", markDirty);
  notes.addEventListener("input", markDirty);
  save.addEventListener("click", async () => {
    save.disabled = true;
    save.textContent = "Saving…";
    try {
      const response = await fetch(`/api/jobs/${encodeURIComponent(job.job_id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: select.value, notes: notes.value }),
      });
      if (!response.ok) throw new Error("Save failed");
      messageEl.textContent = `Saved “${job.title}”`;
      setTimeout(() => { messageEl.textContent = ""; }, 2500);
      await loadJobs();
    } catch (error) {
      save.textContent = "Try again";
      messageEl.textContent = "Could not save that change.";
    } finally {
      save.disabled = false;
    }
  });
  return card;
}

async function loadJobs() {
  const params = new URLSearchParams({
    q: searchEl.value.trim(),
    status: statusEl.value,
    mode: modeEl.value,
  });
  try {
    const response = await fetch(`/api/jobs?${params}`);
    if (!response.ok) throw new Error("Load failed");
    const data = await response.json();
    jobsEl.replaceChildren(...data.jobs.map(createCard));
    countEl.textContent = data.jobs.length;
    emptyEl.hidden = data.jobs.length !== 0;
    renderSummary(data.counts);
  } catch (error) {
    jobsEl.replaceChildren();
    emptyEl.hidden = false;
    emptyEl.querySelector("h3").textContent = "The dashboard could not load your jobs";
  }
}

searchEl.addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(loadJobs, 250);
});
statusEl.addEventListener("change", loadJobs);
modeEl.addEventListener("change", loadJobs);

async function pollSearch() {
  try {
    const response = await fetch("/api/search");
    if (!response.ok) throw new Error("Status unavailable");
    const state = await response.json();
    runSearchEl.disabled = state.running;
    searchModeEl.disabled = state.running;
    searchSpinnerEl.hidden = !state.running;
    searchProgressEl.hidden = !(state.running || state.return_code !== null);
    searchProgressTextEl.textContent = state.message || "Preparing search…";
    const output = state.output || [];
    searchProgressDetailEl.textContent = output.length > 1 ? output[output.length - 2] : "";

    if (state.running) {
      observedRunningSearch = true;
      runSearchEl.textContent = "Searching…";
      searchPollTimer = setTimeout(pollSearch, 1000);
      return;
    }

    runSearchEl.textContent = "Find new jobs";
    if (observedRunningSearch) {
      observedRunningSearch = false;
      if (state.return_code === 0) {
        searchProgressTextEl.textContent = "Search complete — job list updated";
        statusEl.value = "unreviewed";
        modeEl.value = "all";
        searchEl.value = "";
        await loadJobs();
      }
    }
  } catch (error) {
    searchSpinnerEl.hidden = true;
    searchProgressEl.hidden = false;
    searchProgressTextEl.textContent = "Could not read search progress";
  }
}

runSearchEl.addEventListener("click", async () => {
  runSearchEl.disabled = true;
  searchModeEl.disabled = true;
  searchProgressEl.hidden = false;
  searchSpinnerEl.hidden = false;
  searchProgressTextEl.textContent = "Starting search…";
  searchProgressDetailEl.textContent = "A LinkedIn window will open while the search runs.";
  try {
    const response = await fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: searchModeEl.value }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not start search");
    observedRunningSearch = true;
    clearTimeout(searchPollTimer);
    await pollSearch();
  } catch (error) {
    searchSpinnerEl.hidden = true;
    runSearchEl.disabled = false;
    searchModeEl.disabled = false;
    searchProgressTextEl.textContent = error.message;
  }
});

loadJobs();
pollSearch();
