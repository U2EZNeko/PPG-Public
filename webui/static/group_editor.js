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
  const jsonSelectVisibleBtn = document.getElementById("json-select-visible-groups");
  const jsonClearSelectionBtn = document.getElementById("json-clear-group-selection");
  const jsonDeleteSelectedBtn = document.getElementById("json-delete-selected-groups");
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

  /** Merged with ISO list from /static/ppg_country_picklist.json (Plex often uses shorter names). */
  const COUNTRY_PICKLIST_EXTRA = [
    "United States",
    "USA",
    "U.S.A.",
    "UK",
    "U.K.",
    "Great Britain",
    "England",
    "Scotland",
    "Wales",
    "Northern Ireland",
    "Russia",
    "South Korea",
    "North Korea",
  ];
  let countryPicklistReady = false;
  let countryPicklistPromise = null;

  function ensureCountryPicklistDatalist() {
    const dl = document.getElementById("ppg-country-picklist");
    if (!dl || dl.dataset.populated === "1") {
      countryPicklistReady = true;
      return Promise.resolve();
    }
    if (countryPicklistPromise) return countryPicklistPromise;
    countryPicklistPromise = fetch("/static/ppg_country_picklist.json")
      .then(function (r) {
        return r.ok ? r.json() : [];
      })
      .then(function (arr) {
        const base = Array.isArray(arr) ? arr.map(function (x) { return String(x); }) : [];
        const set = new Set(base);
        COUNTRY_PICKLIST_EXTRA.forEach(function (x) {
          if (x && x.trim()) set.add(x.trim());
        });
        const sorted = Array.from(set).sort(function (a, b) {
          return a.localeCompare(b, undefined, { sensitivity: "base" });
        });
        const frag = document.createDocumentFragment();
        for (let i = 0; i < sorted.length; i++) {
          const opt = document.createElement("option");
          opt.value = sorted[i];
          frag.appendChild(opt);
        }
        dl.appendChild(frag);
        dl.dataset.populated = "1";
        countryPicklistReady = true;
      })
      .catch(function () {
        countryPicklistReady = true;
      });
    return countryPicklistPromise;
  }

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
        let artistCountryInclude = [];
        let artistCountryFilterComplex = null;
        const acf = val.artist_country_filter;
        if (Array.isArray(acf)) {
          artistCountryInclude = acf.map((x) => String(x)).filter((s) => s.trim());
        } else if (acf && typeof acf === "object") {
          if (Array.isArray(acf.include)) {
            artistCountryInclude = acf.include.map((x) => String(x)).filter((s) => s.trim());
          }
          const rest = { ...acf };
          delete rest.include;
          if (Object.keys(rest).length > 0) {
            artistCountryFilterComplex = rest;
          }
        }
        const extra = { ...val };
        delete extra.genres;
        delete extra.release_date_filter;
        delete extra.prefer_liked_artists;
        delete extra.artist_country_filter;
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
        const hasCx =
          artistCountryFilterComplex &&
          typeof artistCountryFilterComplex === "object" &&
          Object.keys(artistCountryFilterComplex).length > 0;
        const _uiOpenCountry =
          artistCountryInclude.length > 0 || !!hasCx;
        out.push({
          _uid: uid(),
          kind: "rich",
          name,
          genres,
          filter,
          preferLiked,
          artistCountryInclude,
          artistCountryFilterComplex,
          _uiOpenCountry,
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
        const hasCountries =
          Array.isArray(e.artistCountryInclude) && e.artistCountryInclude.length > 0;
        const complex = e.artistCountryFilterComplex;
        const hasComplex = complex && typeof complex === "object" && Object.keys(complex).length > 0;
        if (hasCountries) {
          if (hasComplex) {
            o.artist_country_filter = { ...complex, include: e.artistCountryInclude.slice() };
          } else {
            o.artist_country_filter = e.artistCountryInclude.slice();
          }
        } else if (hasComplex) {
          o.artist_country_filter = { ...complex };
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
    refreshGroupJsonBulkToolbar();
  }

  function countSelectedGroupCards() {
    if (!jsonVisual) return 0;
    return jsonVisual.querySelectorAll(".group-card-select:checked").length;
  }

  function refreshGroupJsonBulkToolbar() {
    const formOk = viewMode === "form" && !parseError;
    const hasEntries = entries.length > 0;
    const filterTrim = (jsonFilterInput && jsonFilterInput.value || "").trim();
    const hasFilter = !!filterTrim;
    const nSel = countSelectedGroupCards();

    if (jsonSelectVisibleBtn) {
      jsonSelectVisibleBtn.disabled = !formOk || !hasEntries || !hasFilter;
    }
    if (jsonClearSelectionBtn) {
      jsonClearSelectionBtn.disabled = !formOk || !hasEntries || nSel === 0;
    }
    if (jsonDeleteSelectedBtn) {
      jsonDeleteSelectedBtn.disabled = !formOk || !hasEntries || nSel === 0;
      jsonDeleteSelectedBtn.textContent =
        nSel > 0 ? "Delete selection (" + nSel + ")" : "Delete selection";
    }
  }

  function selectVisibleGroupCards() {
    if (viewMode !== "form" || parseError || !entries.length) return;
    const filterTrim = (jsonFilterInput && jsonFilterInput.value || "").trim();
    if (!filterTrim) {
      showToast(
        "Type part of a group name in the filter first — Select visible only checks rows that match.",
        true
      );
      return;
    }
    let n = 0;
    jsonVisual.querySelectorAll(".group-card").forEach((card) => {
      if (card.style.display === "none") return;
      const cb = card.querySelector(".group-card-select");
      if (cb) {
        cb.checked = true;
        n++;
      }
    });
    refreshGroupJsonBulkToolbar();
    showToast(n ? "Selected " + n + " visible group(s)." : "No visible groups.", false);
  }

  function clearGroupCardSelection() {
    if (!jsonVisual) return;
    jsonVisual.querySelectorAll(".group-card-select").forEach((cb) => {
      cb.checked = false;
    });
    refreshGroupJsonBulkToolbar();
  }

  function deleteSelectedGroups() {
    if (viewMode !== "form" || parseError || !entries.length) return;
    const checked = jsonVisual.querySelectorAll(".group-card-select:checked");
    if (!checked.length) return;
    const uids = [];
    const names = [];
    checked.forEach((cb) => {
      const card = cb.closest(".group-card");
      if (!card || !card.dataset.uid) return;
      uids.push(card.dataset.uid);
      const ni = card.querySelector(".group-card-name");
      names.push(ni ? String(ni.value || "").trim() || card.dataset.uid : card.dataset.uid);
    });
    if (!uids.length) return;
    const preview =
      names.slice(0, 15).join(", ") + (names.length > 15 ? "… (+" + (names.length - 15) + " more)" : "");
    if (
      !window.confirm(
        "Delete " +
          uids.length +
          " selected group(s)?\n\n" +
          preview +
          "\n\nTip: Reload without saving if this is wrong."
      )
    ) {
      return;
    }
    const drop = new Set(uids);
    entries = entries.filter((e) => !drop.has(e._uid));
    const id = jsonSelect.value;
    renderAll();
    setJsonDirty(true);
    updateJsonMeta("Unsaved changes");
    if (id) updateJsonFileOptionLabel(id, entries.length);
    showToast(
      "Removed " + drop.size + " group(s). Save to update " + selectedJsonDiskFilename() + ".",
      false
    );
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
    refreshGroupJsonBulkToolbar();
    if (!isForm && !parseError) {
      try {
        syncTextareaFromEntries();
      } catch (e) {
        showToast(e.message, true);
      }
    }
  }

  function bindCard(wrap, e, fileId) {
    const selectCb = wrap.querySelector(".group-card-select");
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
      if (ev.target && ev.target.classList && ev.target.classList.contains("group-card-select")) return;
      toggleExpand();
    });

    if (selectCb) {
      selectCb.addEventListener("change", refreshGroupJsonBulkToolbar);
    }

    nameInput.addEventListener("input", () => {
      e.name = nameInput.value;
      setJsonDirty(true);
      updateJsonMeta("Unsaved changes");
    });

    const runMixBtn = wrap.querySelector(".group-card-run-one");
    if (runMixBtn) {
      runMixBtn.addEventListener("click", () => {
        const base = (nameInput.value || "").trim();
        if (!base) {
          showToast("Enter a group name first.", true);
          return;
        }
        const title = base + " Mix";
        if (typeof window.__ppgRegeneratePlaylist === "function") {
          window.__ppgRegeneratePlaylist(title, false);
        } else {
          showToast("Page not ready — refresh and try again.", true);
        }
      });
    }

    removeBtn.addEventListener("click", () => {
      if (!window.confirm('Delete group "' + e.name + '"?')) return;
      entries = entries.filter((x) => x._uid !== e._uid);
      wrap.remove();
      const id = jsonSelect.value;
      if (id) updateJsonFileOptionLabel(id, entries.length);
      if (jsonSortGroupsBtn) {
        jsonSortGroupsBtn.disabled =
          viewMode !== "form" || !!parseError || entries.length < 2;
      }
      refreshGroupJsonBulkToolbar();
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
      if (typeof e._uiOpenCountry !== "boolean") {
        const _hasC =
          Array.isArray(e.artistCountryInclude) && e.artistCountryInclude.length > 0;
        const _cx = e.artistCountryFilterComplex;
        const _hasCx =
          _cx && typeof _cx === "object" && Object.keys(_cx).length > 0;
        e._uiOpenCountry = !!(_hasC || _hasCx);
      }
      const condSel = wrap.querySelector(".filter-condition");
      const startL = wrap.querySelector(".filter-start-wrap");
      const endL = wrap.querySelector(".filter-end-wrap");
      const startIn = wrap.querySelector(".filter-start-input");
      const endIn = wrap.querySelector(".filter-end-input");
      const prefSel = wrap.querySelector(".prefer-liked");
      const filterPicker = wrap.querySelector(".filter-add-picker");
      const secRelease = wrap.querySelector(".filter-section-release");
      const secLiked = wrap.querySelector(".filter-section-liked");
      const secCountry = wrap.querySelector(".filter-section-country");

      function releaseFilterActive() {
        return !!(e.filter && String(e.filter.condition || "").trim());
      }
      function likedFilterActive() {
        return e.preferLiked === true || e.preferLiked === false;
      }
      function countryFilterActive() {
        const has =
          Array.isArray(e.artistCountryInclude) && e.artistCountryInclude.length > 0;
        const cx = e.artistCountryFilterComplex;
        const hasCx = cx && typeof cx === "object" && Object.keys(cx).length > 0;
        return !!e._uiOpenCountry || has || !!hasCx;
      }
      function syncRichFilterSections() {
        if (secRelease) secRelease.hidden = !releaseFilterActive();
        if (secLiked) secLiked.hidden = !likedFilterActive();
        if (secCountry) secCountry.hidden = !countryFilterActive();
        if (filterPicker) {
          const oRel = filterPicker.querySelector('option[value="release"]');
          const oLik = filterPicker.querySelector('option[value="liked"]');
          const oCnt = filterPicker.querySelector('option[value="country"]');
          if (oRel) oRel.disabled = releaseFilterActive();
          if (oLik) oLik.disabled = likedFilterActive();
          if (oCnt) oCnt.disabled = countryFilterActive();
        }
      }

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
      syncRichFilterSections();

      if (filterPicker) {
        filterPicker.addEventListener("change", function () {
          const v = filterPicker.value;
          if (!v) return;
          if (v === "release") {
            e.filter = { condition: "between", start_date: "", end_date: "" };
            condSel.value = "between";
            startIn.value = "";
            endIn.value = "";
            syncFilterVisibility();
          } else if (v === "liked") {
            e.preferLiked = true;
            prefSel.value = "true";
          } else if (v === "country") {
            if (!Array.isArray(e.artistCountryInclude)) e.artistCountryInclude = [];
            e._uiOpenCountry = true;
            renderCountryTags();
          }
          filterPicker.value = "";
          syncRichFilterSections();
          setJsonDirty(true);
          updateJsonMeta("Unsaved changes");
        });
      }

      const filtersWrap = wrap.querySelector(".rich-filters-wrap");
      if (filtersWrap) {
        filtersWrap.addEventListener("click", function (ev) {
          const btn = ev.target.closest(".filter-section-remove");
          if (!btn) return;
          const which = btn.getAttribute("data-filter");
          if (which === "release") {
            e.filter = null;
            condSel.value = "";
            startIn.value = "";
            endIn.value = "";
            syncFilterVisibility();
          } else if (which === "liked") {
            e.preferLiked = null;
            prefSel.value = "";
          } else if (which === "country") {
            e.artistCountryInclude = [];
            e.artistCountryFilterComplex = null;
            e._uiOpenCountry = false;
            renderCountryTags();
          }
          syncRichFilterSections();
          setJsonDirty(true);
          updateJsonMeta("Unsaved changes");
        });
      }

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
        syncRichFilterSections();
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
        syncRichFilterSections();
        setJsonDirty(true);
        updateJsonMeta("Unsaved changes");
      });

      const countryTagList = wrap.querySelector(".country-tag-list");
      const countryInput = wrap.querySelector(".country-input");
      const countryAddBtn = wrap.querySelector(".country-tag-add");
      if (!Array.isArray(e.artistCountryInclude)) e.artistCountryInclude = [];
      function renderCountryTags() {
        if (!countryTagList) return;
        countryTagList.innerHTML = "";
        e.artistCountryInclude.forEach(function (c, idx) {
          const span = document.createElement("span");
          span.className = "tag-chip";
          span.appendChild(document.createTextNode(c + " "));
          const x = document.createElement("button");
          x.type = "button";
          x.className = "tag-remove";
          x.setAttribute("aria-label", "Remove country");
          x.textContent = "×";
          x.addEventListener("click", function () {
            e.artistCountryInclude.splice(idx, 1);
            renderCountryTags();
            syncRichFilterSections();
            setJsonDirty(true);
            updateJsonMeta("Unsaved changes");
          });
          span.appendChild(x);
          countryTagList.appendChild(span);
        });
      }
      renderCountryTags();
      function addCountryTag() {
        if (!countryInput) return;
        const v = countryInput.value.trim();
        if (!v) return;
        if (e.artistCountryInclude.indexOf(v) !== -1) {
          showToast("That country is already in the list.", true);
          return;
        }
        e.artistCountryInclude.push(v);
        countryInput.value = "";
        renderCountryTags();
        syncRichFilterSections();
        setJsonDirty(true);
        updateJsonMeta("Unsaved changes");
      }
      if (countryAddBtn) countryAddBtn.addEventListener("click", addCountryTag);
      if (countryInput) {
        countryInput.addEventListener("keydown", function (ev) {
          if (ev.key === "Enter") {
            ev.preventDefault();
            addCountryTag();
          }
        });
      }
    }

    if (fileId !== "mood_groups" && e.kind === "simple") {
      const upBtn = wrap.querySelector(".promote-rich");
      if (upBtn) {
        upBtn.addEventListener("click", () => {
          e.kind = "rich";
          e.filter = null;
          e.preferLiked = null;
          e.artistCountryInclude = [];
          e.artistCountryFilterComplex = null;
          e._uiOpenCountry = false;
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

    const selectCb = document.createElement("input");
    selectCb.type = "checkbox";
    selectCb.className = "group-card-select";
    selectCb.title = "Select for bulk delete";
    selectCb.setAttribute(
      "aria-label",
      "Select group for bulk delete: " + String(e.name || "").replace(/["\\]/g, "")
    );

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
    removeBtn.textContent = "Delete";
    removeBtn.title = "Remove this group from the file (Save to write to disk)";
    removeBtn.setAttribute("aria-label", "Delete group");

    if (fileId === "named_genre_mix_playlists" || fileId === "mood_groups") {
      const runOneBtn = document.createElement("button");
      runOneBtn.type = "button";
      runOneBtn.className = "group-card-run-one";
      runOneBtn.textContent = "Run one";
      runOneBtn.title =
        "Build only this Plex playlist (name + \" Mix\"). The script reads the JSON file on disk — click Save first if you edited this group.";
      runOneBtn.setAttribute("aria-label", "Generate this mix playlist only");
      head.append(selectCb, expandBtn, nameInput, badge, runOneBtn, removeBtn);
    } else {
      head.append(selectCb, expandBtn, nameInput, badge, removeBtn);
    }

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
      fl.className = "rich-filters-wrap";
      fl.innerHTML =
        '<div class="filter-add-toolbar">' +
        '<span class="field-label">Filters</span>' +
        '<select class="filter-add-picker" aria-label="Add filter">' +
        '<option value="">Add filter…</option>' +
        '<option value="release">Release date filter</option>' +
        '<option value="liked">Liked artists</option>' +
        '<option value="country">Artist countries</option>' +
        "</select></div>" +
        '<div class="filter-section filter-section-release" hidden>' +
        '<div class="filter-section-head">' +
        '<span class="field-label">Release date filter</span>' +
        '<button type="button" class="filter-section-remove" data-filter="release">Remove</button></div>' +
        '<div class="filter-row">' +
        '<select class="filter-condition" aria-label="Filter condition">' +
        '<option value="">No filter</option>' +
        '<option value="before">Before year</option>' +
        '<option value="after">After year</option>' +
        '<option value="between">Between years</option>' +
        "</select>" +
        '<span class="filter-start-wrap"><label>Start <input type="text" class="filter-start-input" placeholder="e.g. 1990" /></label></span>' +
        '<span class="filter-end-wrap"><label>End <input type="text" class="filter-end-input" placeholder="e.g. 1999" /></label></span>' +
        "</div></div>" +
        '<div class="filter-section filter-section-liked" hidden>' +
        '<div class="filter-section-head">' +
        '<span class="field-label">Liked artists</span>' +
        '<button type="button" class="filter-section-remove" data-filter="liked">Remove</button></div>' +
        '<div class="prefer-row"><label>Preference <select class="prefer-liked">' +
        '<option value="">(not set)</option><option value="true">Prefer</option><option value="false">Do not prefer</option>' +
        "</select></label></div></div>" +
        '<div class="filter-section filter-section-country country-filter-section" hidden>' +
        '<div class="filter-section-head">' +
        '<span class="field-label">Artist countries</span>' +
        '<button type="button" class="filter-section-remove" data-filter="country">Remove</button></div>' +
        '<p class="country-filter-hint">Match <strong>any</strong> of these (OR). Same as <code>artist_country_filter</code> as a JSON array. You can type a name exactly as in Plex if it is not in the list.</p>' +
        '<div class="tag-list country-tag-list"></div>' +
        '<div class="tag-add-row country-add-row">' +
        '<input type="text" class="country-input" list="ppg-country-picklist" placeholder="Pick or type a country…" autocomplete="off" aria-label="Country to add" />' +
        '<button type="button" class="tag-add country-tag-add">Add</button>' +
        "</div></div>";
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
    refreshGroupJsonBulkToolbar();
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
      await ensureCountryPicklistDatalist();
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
        e = {
          _uid: uid(),
          kind: "rich",
          name: "New group",
          genres: [],
          filter: null,
          preferLiked: null,
          artistCountryInclude: [],
          artistCountryFilterComplex: null,
          _uiOpenCountry: false,
          extra: {},
        };
      }
      entries.push(e);
      jsonVisual.appendChild(cardTemplate(e, fileId));
      applyFilter();
      if (jsonSortGroupsBtn) {
        jsonSortGroupsBtn.disabled =
          viewMode !== "form" || !!parseError || entries.length < 2;
      }
      refreshGroupJsonBulkToolbar();
      setJsonDirty(true);
      updateJsonMeta("Unsaved changes");
    });
  }

  if (jsonSelectVisibleBtn) {
    jsonSelectVisibleBtn.addEventListener("click", selectVisibleGroupCards);
  }
  if (jsonClearSelectionBtn) {
    jsonClearSelectionBtn.addEventListener("click", clearGroupCardSelection);
  }
  if (jsonDeleteSelectedBtn) {
    jsonDeleteSelectedBtn.addEventListener("click", deleteSelectedGroups);
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
  refreshGroupJsonBulkToolbar();

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

  void ensureCountryPicklistDatalist();
})();
