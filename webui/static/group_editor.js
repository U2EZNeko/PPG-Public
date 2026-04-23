/**
 * Structured editor for PPG group JSON files (genre / mood / mixes).
 */
(function () {
  "use strict";

  const jsonSelect = document.getElementById("json-file-select");
  const jsonEditor = document.getElementById("json-editor");
  const jsonVisual = document.getElementById("json-visual");
  const jsonMeta = document.getElementById("json-meta");
  const jsonReloadBtn = document.getElementById("json-reload");
  const jsonFormatBtn = document.getElementById("json-format");
  const jsonDownloadBtn = document.getElementById("json-download");
  const jsonUploadBtn = document.getElementById("json-upload");
  const jsonUploadInput = document.getElementById("json-upload-input");
  const jsonSaveBtn = document.getElementById("json-save");
  const jsonViewFormBtn = document.getElementById("json-view-form");
  const jsonViewRawBtn = document.getElementById("json-view-raw");
  const jsonAddGroupBtn = document.getElementById("json-add-group");
  const jsonSortGroupsBtn = document.getElementById("json-sort-groups");
  const jsonFilterInput = document.getElementById("json-group-filter");
  const jsonFetchGenresBtn = document.getElementById("json-fetch-genres");
  const plexGenresStatusEl = document.getElementById("plex-genres-status");
  const plexGenresDatalist = document.getElementById("plex-genres-datalist");
  const jsonFetchMoodsBtn = document.getElementById("json-fetch-moods");
  const plexMoodsStatusEl = document.getElementById("plex-moods-status");
  const plexMoodsDatalist = document.getElementById("plex-moods-datalist");
  const toastEl = document.getElementById("toast");

  if (!jsonSelect || !jsonEditor || !jsonVisual) return;

  const PLEX_GENRES_STORAGE_KEY = "ppg_webui_plex_genres_v1";
  let plexGenres = [];
  let plexGenresSet = new Set();
  /** True once we have a non-empty list from Plex or from localStorage. */
  let plexGenresReady = false;

  const PLEX_MOODS_STORAGE_KEY = "ppg_webui_plex_moods_v1";
  let plexMoods = [];
  let plexMoodsSet = new Set();
  let plexMoodsReady = false;

  let entries = [];
  let viewMode = "form";
  let jsonDirty = false;
  let jsonLoading = false;
  let jsonSelectLockedValue = jsonSelect.value;
  let parseError = null;

  function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  function showToast(msg, isErr) {
    if (!toastEl) return;
    toastEl.textContent = msg;
    toastEl.classList.add("show");
    toastEl.classList.toggle("err", !!isErr);
    clearTimeout(showToast._t);
    showToast._t = setTimeout(() => toastEl.classList.remove("show"), 4500);
  }

  function setJsonDirty(on) {
    jsonDirty = !!on;
    jsonSaveBtn.disabled = jsonLoading || !jsonDirty;
  }

  function updateJsonMeta(text, isWarn) {
    jsonMeta.textContent = text || "";
    jsonMeta.classList.toggle("warn", !!isWarn);
  }

  function updateJsonFileOptionLabel(fileId, groupCount) {
    const opt = Array.from(jsonSelect.options).find((o) => o.value === fileId);
    if (!opt) return;
    const file = opt.getAttribute("data-file") || "";
    const label = opt.getAttribute("data-label") || fileId;
    const g = groupCount === 1 ? "group" : "groups";
    opt.textContent = label + " (" + file + ") — " + groupCount + " " + g;
  }

  function syncPlexGenresDatalist() {
    if (!plexGenresDatalist) return;
    plexGenresDatalist.innerHTML = "";
    const frag = document.createDocumentFragment();
    for (const g of plexGenres) {
      const o = document.createElement("option");
      o.value = g;
      frag.appendChild(o);
    }
    plexGenresDatalist.appendChild(frag);
  }

  function updatePlexGenresStatusUi() {
    if (!plexGenresStatusEl) return;
    if (!plexGenresReady || plexGenres.length === 0) {
      plexGenresStatusEl.textContent =
        "No Plex genres loaded — fetch before adding genres to a group.";
    } else {
      plexGenresStatusEl.textContent =
        plexGenres.length + " Plex genres (genre / mix files only).";
    }
  }

  function refreshGenrePickerControls() {
    document.querySelectorAll('.tag-add-row[data-plex-genres="1"]').forEach((row) => {
      const btn = row.querySelector(".tag-add");
      const inp = row.querySelector(".tag-input");
      const on = plexGenresReady && plexGenres.length > 0;
      if (btn) btn.disabled = !on;
      if (inp) {
        inp.placeholder = on
          ? "Type or pick a Plex genre…"
          : "Fetch Plex genres first…";
      }
    });
  }

  /**
   * @param {string[]} arr
   * @param {boolean} persist - write localStorage (after successful API fetch)
   */
  function applyPlexGenres(arr, persist) {
    plexGenres = Array.from(
      new Set((arr || []).map((x) => String(x).trim()).filter(Boolean))
    ).sort((a, b) => a.localeCompare(b));
    plexGenresSet = new Set(plexGenres);
    plexGenresReady = plexGenres.length > 0;
    syncPlexGenresDatalist();
    if (persist) {
      try {
        localStorage.setItem(
          PLEX_GENRES_STORAGE_KEY,
          JSON.stringify({ genres: plexGenres, fetchedAt: Date.now() })
        );
      } catch (e) {
        /* ignore quota */
      }
    }
    updatePlexGenresStatusUi();
    refreshGenrePickerControls();
  }

  function loadPlexGenresFromStorage() {
    try {
      const raw = localStorage.getItem(PLEX_GENRES_STORAGE_KEY);
      if (!raw) return;
      const j = JSON.parse(raw);
      if (Array.isArray(j.genres) && j.genres.length) {
        applyPlexGenres(j.genres, false);
      }
    } catch (e) {
      /* ignore */
    }
  }

  function syncPlexMoodsDatalist() {
    if (!plexMoodsDatalist) return;
    plexMoodsDatalist.innerHTML = "";
    const frag = document.createDocumentFragment();
    for (const m of plexMoods) {
      const o = document.createElement("option");
      o.value = m;
      frag.appendChild(o);
    }
    plexMoodsDatalist.appendChild(frag);
  }

  function updatePlexMoodsStatusUi() {
    if (!plexMoodsStatusEl) return;
    if (!plexMoodsReady || plexMoods.length === 0) {
      plexMoodsStatusEl.textContent =
        "No Plex moods loaded — fetch before adding moods to a group.";
    } else {
      plexMoodsStatusEl.textContent =
        plexMoods.length + " Plex moods (mood groups file only).";
    }
  }

  function refreshMoodPickerControls() {
    document.querySelectorAll('.tag-add-row[data-plex-moods="1"]').forEach((row) => {
      const btn = row.querySelector(".tag-add");
      const inp = row.querySelector(".tag-input");
      const on = plexMoodsReady && plexMoods.length > 0;
      if (btn) btn.disabled = !on;
      if (inp) {
        inp.placeholder = on
          ? "Type or pick a Plex mood…"
          : "Fetch Plex moods first…";
      }
    });
  }

  function applyPlexMoods(arr, persist) {
    plexMoods = Array.from(
      new Set((arr || []).map((x) => String(x).trim()).filter(Boolean))
    ).sort((a, b) => a.localeCompare(b));
    plexMoodsSet = new Set(plexMoods);
    plexMoodsReady = plexMoods.length > 0;
    syncPlexMoodsDatalist();
    if (persist) {
      try {
        localStorage.setItem(
          PLEX_MOODS_STORAGE_KEY,
          JSON.stringify({ moods: plexMoods, fetchedAt: Date.now() })
        );
      } catch (e) {
        /* ignore quota */
      }
    }
    updatePlexMoodsStatusUi();
    refreshMoodPickerControls();
  }

  function loadPlexMoodsFromStorage() {
    try {
      const raw = localStorage.getItem(PLEX_MOODS_STORAGE_KEY);
      if (!raw) return;
      const j = JSON.parse(raw);
      if (Array.isArray(j.moods) && j.moods.length) {
        applyPlexMoods(j.moods, false);
      }
    } catch (e) {
      /* ignore */
    }
  }

  function uid() {
    return crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random();
  }

  function parseEntriesFromObject(obj, fileId) {
    const out = [];
    if (!obj || typeof obj !== "object" || Array.isArray(obj)) {
      throw new Error("Root must be a JSON object");
    }
    const keys = Object.keys(obj);
    for (const name of keys) {
      const val = obj[name];
      if (fileId === "mood_groups") {
        if (!Array.isArray(val)) {
          throw new Error('Mood group "' + name + '" must be an array');
        }
        out.push({
          _uid: uid(),
          kind: "mood",
          name,
          tags: val.map((x) => String(x)),
        });
        continue;
      }
      if (Array.isArray(val)) {
        out.push({
          _uid: uid(),
          kind: "simple",
          name,
          genres: val.map((x) => String(x)),
        });
      } else if (val && typeof val === "object") {
        const genres = Array.isArray(val.genres)
          ? val.genres.map((x) => String(x))
          : [];
        const extra = { ...val };
        delete extra.genres;
        delete extra.release_date_filter;
        delete extra.prefer_liked_artists;
        let filter = null;
        const rdf = val.release_date_filter;
        if (rdf && typeof rdf === "object") {
          filter = {
            condition: String(rdf.condition || "between"),
            start_date:
              rdf.start_date != null && rdf.start_date !== ""
                ? String(rdf.start_date)
                : "",
            end_date:
              rdf.end_date != null && rdf.end_date !== ""
                ? String(rdf.end_date)
                : "",
          };
        }
        let preferLiked = null;
        if (typeof val.prefer_liked_artists === "boolean") {
          preferLiked = val.prefer_liked_artists;
        }
        out.push({
          _uid: uid(),
          kind: "rich",
          name,
          genres,
          filter,
          preferLiked,
          extra,
        });
      } else {
        throw new Error('Invalid value for group "' + name + '"');
      }
    }
    return out;
  }

  function serializeEntries(fileId) {
    const out = {};
    for (const e of entries) {
      const name = e.name.trim();
      if (!name) continue;
      if (out[name] !== undefined) {
        throw new Error('Duplicate group name: "' + name + '"');
      }
      if (fileId === "mood_groups") {
        out[name] = e.tags.slice();
      } else if (e.kind === "simple") {
        out[name] = e.genres.slice();
      } else {
        const o = { ...(e.extra || {}) };
        o.genres = e.genres.slice();
        if (e.filter && e.filter.condition) {
          const c = e.filter.condition;
          const f = { condition: c };
          if (c === "between") {
            f.start_date = e.filter.start_date || "";
            f.end_date = e.filter.end_date || "";
          } else if (c === "after") {
            f.start_date = e.filter.start_date || "";
          } else if (c === "before") {
            f.end_date = e.filter.end_date || "";
          }
          o.release_date_filter = f;
        }
        if (e.preferLiked !== null && e.preferLiked !== undefined) {
          o.prefer_liked_artists = e.preferLiked;
        }
        out[name] = o;
      }
    }
    return out;
  }

  function syncTextareaFromEntries() {
    const fileId = jsonSelect.value;
    const text = JSON.stringify(serializeEntries(fileId), null, 2) + "\n";
    jsonEditor.value = text;
  }

  function selectedJsonDiskFilename() {
    const opt = jsonSelect.options[jsonSelect.selectedIndex];
    return (opt && opt.getAttribute("data-file")) || "export.json";
  }

  /** Same bytes the user would save: raw buffer in raw/parse-error mode, else serialized form. */
  function getJsonTextForExport() {
    const id = jsonSelect.value;
    if (!id) return null;
    if (viewMode === "raw" || parseError) {
      return jsonEditor.value;
    }
    try {
      return JSON.stringify(serializeEntries(id), null, 2) + "\n";
    } catch (e) {
      showToast(e.message, true);
      return null;
    }
  }

  function downloadCurrentJson() {
    const id = jsonSelect.value;
    if (!id) return;
    const text = getJsonTextForExport();
    if (text == null) return;
    const name = selectedJsonDiskFilename();
    const blob = new Blob([text], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    showToast("Downloaded " + name);
  }

  function applyFilter() {
    const q = (jsonFilterInput && jsonFilterInput.value || "").trim().toLowerCase();
    jsonVisual.querySelectorAll(".group-card").forEach((card) => {
      const name = (card.querySelector(".group-card-name") || {}).value || "";
      const ok = !q || name.toLowerCase().includes(q);
      card.style.display = ok ? "" : "none";
    });
  }

  function setViewMode(mode) {
    viewMode = mode;
    const isForm = mode === "form";
    jsonVisual.classList.toggle("hidden", !isForm);
    jsonEditor.classList.toggle("hidden", isForm);
    if (jsonViewFormBtn && jsonViewRawBtn) {
      jsonViewFormBtn.classList.toggle("active", isForm);
      jsonViewRawBtn.classList.toggle("active", !isForm);
    }
    if (jsonAddGroupBtn) jsonAddGroupBtn.disabled = !isForm || !!parseError;
    if (jsonSortGroupsBtn) {
      jsonSortGroupsBtn.disabled = !isForm || !!parseError || entries.length < 2;
    }
    if (jsonFilterInput) jsonFilterInput.disabled = !isForm || !!parseError;
    if (!isForm && !parseError) {
      try {
        syncTextareaFromEntries();
      } catch (e) {
        showToast(e.message, true);
      }
    }
  }

  function bindCard(wrap, e, fileId) {
    const expandBtn = wrap.querySelector(".group-card-expand");
    const head = wrap.querySelector(".group-card-head");
    const body = wrap.querySelector(".group-card-body");
    const nameInput = wrap.querySelector(".group-card-name");
    const badge = wrap.querySelector(".group-card-badge");
    const removeBtn = wrap.querySelector(".group-card-remove");

    function refreshBadge() {
      if (e.kind === "mood") {
        badge.textContent = e.tags.length + " moods";
      } else {
        badge.textContent = e.genres.length + " genres";
      }
    }
    refreshBadge();

    function toggleExpand() {
      const open = !body.hidden;
      body.hidden = open;
      expandBtn.textContent = open ? "▶" : "▼";
      expandBtn.setAttribute("aria-expanded", open ? "false" : "true");
    }

    expandBtn.addEventListener("click", toggleExpand);
    head.addEventListener("dblclick", (ev) => {
      if (ev.target === nameInput) return;
      toggleExpand();
    });

    nameInput.addEventListener("input", () => {
      e.name = nameInput.value;
      setJsonDirty(true);
      updateJsonMeta("Unsaved changes");
    });

    removeBtn.addEventListener("click", () => {
      if (!window.confirm('Remove group "' + e.name + '"?')) return;
      entries = entries.filter((x) => x._uid !== e._uid);
      wrap.remove();
      setJsonDirty(true);
      updateJsonMeta("Unsaved changes");
    });

    const tagList = wrap.querySelector(".tag-list");
    const tagInput = wrap.querySelector(".tag-input");
    const tagAddBtn = wrap.querySelector(".tag-add");
    const tagAddRow = wrap.querySelector(".tag-add-row");

    const tags = e.kind === "mood" ? e.tags : e.genres;

    if (fileId === "mood_groups" && tagAddRow) {
      tagAddRow.setAttribute("data-plex-moods", "1");
      tagInput.setAttribute("list", "plex-moods-datalist");
    } else if (fileId !== "mood_groups" && tagAddRow) {
      tagAddRow.setAttribute("data-plex-genres", "1");
      tagInput.setAttribute("list", "plex-genres-datalist");
    }

    function renderTags() {
      tagList.innerHTML = "";
      const isMoodFile = fileId === "mood_groups";
      tags.forEach((tag, idx) => {
        const span = document.createElement("span");
        span.className = "tag-chip";
        /* Off-Plex genres/moods already in the file are kept as-is; scripts use them normally. */
        span.appendChild(document.createTextNode(tag + " "));
        const x = document.createElement("button");
        x.type = "button";
        x.className = "tag-remove";
        x.setAttribute("aria-label", "Remove");
        x.textContent = "×";
        x.addEventListener("click", () => {
          tags.splice(idx, 1);
          renderTags();
          refreshBadge();
          setJsonDirty(true);
          updateJsonMeta("Unsaved changes");
        });
        span.appendChild(x);
        tagList.appendChild(span);
      });
    }
    renderTags();

    function addTag() {
      const v = tagInput.value.trim();
      if (!v) return;
      if (fileId === "mood_groups") {
        if (!plexMoodsReady || plexMoods.length === 0) {
          showToast("Fetch moods from Plex first.", true);
          return;
        }
        if (!plexMoodsSet.has(v)) {
          showToast("Only Plex library moods are allowed — pick from the suggestions list.", true);
          return;
        }
      } else {
        if (!plexGenresReady || plexGenres.length === 0) {
          showToast("Fetch genres from Plex first.", true);
          return;
        }
        if (!plexGenresSet.has(v)) {
          showToast("Only Plex library genres are allowed — pick from the suggestions list.", true);
          return;
        }
      }
      if (tags.includes(v)) {
        showToast("Already in this group.", true);
        return;
      }
      tags.push(v);
      tagInput.value = "";
      renderTags();
      refreshBadge();
      setJsonDirty(true);
      updateJsonMeta("Unsaved changes");
    }
    tagAddBtn.addEventListener("click", addTag);
    tagInput.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") {
        ev.preventDefault();
        addTag();
      }
    });

    if (e.kind === "rich") {
      const condSel = wrap.querySelector(".filter-condition");
      const startL = wrap.querySelector(".filter-start-wrap");
      const endL = wrap.querySelector(".filter-end-wrap");
      const startIn = wrap.querySelector(".filter-start-input");
      const endIn = wrap.querySelector(".filter-end-input");
      const prefSel = wrap.querySelector(".prefer-liked");

      function syncFilterVisibility() {
        const c = condSel.value;
        startL.style.display = c === "between" || c === "after" ? "" : "none";
        endL.style.display = c === "between" || c === "before" ? "" : "none";
      }

      if (e.filter) {
        condSel.value = e.filter.condition || "";
        startIn.value = e.filter.start_date || "";
        endIn.value = e.filter.end_date || "";
      } else {
        condSel.value = "";
      }
      if (e.preferLiked === true) prefSel.value = "true";
      else if (e.preferLiked === false) prefSel.value = "false";
      else prefSel.value = "";

      syncFilterVisibility();

      condSel.addEventListener("change", () => {
        const c = condSel.value;
        if (!c) {
          e.filter = null;
        } else {
          e.filter = e.filter || {
            condition: c,
            start_date: "",
            end_date: "",
          };
          e.filter.condition = c;
        }
        syncFilterVisibility();
        setJsonDirty(true);
        updateJsonMeta("Unsaved changes");
      });
      startIn.addEventListener("input", () => {
        if (e.filter) e.filter.start_date = startIn.value;
        setJsonDirty(true);
        updateJsonMeta("Unsaved changes");
      });
      endIn.addEventListener("input", () => {
        if (e.filter) e.filter.end_date = endIn.value;
        setJsonDirty(true);
        updateJsonMeta("Unsaved changes");
      });
      prefSel.addEventListener("change", () => {
        const v = prefSel.value;
        e.preferLiked = v === "" ? null : v === "true";
        setJsonDirty(true);
        updateJsonMeta("Unsaved changes");
      });
    }

    if (fileId !== "mood_groups" && e.kind === "simple") {
      const upBtn = wrap.querySelector(".promote-rich");
      if (upBtn) {
        upBtn.addEventListener("click", () => {
          e.kind = "rich";
          e.filter = null;
          e.preferLiked = null;
          e.extra = {};
          renderAll();
          setJsonDirty(true);
          updateJsonMeta("Unsaved changes");
        });
      }
    }

    refreshGenrePickerControls();
    refreshMoodPickerControls();
  }

  function cardTemplate(e, fileId) {
    const isMood = fileId === "mood_groups";
    const label = isMood ? "Mood tags" : "Genres";
    const wrap = document.createElement("div");
    wrap.className = "group-card";
    wrap.dataset.uid = e._uid;

    const head = document.createElement("div");
    head.className = "group-card-head";

    const expandBtn = document.createElement("button");
    expandBtn.type = "button";
    expandBtn.className = "group-card-expand";
    expandBtn.textContent = "▶";
    expandBtn.setAttribute("aria-expanded", "false");

    const nameInput = document.createElement("input");
    nameInput.type = "text";
    nameInput.className = "group-card-name";
    nameInput.value = e.name;
    nameInput.setAttribute("aria-label", "Group name");

    const badge = document.createElement("span");
    badge.className = "group-card-badge";

    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "group-card-remove";
    removeBtn.textContent = "Remove";

    head.append(expandBtn, nameInput, badge, removeBtn);

    const body = document.createElement("div");
    body.className = "group-card-body";
    body.hidden = true;

    const tagsLabel = document.createElement("div");
    tagsLabel.className = "field-label";
    tagsLabel.textContent = label;
    const tagList = document.createElement("div");
    tagList.className = "tag-list";
    const addRow = document.createElement("div");
    addRow.className = "tag-add-row";
    const tagInput = document.createElement("input");
    tagInput.type = "text";
    tagInput.className = "tag-input";
    tagInput.placeholder = isMood ? "Add mood…" : "Add genre…";
    const tagAdd = document.createElement("button");
    tagAdd.type = "button";
    tagAdd.className = "tag-add";
    tagAdd.textContent = "Add";
    addRow.append(tagInput, tagAdd);
    body.append(tagsLabel, tagList, addRow);

    if (e.kind === "rich") {
      const fl = document.createElement("div");
      fl.className = "filter-block";
      fl.innerHTML =
        '<div class="field-label">Release date filter</div>' +
        '<div class="filter-row">' +
        '<select class="filter-condition" aria-label="Filter condition">' +
        '<option value="">No filter</option>' +
        '<option value="before">Before year</option>' +
        '<option value="after">After year</option>' +
        '<option value="between">Between years</option>' +
        "</select>" +
        '<span class="filter-start-wrap"><label>Start <input type="text" class="filter-start-input" placeholder="e.g. 1990" /></label></span>' +
        '<span class="filter-end-wrap"><label>End <input type="text" class="filter-end-input" placeholder="e.g. 1999" /></label></span>' +
        "</div>" +
        '<div class="prefer-row"><label>Liked artists <select class="prefer-liked">' +
        '<option value="">(not set)</option><option value="true">Prefer</option><option value="false">Do not prefer</option>' +
        "</select></label></div>";
      body.appendChild(fl);
    } else if (!isMood) {
      const prom = document.createElement("div");
      prom.className = "promote-row";
      const b = document.createElement("button");
      b.type = "button";
      b.className = "promote-rich";
      b.textContent = "Add release-date filter & options";
      prom.appendChild(b);
      body.appendChild(prom);
    }

    wrap.append(head, body);
    bindCard(wrap, e, fileId);
    return wrap;
  }

  function renderAll() {
    jsonVisual.innerHTML = "";
    const fileId = jsonSelect.value;
    const frag = document.createDocumentFragment();
    for (const e of entries) {
      frag.appendChild(cardTemplate(e, fileId));
    }
    jsonVisual.appendChild(frag);
    applyFilter();
    refreshGenrePickerControls();
    refreshMoodPickerControls();
    if (jsonSortGroupsBtn) {
      jsonSortGroupsBtn.disabled =
        viewMode !== "form" || !!parseError || entries.length < 2;
    }
  }

  function ingestJsonText(text, fileId) {
    parseError = null;
    const obj = JSON.parse(text);
    entries = parseEntriesFromObject(obj, fileId);
    renderAll();
    setJsonDirty(false);
    updateJsonMeta(
      "Form view — " + entries.length + " group(s). Double-click header to expand."
    );
  }

  async function loadJsonFile() {
    const id = jsonSelect.value;
    if (!id) return;
    jsonLoading = true;
    jsonReloadBtn.disabled = true;
    jsonSaveBtn.disabled = true;
    updateJsonMeta("Loading…");
    try {
      const r = await fetch("/api/json-groups/" + encodeURIComponent(id));
      const j = await r.json();
      if (!r.ok) {
        updateJsonMeta(j.error || "Load failed", true);
        showToast(j.error || "Load failed", true);
        return;
      }
      let text = j.content != null ? String(j.content) : "";
      if (!text.trim()) text = "{}\n";
      jsonEditor.value = text;
      jsonSelectLockedValue = jsonSelect.value;
      parseError = null;
      try {
        ingestJsonText(text, id);
        setViewMode("form");
        updateJsonFileOptionLabel(id, entries.length);
        updateJsonMeta(
          (j.exists ? "On disk — " : "New file — ") +
            (jsonSelect.options[jsonSelect.selectedIndex]?.text || id)
        );
      } catch (err) {
        parseError = err;
        entries = [];
        jsonVisual.innerHTML =
          '<p class="parse-error">Cannot show form view: ' +
          escapeHtml(err.message) +
          ". Fix JSON in raw view or reload.</p>";
        setViewMode("raw");
        updateJsonMeta("Invalid JSON — raw editor", true);
        showToast(err.message, true);
      }
    } catch (e) {
      updateJsonMeta(String(e), true);
      showToast(String(e), true);
    } finally {
      jsonLoading = false;
      jsonReloadBtn.disabled = false;
      jsonSaveBtn.disabled = jsonLoading || !jsonDirty;
    }
  }

  async function saveJsonFile() {
    const id = jsonSelect.value;
    if (!id) return;
    let text;
    if (viewMode === "raw" || parseError) {
      text = jsonEditor.value;
      try {
        JSON.parse(text);
      } catch (e) {
        showToast("Invalid JSON: " + e.message, true);
        return;
      }
    } else {
      try {
        text = JSON.stringify(serializeEntries(id), null, 2) + "\n";
      } catch (e) {
        showToast(e.message, true);
        return;
      }
    }
    jsonSaveBtn.disabled = true;
    updateJsonMeta("Saving…");
    try {
      const r = await fetch("/api/json-groups/" + encodeURIComponent(id), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: text }),
      });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) {
        updateJsonMeta(j.error || "Save failed", true);
        showToast(j.error || "Save failed", true);
        jsonSaveBtn.disabled = jsonLoading || !jsonDirty;
        return;
      }
      jsonEditor.value = text;
      parseError = null;
      try {
        ingestJsonText(text, id);
        setViewMode("form");
      } catch (e) {
        parseError = e;
        setViewMode("raw");
      }
      setJsonDirty(false);
      updateJsonFileOptionLabel(id, entries.length);
      showToast("Saved", false);
      updateJsonMeta("Saved — " + (jsonSelect.options[jsonSelect.selectedIndex]?.text || id));
      if (typeof window.__ppgRefreshScriptCardMeta === "function") {
        window.__ppgRefreshScriptCardMeta();
      }
    } catch (e) {
      updateJsonMeta(String(e), true);
      showToast(String(e), true);
    } finally {
      jsonSaveBtn.disabled = jsonLoading || !jsonDirty;
    }
  }

  function formatJson() {
    if (viewMode === "form" && !parseError) {
      try {
        const text = JSON.stringify(serializeEntries(jsonSelect.value), null, 2) + "\n";
        jsonEditor.value = text;
        ingestJsonText(text, jsonSelect.value);
        setViewMode("form");
        setJsonDirty(true);
        updateJsonMeta("Reformatted (unsaved)");
        showToast("Reformatted", false);
      } catch (e) {
        showToast(e.message, true);
      }
      return;
    }
    try {
      const parsed = JSON.parse(jsonEditor.value);
      jsonEditor.value = JSON.stringify(parsed, null, 2) + "\n";
      setJsonDirty(true);
      updateJsonMeta("Formatted (unsaved)");
    } catch (e) {
      showToast("Format: " + e.message, true);
    }
  }

  jsonEditor.addEventListener("input", () => {
    setJsonDirty(true);
    jsonSaveBtn.disabled = false;
    updateJsonMeta("Unsaved changes (raw)");
  });

  jsonSelect.addEventListener("change", () => {
    if (jsonDirty && !window.confirm("Discard unsaved changes and switch file?")) {
      jsonSelect.value = jsonSelectLockedValue;
      return;
    }
    jsonSelectLockedValue = jsonSelect.value;
    loadJsonFile();
  });

  jsonReloadBtn.addEventListener("click", () => {
    if (jsonDirty && !window.confirm("Reload from disk and discard edits?")) return;
    loadJsonFile();
  });

  jsonFormatBtn.addEventListener("click", formatJson);
  if (jsonDownloadBtn) {
    jsonDownloadBtn.addEventListener("click", downloadCurrentJson);
  }

  if (jsonUploadBtn && jsonUploadInput) {
    jsonUploadBtn.addEventListener("click", () => {
      if (jsonDirty && !window.confirm("Discard unsaved changes and import a file?")) {
        return;
      }
      jsonUploadInput.click();
    });
    jsonUploadInput.addEventListener("change", () => {
      const f = jsonUploadInput.files && jsonUploadInput.files[0];
      jsonUploadInput.value = "";
      if (!f) return;
      const reader = new FileReader();
      reader.onload = () => {
        let text = typeof reader.result === "string" ? reader.result : "";
        if (!text.trim()) {
          showToast("File is empty", true);
          return;
        }
        if (!text.endsWith("\n")) {
          text += "\n";
        }
        jsonEditor.value = text;
        const id = jsonSelect.value;
        if (!id) return;
        parseError = null;
        try {
          ingestJsonText(text, id);
          setViewMode("form");
          setJsonDirty(true);
          updateJsonFileOptionLabel(id, entries.length);
          updateJsonMeta("Imported from " + f.name + " (unsaved — Save writes to " + selectedJsonDiskFilename() + ")");
          showToast("Imported " + f.name);
        } catch (err) {
          parseError = err;
          entries = [];
          jsonVisual.innerHTML =
            '<p class="parse-error">Cannot show form view: ' +
            escapeHtml(err.message) +
            ". Fix JSON in raw view or reload.</p>";
          setViewMode("raw");
          setJsonDirty(true);
          updateJsonMeta("Invalid JSON from file — raw editor", true);
          showToast(err.message, true);
        }
      };
      reader.onerror = () => showToast("Could not read file", true);
      reader.readAsText(f, "UTF-8");
    });
  }

  jsonSaveBtn.addEventListener("click", saveJsonFile);

  if (jsonViewFormBtn) {
    jsonViewFormBtn.addEventListener("click", () => {
      if (viewMode === "form") return;
      try {
        ingestJsonText(jsonEditor.value, jsonSelect.value);
        setViewMode("form");
        setJsonDirty(true);
        updateJsonMeta("Unsaved changes");
      } catch (e) {
        showToast(e.message, true);
      }
    });
  }

  if (jsonViewRawBtn) {
    jsonViewRawBtn.addEventListener("click", () => {
      if (viewMode === "raw") return;
      if (parseError) {
        setViewMode("raw");
        return;
      }
      try {
        syncTextareaFromEntries();
      } catch (e) {
        showToast(e.message, true);
        return;
      }
      setViewMode("raw");
    });
  }

  if (jsonAddGroupBtn) {
    jsonAddGroupBtn.addEventListener("click", () => {
      const fileId = jsonSelect.value;
      let e;
      if (fileId === "mood_groups") {
        e = { _uid: uid(), kind: "mood", name: "New group", tags: [] };
      } else {
        e = { _uid: uid(), kind: "rich", name: "New group", genres: [], filter: null, preferLiked: null, extra: {} };
      }
      entries.push(e);
      jsonVisual.appendChild(cardTemplate(e, fileId));
      applyFilter();
      setJsonDirty(true);
      updateJsonMeta("Unsaved changes");
    });
  }

  if (jsonFilterInput) {
    jsonFilterInput.addEventListener("input", applyFilter);
  }

  setJsonDirty(false);
  jsonSaveBtn.disabled = true;

  window.__ppgLoadJsonGroups = function () {
    loadJsonFile();
  };
  window.__ppgJsonIsDirty = function () {
    return jsonDirty;
  };
  window.__ppgJsonMarkClean = function () {
    setJsonDirty(false);
  };

  loadPlexGenresFromStorage();
  updatePlexGenresStatusUi();
  refreshGenrePickerControls();
  loadPlexMoodsFromStorage();
  updatePlexMoodsStatusUi();
  refreshMoodPickerControls();

  if (jsonSortGroupsBtn) {
    jsonSortGroupsBtn.disabled =
      viewMode !== "form" || !!parseError || entries.length < 2;
  }

  function sortGroupsAtoZ() {
    if (viewMode !== "form" || parseError || entries.length < 2) return;
    const collator = new Intl.Collator(undefined, {
      numeric: true,
      sensitivity: "base",
    });
    entries.sort((a, b) =>
      collator.compare(String(a.name).trim(), String(b.name).trim())
    );
    renderAll();
    setJsonDirty(true);
    updateJsonMeta("Groups sorted A–Z (unsaved)");
    showToast("Sorted alphabetically — save to update the JSON file.", false);
  }

  if (jsonSortGroupsBtn) {
    jsonSortGroupsBtn.addEventListener("click", sortGroupsAtoZ);
  }

  if (jsonFetchGenresBtn) {
    jsonFetchGenresBtn.addEventListener("click", async () => {
      jsonFetchGenresBtn.disabled = true;
      try {
        const r = await fetch("/api/plex/genres", { method: "POST" });
        const j = await r.json();
        if (!r.ok) {
          showToast(j.error || "Could not fetch genres", true);
          return;
        }
        const list = j.genres;
        if (!Array.isArray(list) || list.length === 0) {
          showToast("Plex returned no genres — check library or PLEX_MUSIC_SECTION in .env.", true);
          return;
        }
        applyPlexGenres(list, true);
        showToast("Loaded " + list.length + " genres from Plex.", false);
        if (entries.length) renderAll();
      } catch (err) {
        showToast(String(err), true);
      } finally {
        jsonFetchGenresBtn.disabled = false;
      }
    });
  }

  if (jsonFetchMoodsBtn) {
    jsonFetchMoodsBtn.addEventListener("click", async () => {
      jsonFetchMoodsBtn.disabled = true;
      try {
        const r = await fetch("/api/plex/moods", { method: "POST" });
        const j = await r.json();
        if (!r.ok) {
          showToast(j.error || "Could not fetch moods", true);
          return;
        }
        const list = j.moods;
        if (!Array.isArray(list) || list.length === 0) {
          showToast("Plex returned no moods — check library or PLEX_MUSIC_SECTION in .env.", true);
          return;
        }
        applyPlexMoods(list, true);
        showToast("Loaded " + list.length + " moods from Plex.", false);
        if (entries.length) renderAll();
      } catch (err) {
        showToast(String(err), true);
      } finally {
        jsonFetchMoodsBtn.disabled = false;
      }
    });
  }
})();
