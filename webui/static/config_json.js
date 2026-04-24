/**
 * Config JSON: Form or Raw for series_groups, genre_mixes, and movie_genre_mixes.
 */
(function () {
  "use strict";

  const jsonSelect = document.getElementById("json-file-select");
  const jsonEditor = document.getElementById("json-editor");
  const jsonVisual = document.getElementById("json-visual");
  const jsonMeta = document.getElementById("json-meta");
  const jsonReloadBtn = document.getElementById("json-reload");
  const jsonFormatBtn = document.getElementById("json-format");
  const jsonSaveBtn = document.getElementById("json-save");
  const jsonViewFormBtn = document.getElementById("json-view-form");
  const jsonViewRawBtn = document.getElementById("json-view-raw");
  const jsonSeriesToolbar = document.getElementById("json-series-toolbar");
  const jsonGroupFilter = document.getElementById("json-group-filter");
  const plexSeriesStatus = document.getElementById("plex-tv-shows-status");
  const jsonSortGroupsBtn = document.getElementById("json-sort-groups");
  const jsonAddGroupBtn = document.getElementById("json-add-group");
  const plexSeriesDatalist = document.getElementById("plex-tv-datalist");
  const plexMoviesDatalist = document.getElementById("plex-movies-datalist");
  const plexTvGenresDatalist = document.getElementById("plex-tv-genres-datalist");
  const plexMovieGenresDatalist = document.getElementById("plex-movie-genres-datalist");
  const jsonViewToggle = document.getElementById("json-view-toggle");
  const jsonFetchAllShows = document.getElementById("json-fetch-all-shows");
  const jsonFetchAllMovies = document.getElementById("json-fetch-all-movies");
  const jsonFetchAllTvGenres = document.getElementById("json-fetch-all-tv-genres");
  const jsonFetchAllMovieGenres = document.getElementById("json-fetch-all-movie-genres");
  const jsonDownloadBtn = document.getElementById("json-download");
  const jsonUploadBtn = document.getElementById("json-upload");
  const jsonUploadInput = document.getElementById("json-upload-input");
  const plexTopCacheStatus = document.getElementById("json-plex-fetch-cache-status");
  const toastEl = document.getElementById("toast");

  if (!jsonSelect || !jsonEditor) return;

  const PLEX_SERIES_STORAGE_KEY = "pvpg_webui_plex_tv_series_titles_v1";
  const PLEX_MOVIES_STORAGE_KEY = "pvpg_webui_plex_movie_titles_v1";
  const PLEX_TV_GENRES_STORAGE_KEY = "pvpg_webui_plex_tv_genres_v1";
  const PLEX_MOVIE_GENRES_STORAGE_KEY = "pvpg_webui_plex_movie_genres_v1";

  let viewMode = "raw";
  let jsonDirty = false;
  let jsonLoading = false;
  let jsonSelectLockedValue = jsonSelect.value;
  let baselineText = "";

  let seriesEntries = [];
  let formParseError = null;
  let plexTitles = [];
  let plexMovieTitles = [];
  let plexTvGenres = [];
  let plexMovieGenres = [];
  let plexFetchBusy = false;
  let mixEntries = [];

  function getJsonFileId() {
    return jsonSelect && jsonSelect.value ? jsonSelect.value : "";
  }
  function isSeriesGroups() {
    return getJsonFileId() === "series_groups";
  }
  function isGenreMixesFile() {
    return getJsonFileId() === "genre_mixes";
  }
  function isMovieMixesFile() {
    return getJsonFileId() === "movie_genre_mixes";
  }
  function isSeriesFile() {
    return isSeriesGroups();
  }
  function supportsFormEditor() {
    return isSeriesGroups() || isGenreMixesFile() || isMovieMixesFile();
  }

  function currentMixGenreSourceAndChoices() {
    if (isMovieMixesFile()) {
      return { source: "movie", choices: plexMovieGenres.slice() };
    }
    if (isGenreMixesFile()) {
      return { source: "tv", choices: plexTvGenres.slice() };
    }
    return { source: "", choices: [] };
  }

  function populateMixGenrePicker(selectEl, kindLabel, selectedList) {
    if (!selectEl) return;
    const src = currentMixGenreSourceAndChoices();
    const used = new Set((selectedList || []).map(String));
    const choices = src.choices.filter(function (g) {
      return !used.has(String(g));
    });
    const totalCached = src.choices.length;
    const srcLabel = src.source === "movie" ? "movie" : src.source === "tv" ? "TV show" : "";
    selectEl.innerHTML = "";
    const opt0 = document.createElement("option");
    opt0.value = "";
    opt0.textContent = choices.length
      ? "— Select " +
        kindLabel +
        " (" +
        choices.length +
        " available of " +
        totalCached +
        " " +
        srcLabel +
        " genres cached) —"
      : totalCached
      ? "— All cached " + srcLabel + " genres already added —"
      : "— Fetch " + (srcLabel || "library") + " genres first from toolbar —";
    selectEl.appendChild(opt0);
    for (let i = 0; i < choices.length; i++) {
      const g = choices[i];
      const o = document.createElement("option");
      o.value = g;
      o.textContent = g;
      selectEl.appendChild(o);
    }
  }

  function reapplyAllMixGenreDatalistIds() {
    if (!jsonVisual) return;
    const cards = jsonVisual.querySelectorAll(".group-card--mix");
    for (let i = 0; i < cards.length; i++) {
      const card = cards[i];
      const uidVal = card.dataset ? card.dataset.uid : "";
      const ent = mixEntries.find(function (x) {
        return x && x._uid === uidVal;
      });
      const inc = ent && Array.isArray(ent.genres) ? ent.genres : [];
      const exc = ent && Array.isArray(ent.excluded_genres) ? ent.excluded_genres : [];
      populateMixGenrePicker(
        card.querySelector("select.tag-input-genres"),
        "genre to include",
        inc
      );
      populateMixGenrePicker(
        card.querySelector("select.tag-input-excl"),
        "genre to exclude",
        exc
      );
    }
  }

  function setMixCardGenreListAttrsOnWrap(wrap) {
    if (!wrap) return;
    const uidVal = wrap.dataset ? wrap.dataset.uid : "";
    const ent = mixEntries.find(function (x) {
      return x && x._uid === uidVal;
    });
    const inc = ent && Array.isArray(ent.genres) ? ent.genres : [];
    const exc = ent && Array.isArray(ent.excluded_genres) ? ent.excluded_genres : [];
    populateMixGenrePicker(
      wrap.querySelector(".tag-input-genres"),
      "genre to include",
      inc
    );
    populateMixGenrePicker(
      wrap.querySelector(".tag-input-excl"),
      "genre to exclude",
      exc
    );
  }

  function showToast(msg, isErr) {
    if (typeof window.__pvpgShowToast === "function") {
      window.__pvpgShowToast(msg, isErr);
    } else if (toastEl) {
      toastEl.textContent = msg;
      toastEl.classList.add("show");
      toastEl.classList.toggle("err", !!isErr);
      clearTimeout(showToast._t);
      showToast._t = setTimeout(function () {
        toastEl.classList.remove("show");
      }, 4500);
    }
  }

  function openDarkSelectListbox(selectEl) {
    if (!selectEl) return;
    const n = Math.max(6, Math.min(12, selectEl.options ? selectEl.options.length : 6));
    selectEl.size = n;
    selectEl.dataset.open = "1";
  }

  function closeDarkSelectListbox(selectEl) {
    if (!selectEl) return;
    selectEl.size = 1;
    selectEl.dataset.open = "0";
  }

  function wireDarkSelectListbox(selectEl) {
    if (!selectEl || selectEl.dataset.darkListboxWired === "1") return;
    selectEl.dataset.darkListboxWired = "1";
    closeDarkSelectListbox(selectEl);
    selectEl.addEventListener("mousedown", function (ev) {
      if (selectEl.dataset.open === "1") return;
      ev.preventDefault();
      openDarkSelectListbox(selectEl);
    });
    selectEl.addEventListener("keydown", function (ev) {
      if (ev.key === " " || ev.key === "Enter" || ev.key === "ArrowDown") {
        if (selectEl.dataset.open !== "1") {
          ev.preventDefault();
          openDarkSelectListbox(selectEl);
        }
      } else if (ev.key === "Escape") {
        closeDarkSelectListbox(selectEl);
      }
    });
    selectEl.addEventListener("change", function () {
      closeDarkSelectListbox(selectEl);
    });
    selectEl.addEventListener("blur", function () {
      window.setTimeout(function () {
        closeDarkSelectListbox(selectEl);
      }, 80);
    });
  }

  function wireDarkListboxesInContainer(rootEl) {
    if (!rootEl) return;
    rootEl.querySelectorAll("select").forEach(function (sel) {
      wireDarkSelectListbox(sel);
    });
  }

  function uid() {
    return window.crypto && crypto.randomUUID
      ? crypto.randomUUID()
      : String(Date.now()) + Math.random();
  }

  function setJsonDirty(on) {
    jsonDirty = !!on;
    if (jsonSaveBtn) jsonSaveBtn.disabled = jsonLoading || !jsonDirty;
  }

  function updateJsonMeta(text, isWarn) {
    if (!jsonMeta) return;
    jsonMeta.textContent = text || "";
    jsonMeta.classList.toggle("warn", !!isWarn);
  }

  function updateFileOptionKeyCount() {
    const id = jsonSelect.value;
    if (!id) return;
    let n = 0;
    if (id === "series_groups" && !formParseError && viewMode === "form") {
      n = seriesEntries.length;
    } else if (
      (id === "genre_mixes" || id === "movie_genre_mixes") &&
      !formParseError &&
      viewMode === "form"
    ) {
      n = mixEntries.length;
    } else {
      try {
        const obj = JSON.parse(jsonEditor.value || "{}");
        if (obj && typeof obj === "object" && !Array.isArray(obj)) n = Object.keys(obj).length;
      } catch (e) {
        return;
      }
    }
    const opt = Array.from(jsonSelect.options).find(function (o) {
      return o.value === id;
    });
    if (!opt) return;
    const file = opt.getAttribute("data-file") || "";
    const label = opt.getAttribute("data-label") || id;
    const g = n === 1 ? "key" : "keys";
    opt.textContent = label + " — " + file + " (" + n + " " + g + ")";
  }

  function parseObjectJsonFromText(text) {
    const t = (text || "").trim();
    if (!t) {
      return { ok: true, value: {} };
    }
    try {
      const parsed = JSON.parse(t);
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
        return { ok: false, value: null };
      }
      return { ok: true, value: parsed };
    } catch (e) {
      return { ok: false, value: null };
    }
  }

  /** PvPG-Series: per-show season_filter as dict of range objects or single season numbers. */
  function canRepresentSeasonFilter(sf) {
    if (sf == null) return true;
    if (typeof sf !== "object" || Array.isArray(sf)) return false;
    const keys = Object.keys(sf);
    for (let i = 0; i < keys.length; i++) {
      const v = sf[keys[i]];
      if (v == null) return false;
      if (Array.isArray(v)) return false;
      if (typeof v === "number" && isFinite(v)) continue;
      if (typeof v === "object") {
        if (v.start == null && v.end == null) return false;
        if (v.start != null && !isFinite(Number(v.start))) return false;
        if (v.end != null && !isFinite(Number(v.end))) return false;
        continue;
      }
      return false;
    }
    return true;
  }

  function filtersWithoutSeason(f) {
    const o = Object.assign({}, f || {});
    delete o.season_filter;
    delete o.genre_filter;
    delete o.excluded_genres;
    return o;
  }

  function normalizeGenreFilterFromText(raw) {
    const text = String(raw || "").trim();
    if (!text) return null;
    const parts = text
      .split(",")
      .map(function (s) {
        return s.trim();
      })
      .filter(function (s) {
        return !!s;
      });
    if (!parts.length) return null;
    if (parts.length === 1) return parts[0];
    return parts;
  }

  function genreFilterToText(v) {
    if (v == null) return "";
    if (Array.isArray(v)) return v.map(String).join(", ");
    return String(v);
  }

  function normalizeExcludedGenresFromText(raw) {
    return normalizeGenreFilterFromText(raw);
  }

  function excludedGenresToText(v) {
    return genreFilterToText(v);
  }

  function genreFilterValueToArray(v) {
    if (v == null) return [];
    const raw = Array.isArray(v) ? v.map(String) : String(v).split(",");
    const out = [];
    raw.forEach(function (x) {
      const t = String(x || "").trim();
      if (!t) return;
      if (out.indexOf(t) === -1) out.push(t);
    });
    return out;
  }

  function seasonFilterToRows(sf) {
    if (!sf || typeof sf !== "object" || Array.isArray(sf)) return [];
    return Object.keys(sf).map(function (k) {
      const v = sf[k];
      if (typeof v === "number" && isFinite(v)) {
        return { show: k, start: v, end: v };
      }
      if (v && typeof v === "object" && !Array.isArray(v)) {
        return {
          show: k,
          start: v.start != null ? Number(v.start) : 1,
          end: v.end != null ? Number(v.end) : 999,
        };
      }
      return { show: k, start: 1, end: 999 };
    });
  }

  function readSeasonFilterRowsFromEl(rowsEl) {
    const out = {};
    if (!rowsEl) return out;
    const rows = rowsEl.querySelectorAll(".season-filter-row");
    for (let r = 0; r < rows.length; r++) {
      const row = rows[r];
      const sel = row.querySelector(".season-filter-show");
      const sIn = row.querySelector(".season-filter-start");
      const eIn = row.querySelector(".season-filter-end");
      const show = sel && sel.value ? String(sel.value).trim() : "";
      if (!show) continue;
      const s = sIn && sIn.value !== "" ? parseInt(String(sIn.value), 10) : 1;
      const e = eIn && eIn.value !== "" ? parseInt(String(eIn.value), 10) : 999;
      out[show] = { start: isNaN(s) ? 1 : s, end: isNaN(e) ? 999 : e };
    }
    return out;
  }

  function fillShowSelectFromSeries(sel, series, selected) {
    if (!sel) return;
    const cur = selected != null ? String(selected) : "";
    sel.innerHTML = "";
    const pick = document.createElement("option");
    pick.value = "";
    pick.textContent = "— pick show —";
    sel.appendChild(pick);
    for (let i = 0; i < series.length; i++) {
      const t = String(series[i]);
      const opt = document.createElement("option");
      opt.value = t;
      opt.textContent = t;
      sel.appendChild(opt);
    }
    if (cur && series.indexOf(cur) === -1) {
      const opt = document.createElement("option");
      opt.value = cur;
      opt.textContent = cur + " (not in list)";
      sel.appendChild(opt);
    }
    if (cur) {
      sel.value = cur;
    } else {
      sel.value = "";
    }
  }

  /** Read filter textareas into entries. Invalid fields keep prior values; returns false if any field is invalid. */
  function readSeriesFilterTextareasIntoEntries() {
    if (!jsonVisual) {
      return true;
    }
    var allValid = true;
    const cards = jsonVisual.querySelectorAll(".group-card");
    for (let i = 0; i < cards.length; i++) {
      const card = cards[i];
      const ent = seriesEntries.find(function (x) {
        return x._uid === card.dataset.uid;
      });
      if (!ent) {
        continue;
      }
      const spot = card.querySelector(".group-use-spotify-poster");
      if (spot) {
        ent.use_spotify_posters = !!spot.checked;
      }
      const genreInp = card.querySelector("input.group-genre-filter");
      const genreVal = normalizeGenreFilterFromText(genreInp ? genreInp.value : "");
      const excludedInp = card.querySelector("input.group-excluded-genres");
      const excludedVal = normalizeExcludedGenresFromText(
        excludedInp ? excludedInp.value : ""
      );
      const advTa = card.querySelector("textarea.group-filters-advanced");
      if (advTa) {
        const r = parseObjectJsonFromText(advTa.value);
        if (r.ok) {
          ent.filters = r.value;
          if (genreVal == null) {
            delete ent.filters.genre_filter;
          } else {
            ent.filters.genre_filter = genreVal;
          }
          if (excludedVal == null) {
            delete ent.filters.excluded_genres;
          } else {
            ent.filters.excluded_genres = excludedVal;
          }
          advTa.classList.remove("invalid");
        } else {
          allValid = false;
          advTa.classList.add("invalid");
        }
        continue;
      }
      const rowsEl = card.querySelector(".season-filter-rows");
      const exTa = card.querySelector("textarea.group-filters-extras");
      if (rowsEl && exTa) {
        const re = parseObjectJsonFromText(exTa.value);
        if (!re.ok) {
          allValid = false;
          exTa.classList.add("invalid");
          continue;
        }
        exTa.classList.remove("invalid");
        const sf = readSeasonFilterRowsFromEl(rowsEl);
        const merged = Object.assign({}, re.value);
        if (Object.keys(sf).length) {
          merged.season_filter = sf;
        } else {
          delete merged.season_filter;
        }
        if (genreVal == null) {
          delete merged.genre_filter;
        } else {
          merged.genre_filter = genreVal;
        }
        if (excludedVal == null) {
          delete merged.excluded_genres;
        } else {
          merged.excluded_genres = excludedVal;
        }
        ent.filters = merged;
        continue;
      }
      const ta = card.querySelector(".group-filters-json");
      if (ta) {
        const r = parseObjectJsonFromText(ta.value);
        if (r.ok) {
          ent.filters = r.value;
          if (genreVal == null) {
            delete ent.filters.genre_filter;
          } else {
            ent.filters.genre_filter = genreVal;
          }
          if (excludedVal == null) {
            delete ent.filters.excluded_genres;
          } else {
            ent.filters.excluded_genres = excludedVal;
          }
          ta.classList.remove("invalid");
        } else {
          allValid = false;
          ta.classList.add("invalid");
        }
      }
    }
    return allValid;
  }

  function syncTextareaFromSeries() {
    readSeriesFilterTextareasIntoEntries();
    const obj = serializeSeries();
    jsonEditor.value = JSON.stringify(obj, null, 2) + "\n";
  }

  function parseSeriesFromObject(root) {
    if (!root || typeof root !== "object" || Array.isArray(root)) {
      throw new Error("Root must be a JSON object");
    }
    const out = [];
    const keys = Object.keys(root);
    for (let i = 0; i < keys.length; i++) {
      const name = keys[i];
      const val = root[name];
      if (!val || typeof val !== "object" || Array.isArray(val)) {
        throw new Error('Group "' + name + '" must be an object with a "series" array');
      }
      if (!Array.isArray(val.series)) {
        throw new Error('Group "' + name + '" must have a "series" array');
      }
      var useSpotify = true;
      if (Object.prototype.hasOwnProperty.call(val, "use_spotify_posters")) {
        useSpotify = !!val.use_spotify_posters;
      }
      let filters = {};
      try {
        const raw = JSON.parse(JSON.stringify(val));
        delete raw.series;
        delete raw.use_spotify_posters;
        filters = raw && typeof raw === "object" && !Array.isArray(raw) ? raw : {};
      } catch (e) {
        filters = {};
      }
      out.push({
        _uid: uid(),
        name: String(name),
        series: val.series.map(function (x) {
          return String(x);
        }),
        filters: filters,
        use_spotify_posters: useSpotify,
      });
    }
    return out;
  }

  function serializeSeries() {
    const o = {};
    for (let i = 0; i < seriesEntries.length; i++) {
      const e = seriesEntries[i];
      const n = (e.name || "").trim();
      if (!n) continue;
      if (Object.prototype.hasOwnProperty.call(o, n)) {
        throw new Error('Duplicate group name: "' + n + '"');
      }
      const row = { series: e.series.slice() };
      if (e.use_spotify_posters === false) {
        row.use_spotify_posters = false;
      }
      const f = e.filters;
      if (f && typeof f === "object" && !Array.isArray(f)) {
        const fk = Object.keys(f);
        for (let j = 0; j < fk.length; j++) {
          const k = fk[j];
          row[k] = f[k];
        }
      }
      o[n] = row;
    }
    return o;
  }

  function defaultRelease() {
    return { mode: "none", year: 2000, startYear: 1990, endYear: 2025 };
  }

  function numOr(v, d) {
    const n = parseInt(String(v), 10);
    return isNaN(n) ? d : n;
  }

  function releaseFromFilter(filter) {
    if (!filter || typeof filter !== "object") return defaultRelease();
    const c = filter.condition;
    if (c === "after") {
      return { mode: "after", year: numOr(filter.year, 2000), startYear: 1990, endYear: 2025 };
    }
    if (c === "before") {
      return { mode: "before", year: numOr(filter.year, 2000), startYear: 1990, endYear: 2025 };
    }
    if (c === "between") {
      return {
        mode: "between",
        year: 2000,
        startYear: numOr(filter.start_year, 1990),
        endYear: numOr(filter.end_year, 2025),
      };
    }
    return defaultRelease();
  }

  function filterFromRelease(rel) {
    if (!rel || rel.mode === "none") return null;
    if (rel.mode === "after") return { condition: "after", year: numOr(rel.year, 2000) };
    if (rel.mode === "before") return { condition: "before", year: numOr(rel.year, 2000) };
    if (rel.mode === "between") {
      return {
        condition: "between",
        start_year: numOr(rel.startYear, 1990),
        end_year: numOr(rel.endYear, 2025),
      };
    }
    return null;
  }

  function parseMixFromObject(root) {
    if (!root || typeof root !== "object" || Array.isArray(root)) {
      throw new Error("Root must be a JSON object");
    }
    const out = [];
    const keys = Object.keys(root);
    for (let i = 0; i < keys.length; i++) {
      const name = keys[i];
      const val = root[name];
      if (!val || typeof val !== "object" || Array.isArray(val)) {
        throw new Error('Mix "' + name + '" must be an object');
      }
      if (val.series && Array.isArray(val.series) && !Array.isArray(val.genres)) {
        throw new Error(
          'Mix "' +
            name +
            '" is series-based, not genre-based. Use Raw JSON, or add a "genres" array.'
        );
      }
      if (!Array.isArray(val.genres)) {
        throw new Error('Mix "' + name + '" must have a "genres" array');
      }
      if (val.excluded_genres != null && !Array.isArray(val.excluded_genres)) {
        throw new Error('Mix "' + name + '": excluded_genres must be an array');
      }
      const g = val.genres.map(function (x) {
        return String(x);
      });
      const ex = (val.excluded_genres || []).map(function (x) {
        return String(x);
      });
      const ws = val.watched_status;
      if (ws != null && ["any", "watched", "unwatched"].indexOf(String(ws)) === -1) {
        throw new Error('Mix "' + name + '": invalid watched_status');
      }
      var maxMovies = null;
      if (val.max_movies != null) {
        const nm = parseInt(String(val.max_movies), 10);
        if (!isNaN(nm) && nm >= 1) {
          maxMovies = nm;
        }
      }
      var useSpotify = true;
      if (Object.prototype.hasOwnProperty.call(val, "use_spotify_posters")) {
        useSpotify = !!val.use_spotify_posters;
      }
      const knownMix = {
        genres: 1,
        excluded_genres: 1,
        release_date_filter: 1,
        watched_status: 1,
        max_movies: 1,
        use_spotify_posters: 1,
      };
      const mixExtra = {};
      Object.keys(val).forEach(function (k) {
        if (!Object.prototype.hasOwnProperty.call(knownMix, k)) {
          mixExtra[k] = val[k];
        }
      });
      out.push({
        _uid: uid(),
        name: String(name),
        genres: g,
        excluded_genres: ex,
        _release: releaseFromFilter(val.release_date_filter),
        watched_status: ws != null ? String(ws) : "any",
        max_movies: maxMovies,
        mixExtra: mixExtra,
        use_spotify_posters: useSpotify,
      });
    }
    return out;
  }

  function serializeMix() {
    const o = {};
    for (let i = 0; i < mixEntries.length; i++) {
      const e = mixEntries[i];
      const n = (e.name || "").trim();
      if (!n) continue;
      if (Object.prototype.hasOwnProperty.call(o, n)) {
        throw new Error('Duplicate mix name: "' + n + '"');
      }
      const row = {
        genres: e.genres.slice(),
        excluded_genres: (e.excluded_genres || []).slice(),
        watched_status: e.watched_status || "any",
      };
      const f = filterFromRelease(e._release);
      if (f) {
        row.release_date_filter = f;
      }
      if (isMovieMixesFile() && e.max_movies != null) {
        const nm = parseInt(String(e.max_movies), 10);
        if (!isNaN(nm) && nm >= 1) {
          row.max_movies = nm;
        }
      }
      if (e.mixExtra && typeof e.mixExtra === "object") {
        Object.keys(e.mixExtra).forEach(function (k) {
          if (!Object.prototype.hasOwnProperty.call(row, k)) {
            row[k] = e.mixExtra[k];
          }
        });
      }
      if (e.use_spotify_posters === false) {
        row.use_spotify_posters = false;
      }
      o[n] = row;
    }
    return o;
  }

  function readMixExtraAndMaxFromDom() {
    if (!jsonVisual) {
      return true;
    }
    var allValid = true;
    const cards = jsonVisual.querySelectorAll(".group-card--mix");
    for (let i = 0; i < cards.length; i++) {
      const card = cards[i];
      const ent = mixEntries.find(function (x) {
        return x._uid === card.dataset.uid;
      });
      if (!ent) {
        continue;
      }
      const mspot = card.querySelector(".mix-use-spotify-poster");
      if (mspot) {
        ent.use_spotify_posters = !!mspot.checked;
      }
      const ta = card.querySelector(".mix-extra-json");
      if (ta) {
        const r = parseObjectJsonFromText(ta.value);
        if (r.ok) {
          ent.mixExtra = r.value;
          ta.classList.remove("invalid");
        } else {
          allValid = false;
          ta.classList.add("invalid");
        }
      }
      const num = card.querySelector(".mix-max-movies");
      if (num) {
        const t = (num.value || "").trim();
        if (!t) {
          ent.max_movies = null;
        } else {
          const n = parseInt(t, 10);
          ent.max_movies = isNaN(n) || n < 1 ? null : n;
        }
      }
    }
    return allValid;
  }

  function syncTextareaFromMix() {
    readMixExtraAndMaxFromDom();
    const obj = serializeMix();
    jsonEditor.value = JSON.stringify(obj, null, 2) + "\n";
  }

  function applyMixEntries(ent, sourceLabel) {
    seriesEntries = [];
    mixEntries = ent;
    formParseError = null;
    renderMixForm();
    syncTextareaFromMix();
    setJsonDirty(false);
    baselineText = jsonEditor.value;
    if (sourceLabel) updateJsonMeta(sourceLabel);
    updateFileOptionKeyCount();
  }

  function tryIngestMixText(text) {
    const trimmed = (text || "").trim() || "{}";
    const obj = JSON.parse(trimmed);
    const ent = parseMixFromObject(obj);
    applyMixEntries(ent, null);
  }

  function updateMixReleaseVisibility(wrap) {
    const modeSel = wrap.querySelector(".mix-release-mode");
    if (!modeSel) return;
    const mode = modeSel.value;
    const single = wrap.querySelector(".mix-rel-single");
    const between = wrap.querySelector(".mix-rel-between");
    if (single) single.hidden = mode !== "after" && mode !== "before";
    if (between) between.hidden = mode !== "between";
  }

  function bindMixCard(wrap, entry) {
    const expandBtn = wrap.querySelector(".group-card-expand");
    const head = wrap.querySelector(".group-card-head");
    const body = wrap.querySelector(".group-card-body");
    const nameInput = wrap.querySelector(".group-card-name");
    const badge = wrap.querySelector(".group-card-badge");
    const removeBtn = wrap.querySelector(".group-card-remove");
    const modeSel = wrap.querySelector(".mix-release-mode");
    const yearInput = wrap.querySelector(".mix-year");
    const startInput = wrap.querySelector(".mix-year-start");
    const endInput = wrap.querySelector(".mix-year-end");
    const watchSel = wrap.querySelector(".mix-watched");
    const gTags = wrap.querySelector(".tag-list-genres");
    const gInput = wrap.querySelector(".tag-input-genres");
    const gAdd = wrap.querySelector(".tag-add-genres");
    const xTags = wrap.querySelector(".tag-list-excl");
    const xInput = wrap.querySelector(".tag-input-excl");
    const xAdd = wrap.querySelector(".tag-add-excl");

    if (!entry.mixExtra) {
      entry.mixExtra = {};
    }
    if (entry.use_spotify_posters === undefined) {
      entry.use_spotify_posters = true;
    }
    const mixSpotCb = wrap.querySelector(".mix-use-spotify-poster");
    if (mixSpotCb) {
      mixSpotCb.checked = entry.use_spotify_posters !== false;
      mixSpotCb.addEventListener("change", function () {
        entry.use_spotify_posters = mixSpotCb.checked;
        refreshBadge();
        markDirty();
      });
    }
    function refreshBadge() {
      var base =
        entry.genres.length + " genres · " + entry.excluded_genres.length + " excluded";
      if (isMovieMixesFile() && entry.max_movies != null) {
        base += " · cap " + entry.max_movies;
      }
      const nx = entry.mixExtra && Object.keys(entry.mixExtra).length;
      if (nx) {
        base += " · +" + nx + " other";
      }
      if (entry.use_spotify_posters === false) {
        base += " · no poster";
      }
      badge.textContent = base;
    }
    refreshBadge();

    function markDirty() {
      if (modeSel) {
        entry._release.mode = modeSel.value;
      }
      if (entry._release.mode === "after" || entry._release.mode === "before") {
        if (yearInput) {
          entry._release.year = numOr(yearInput.value, entry._release.year);
        }
      } else if (entry._release.mode === "between") {
        if (startInput) {
          entry._release.startYear = numOr(startInput.value, entry._release.startYear);
        }
        if (endInput) {
          entry._release.endYear = numOr(endInput.value, entry._release.endYear);
        }
      }
      if (watchSel) {
        entry.watched_status = watchSel.value;
      }
      syncTextareaFromMix();
      setJsonDirty(jsonEditor.value !== baselineText);
      updateJsonMeta("Unsaved changes");
      updateFileOptionKeyCount();
    }

    function toggleExpand() {
      const open = !body.hidden;
      body.hidden = open;
      expandBtn.textContent = open ? "▶" : "▼";
      expandBtn.setAttribute("aria-expanded", open ? "false" : "true");
    }
    expandBtn.addEventListener("click", toggleExpand);
    head.addEventListener("dblclick", function (ev) {
      if (ev.target === nameInput) return;
      toggleExpand();
    });
    nameInput.addEventListener("input", function () {
      entry.name = nameInput.value;
      markDirty();
    });
    removeBtn.addEventListener("click", function () {
      if (!window.confirm('Remove mix "' + entry.name + '"?')) return;
      mixEntries = mixEntries.filter(function (x) {
        return x._uid !== entry._uid;
      });
      wrap.remove();
      setJsonDirty(true);
      updateJsonMeta("Unsaved changes");
      updateFileOptionKeyCount();
      syncTextareaFromMix();
    });
    function renderG() {
      renderTags(gTags, entry.genres, function () {
        refreshBadge();
        markDirty();
      });
    }
    function renderX() {
      renderTags(xTags, entry.excluded_genres, function () {
        refreshBadge();
        markDirty();
      });
    }
    renderG();
    renderX();
    setMixCardGenreListAttrsOnWrap(wrap);
    wireDarkSelectListbox(gInput);
    wireDarkSelectListbox(xInput);
    function addG() {
      const v = (gInput && gInput.value && gInput.value.trim()) || "";
      if (!v) return;
      if (entry.genres.indexOf(v) !== -1) {
        showToast("Already listed.", true);
        return;
      }
      entry.genres.push(v);
      gInput.value = "";
      renderG();
      refreshBadge();
      markDirty();
    }
    function addX() {
      const v = (xInput && xInput.value && xInput.value.trim()) || "";
      if (!v) return;
      if (entry.excluded_genres.indexOf(v) !== -1) {
        showToast("Already listed.", true);
        return;
      }
      entry.excluded_genres.push(v);
      xInput.value = "";
      renderX();
      refreshBadge();
      markDirty();
    }
    gAdd.addEventListener("click", addG);
    gInput.addEventListener("change", function () {
      addG();
      closeDarkSelectListbox(gInput);
    });
    xAdd.addEventListener("click", addX);
    xInput.addEventListener("change", function () {
      addX();
      closeDarkSelectListbox(xInput);
    });
    if (modeSel) {
      modeSel.value = entry._release.mode;
      modeSel.addEventListener("change", function () {
        entry._release.mode = modeSel.value;
        updateMixReleaseVisibility(wrap);
        markDirty();
      });
    }
    if (yearInput) {
      yearInput.value = String(entry._release.year != null ? entry._release.year : 2000);
      yearInput.addEventListener("change", markDirty);
      yearInput.addEventListener("input", markDirty);
    }
    if (startInput) {
      startInput.value = String(
        entry._release.startYear != null ? entry._release.startYear : 1990
      );
      startInput.addEventListener("change", markDirty);
      startInput.addEventListener("input", markDirty);
    }
    if (endInput) {
      endInput.value = String(
        entry._release.endYear != null ? entry._release.endYear : 2025
      );
      endInput.addEventListener("change", markDirty);
      endInput.addEventListener("input", markDirty);
    }
    if (watchSel) {
      watchSel.value = entry.watched_status || "any";
      watchSel.addEventListener("change", markDirty);
    }
    const maxInp = wrap.querySelector(".mix-max-movies");
    if (maxInp) {
      maxInp.value =
        entry.max_movies != null && entry.max_movies !== "" ? String(entry.max_movies) : "";
      maxInp.addEventListener("input", function () {
        const t = (maxInp.value || "").trim();
        if (!t) {
          entry.max_movies = null;
        } else {
          const n = parseInt(t, 10);
          entry.max_movies = isNaN(n) || n < 1 ? null : n;
        }
        refreshBadge();
        markDirty();
      });
    }
    const extraTa = wrap.querySelector(".mix-extra-json");
    if (extraTa) {
      extraTa.value = Object.keys(entry.mixExtra).length
        ? JSON.stringify(entry.mixExtra, null, 2)
        : "";
      extraTa.addEventListener("input", function () {
        const r = parseObjectJsonFromText(extraTa.value);
        if (r.ok) {
          entry.mixExtra = r.value;
          extraTa.classList.remove("invalid");
          refreshBadge();
          markDirty();
        } else {
          extraTa.classList.add("invalid");
        }
      });
    }
    if (isMovieMixesFile() && entry.max_movies != null) {
      body.hidden = false;
      expandBtn.textContent = "▼";
      expandBtn.setAttribute("aria-expanded", "true");
    } else if (entry.mixExtra && Object.keys(entry.mixExtra).length) {
      body.hidden = false;
      expandBtn.textContent = "▼";
      expandBtn.setAttribute("aria-expanded", "true");
    } else if (entry.use_spotify_posters === false) {
      body.hidden = false;
      expandBtn.textContent = "▼";
      expandBtn.setAttribute("aria-expanded", "true");
    }
    updateMixReleaseVisibility(wrap);
  }

  function createMixCard(entry) {
    const wrap = document.createElement("div");
    wrap.className = "group-card group-card--mix";
    wrap.dataset.uid = entry._uid;
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
    nameInput.value = entry.name;
    nameInput.setAttribute("aria-label", "Playlist / mix name");
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
    if (isMovieMixesFile()) {
      const movieHint = document.createElement("p");
      movieHint.className = "mix-movie-hint";
      movieHint.textContent = "Plex titles often use the “Movies - …” prefix; match your library’s naming if needed.";
      body.appendChild(movieHint);
    }
    const labG = document.createElement("div");
    labG.className = "field-label";
    labG.textContent = "Include genres (OR — match any)";
    const tagListG = document.createElement("div");
    tagListG.className = "tag-list tag-list-genres";
    const rowG = document.createElement("div");
    rowG.className = "tag-add-row";
    const inpG = document.createElement("select");
    inpG.className = "tag-input tag-input-genres";
    inpG.title =
      "Select from fetched Plex genres. Use “Fetch all show genres” for TV mixes or “Fetch all movie genres” for movie mixes.";
    const addG = document.createElement("button");
    addG.type = "button";
    addG.className = "tag-add tag-add-genres";
    addG.textContent = "Add";
    rowG.append(inpG, addG);
    const labX = document.createElement("div");
    labX.className = "field-label";
    labX.textContent = "Exclude genres (titles with any of these are dropped)";
    const tagListX = document.createElement("div");
    tagListX.className = "tag-list tag-list-excl";
    const rowX = document.createElement("div");
    rowX.className = "tag-add-row";
    const inpX = document.createElement("select");
    inpX.className = "tag-input tag-input-excl";
    inpX.title = inpG.title;
    const addX = document.createElement("button");
    addX.type = "button";
    addX.className = "tag-add tag-add-excl";
    addX.textContent = "Add";
    rowX.append(inpX, addX);
    const labR = document.createElement("div");
    labR.className = "field-label";
    labR.textContent = "Release year filter";
    const selM = document.createElement("select");
    selM.className = "mix-release-mode mix-field";
    selM.setAttribute("aria-label", "Release year filter type");
    [
      { v: "none", t: "No year filter" },
      { v: "after", t: "After year" },
      { v: "before", t: "Before (strictly before) year" },
      { v: "between", t: "Between two years" },
    ].forEach(function (o) {
      const opt = document.createElement("option");
      opt.value = o.v;
      opt.textContent = o.t;
      selM.appendChild(opt);
    });
    const relSingle = document.createElement("div");
    relSingle.className = "mix-rel-single mix-row";
    const labY = document.createElement("label");
    labY.textContent = "Year";
    const yInp = document.createElement("input");
    yInp.type = "number";
    yInp.className = "mix-year mix-field";
    yInp.min = "1800";
    yInp.max = "3000";
    relSingle.append(labY, yInp);
    const relBet = document.createElement("div");
    relBet.className = "mix-rel-between mix-row";
    const l1 = document.createElement("label");
    l1.textContent = "From";
    const sInp = document.createElement("input");
    sInp.type = "number";
    sInp.className = "mix-year-start mix-field";
    sInp.min = "1800";
    sInp.max = "3000";
    const l2 = document.createElement("label");
    l2.textContent = "To";
    const eInp = document.createElement("input");
    eInp.type = "number";
    eInp.className = "mix-year-end mix-field";
    eInp.min = "1800";
    eInp.max = "3000";
    relBet.append(l1, sInp, l2, eInp);
    const labW = document.createElement("div");
    labW.className = "field-label";
    labW.textContent = "Watched status filter";
    const wSel = document.createElement("select");
    wSel.className = "mix-watched mix-field";
    wSel.setAttribute("aria-label", "Watched status");
    ["any", "watched", "unwatched"].forEach(function (v) {
      const opt = document.createElement("option");
      opt.value = v;
      opt.textContent = v;
      wSel.appendChild(opt);
    });
    body.append(
      labG,
      tagListG,
      rowG,
      labX,
      tagListX,
      rowX,
      labR,
      selM,
      relSingle,
      relBet,
      labW,
      wSel
    );
    if (isMovieMixesFile()) {
      const labM = document.createElement("div");
      labM.className = "field-label";
      labM.textContent = "max_movies (optional)";
      const rowM = document.createElement("div");
      rowM.className = "mix-max-movies-row";
      const numM = document.createElement("input");
      numM.type = "number";
      numM.className = "mix-max-movies mix-field";
      numM.min = "1";
      numM.setAttribute("aria-label", "max_movies");
      const hintM = document.createElement("span");
      hintM.className = "plex-genres-status";
      hintM.textContent = "Caps random picks per mix (overrides .env).";
      rowM.append(numM, hintM);
      body.append(labM, rowM);
    }
    const mixSpotRow = document.createElement("div");
    mixSpotRow.className = "group-spotify-toggle mix-spotify-toggle";
    const mixSpotCb = document.createElement("input");
    mixSpotCb.type = "checkbox";
    mixSpotCb.className = "mix-use-spotify-poster";
    mixSpotCb.setAttribute("aria-label", "Upload Spotify-style poster for this mix");
    const mixSpotLab = document.createElement("label");
    mixSpotLab.className = "group-spotify-label";
    mixSpotLab.appendChild(mixSpotCb);
    mixSpotLab.appendChild(
      document.createTextNode(
        isMovieMixesFile()
          ? " Set local poster image for this mix (uncheck to keep Plex artwork)"
          : " Set Spotify-style playlist poster (uncheck to keep existing Plex artwork)"
      )
    );
    mixSpotRow.appendChild(mixSpotLab);
    body.append(mixSpotRow);
    const exBlock = document.createElement("div");
    exBlock.className = "filter-block";
    const labEx = document.createElement("div");
    labEx.className = "field-label";
    labEx.textContent = "Other mix fields (JSON object, optional)";
    const hintEx = document.createElement("p");
    hintEx.className = "mix-movie-hint";
    hintEx.style.margin = "0 0 0.4rem 0";
    hintEx.textContent =
      "Any extra per-key data not covered above. Must be a single JSON object (e.g. custom tooling).";
    const taEx = document.createElement("textarea");
    taEx.className = "group-filters-json mix-extra-json";
    taEx.setAttribute("spellcheck", "false");
    taEx.setAttribute("aria-label", "Other mix fields JSON");
    exBlock.append(labEx, hintEx, taEx);
    body.append(exBlock);
    wrap.append(head, body);
    bindMixCard(wrap, entry);
    return wrap;
  }

  function renderMixForm() {
    if (!jsonVisual) return;
    jsonVisual.innerHTML = "";
    const frag = document.createDocumentFragment();
    for (let i = 0; i < mixEntries.length; i++) {
      frag.appendChild(createMixCard(mixEntries[i]));
    }
    jsonVisual.appendChild(frag);
    applyGroupNameFilter();
    wireDarkListboxesInContainer(jsonVisual);
    reapplyAllMixGenreDatalistIds();
    if (jsonSortGroupsBtn) {
      jsonSortGroupsBtn.disabled = viewMode !== "form" || mixEntries.length < 2;
    }
  }

  function updatePlexDatalist() {
    if (!plexSeriesDatalist) return;
    plexSeriesDatalist.innerHTML = "";
    const frag = document.createDocumentFragment();
    for (let i = 0; i < plexTitles.length; i++) {
      const o = document.createElement("option");
      o.value = plexTitles[i];
      frag.appendChild(o);
    }
    plexSeriesDatalist.appendChild(frag);
    refreshAllPlexShowPickerSelects();
  }

  function populatePlexShowPickerSelect(selectEl, excludedTitles) {
    if (!selectEl) return;
    const excludedSet = new Set(
      (Array.isArray(excludedTitles) ? excludedTitles : []).map(function (t) {
        return String(t);
      })
    );
    selectEl.innerHTML = "";
    const opt0 = document.createElement("option");
    opt0.value = "";
    const availableCount = plexTitles.reduce(function (acc, t) {
      return acc + (excludedSet.has(String(t)) ? 0 : 1);
    }, 0);
    if (plexTitles.length) {
      opt0.textContent =
        "— Select a show to add (" + availableCount + " available of " + plexTitles.length + " cached) —";
    } else {
      opt0.textContent = "— Fetch all shows in the toolbar, or use the field below —";
    }
    selectEl.appendChild(opt0);
    for (var i = 0; i < plexTitles.length; i++) {
      const t = plexTitles[i];
      if (excludedSet.has(String(t))) continue;
      const o = document.createElement("option");
      o.value = t;
      o.textContent = t;
      selectEl.appendChild(o);
    }
  }

  function refreshAllPlexShowPickerSelects() {
    if (!jsonVisual) return;
    const nodes = jsonVisual.querySelectorAll("select.tag-select-plex");
    for (var i = 0; i < nodes.length; i++) {
      const sel = nodes[i];
      const card = sel.closest(".group-card");
      const uidVal = card && card.dataset ? card.dataset.uid : "";
      const ent = seriesEntries.find(function (x) {
        return x && x._uid === uidVal;
      });
      const excluded = ent && Array.isArray(ent.series) ? ent.series : [];
      populatePlexShowPickerSelect(sel, excluded);
    }
  }

  function populateSeriesGroupGenrePicker(selectEl, selectedList, noun) {
    if (!selectEl) return;
    selectEl.innerHTML = "";
    const used = new Set((selectedList || []).map(String));
    const available = plexTvGenres.filter(function (g) {
      return !used.has(String(g));
    });
    const opt0 = document.createElement("option");
    opt0.value = "";
    opt0.textContent = available.length
      ? "— Select " + noun + " (" + available.length + " available) —"
      : "— All cached TV genres already added —";
    selectEl.appendChild(opt0);
    for (let i = 0; i < available.length; i++) {
      const o = document.createElement("option");
      o.value = available[i];
      o.textContent = available[i];
      selectEl.appendChild(o);
    }
  }

  function refreshAllSeriesGroupGenrePickers() {
    if (!jsonVisual) return;
    const cards = jsonVisual.querySelectorAll(".group-card");
    for (let i = 0; i < cards.length; i++) {
      const card = cards[i];
      const uidVal = card.dataset ? card.dataset.uid : "";
      const ent = seriesEntries.find(function (x) {
        return x && x._uid === uidVal;
      });
      const gf = genreFilterValueToArray(ent && ent.filters && ent.filters.genre_filter);
      const ex = genreFilterValueToArray(ent && ent.filters && ent.filters.excluded_genres);
      populateSeriesGroupGenrePicker(
        card.querySelector(".group-genre-filter-select"),
        gf,
        "genre to include"
      );
      populateSeriesGroupGenrePicker(
        card.querySelector(".group-excluded-genres-select"),
        ex,
        "genre to exclude"
      );
    }
  }

  function updateMoviesDatalist() {
    if (!plexMoviesDatalist) return;
    plexMoviesDatalist.innerHTML = "";
    const frag = document.createDocumentFragment();
    for (let i = 0; i < plexMovieTitles.length; i++) {
      const o = document.createElement("option");
      o.value = plexMovieTitles[i];
      frag.appendChild(o);
    }
    plexMoviesDatalist.appendChild(frag);
  }

  function updateTvGenresDatalist() {
    if (!plexTvGenresDatalist) return;
    plexTvGenresDatalist.innerHTML = "";
    const frag = document.createDocumentFragment();
    for (let i = 0; i < plexTvGenres.length; i++) {
      const o = document.createElement("option");
      o.value = plexTvGenres[i];
      frag.appendChild(o);
    }
    plexTvGenresDatalist.appendChild(frag);
    reapplyAllMixGenreDatalistIds();
    refreshAllSeriesGroupGenrePickers();
  }

  function updateMovieGenresDatalist() {
    if (!plexMovieGenresDatalist) return;
    plexMovieGenresDatalist.innerHTML = "";
    const frag = document.createDocumentFragment();
    for (let i = 0; i < plexMovieGenres.length; i++) {
      const o = document.createElement("option");
      o.value = plexMovieGenres[i];
      frag.appendChild(o);
    }
    plexMovieGenresDatalist.appendChild(frag);
    reapplyAllMixGenreDatalistIds();
  }

  function updateTopCacheStatus() {
    if (!plexTopCacheStatus) return;
    const s = plexTitles.length;
    const m = plexMovieTitles.length;
    const gtv = plexTvGenres.length;
    const gmv = plexMovieGenres.length;
    const titleParts = [];
    if (s) titleParts.push(s + " show" + (s === 1 ? "" : "s"));
    if (m) titleParts.push(m + " movie" + (m === 1 ? "" : "s"));
    const titleLine = titleParts.length
      ? "Title cache: " + titleParts.join(" · ") + " (from Plex, stored in this browser)."
      : "Title cache: empty — use Fetch all shows / movies.";
    const genParts = [];
    if (gtv) genParts.push(gtv + " TV genre tag" + (gtv === 1 ? "" : "s"));
    if (gmv) genParts.push(gmv + " movie genre tag" + (gmv === 1 ? "" : "s"));
    const genLine = genParts.length
      ? "Genre cache: " + genParts.join(" · ") + " (from Plex, stored in this browser)."
      : "Genre cache: empty — use Fetch all show genres / all movie genres.";
    plexTopCacheStatus.textContent = titleLine + " " + genLine;
  }

  function setPlexStatus(text) {
    if (plexSeriesStatus) plexSeriesStatus.textContent = text || "";
  }

  function setTopFetchButtonsDisabled(on) {
    if (jsonFetchAllShows) jsonFetchAllShows.disabled = !!on;
    if (jsonFetchAllMovies) jsonFetchAllMovies.disabled = !!on;
    if (jsonFetchAllTvGenres) jsonFetchAllTvGenres.disabled = !!on;
    if (jsonFetchAllMovieGenres) jsonFetchAllMovieGenres.disabled = !!on;
  }

  function setPlexFetchBusy(on) {
    plexFetchBusy = !!on;
    setTopFetchButtonsDisabled(plexFetchBusy);
  }

  function loadPlexTitlesFromStorage() {
    try {
      const raw = localStorage.getItem(PLEX_SERIES_STORAGE_KEY);
      if (!raw) return;
      const j = JSON.parse(raw);
      if (Array.isArray(j.titles) && j.titles.length) {
        plexTitles = j.titles.slice();
        updatePlexDatalist();
        setPlexStatus(
          plexTitles.length +
            " show titles (cached) — use Fetch all shows above to refresh from Plex"
        );
      }
    } catch (e) {
      /* ignore */
    }
  }

  function loadMovieTitlesFromStorage() {
    try {
      const raw = localStorage.getItem(PLEX_MOVIES_STORAGE_KEY);
      if (!raw) return;
      const j = JSON.parse(raw);
      if (Array.isArray(j.titles) && j.titles.length) {
        plexMovieTitles = j.titles.slice();
        updateMoviesDatalist();
      }
    } catch (e) {
      /* ignore */
    }
  }

  function fetchShowsFromPlex() {
    setPlexStatus("Loading…");
    setPlexFetchBusy(true);
    return fetch("/api/plex/tv-series", { method: "POST" })
      .then(function (r) {
        return r.json().then(function (j) {
          return { ok: r.ok, j: j };
        });
      })
      .then(function (res) {
        if (!res.ok) {
          setPlexStatus(res.j.error || "Error");
          showToast(res.j.error || "Failed to load shows", true);
          updateTopCacheStatus();
          return;
        }
        const list = res.j.titles;
        if (!Array.isArray(list) || !list.length) {
          setPlexStatus("No shows returned");
          showToast(
            "No TV shows in this library — check PLEX_TV_SECTION in .env.",
            true
          );
          updateTopCacheStatus();
          return;
        }
        plexTitles = list;
        updatePlexDatalist();
        try {
          localStorage.setItem(
            PLEX_SERIES_STORAGE_KEY,
            JSON.stringify({ titles: plexTitles, fetchedAt: Date.now() })
          );
        } catch (e) {
          /* ignore */
        }
        setPlexStatus(
          list.length +
            " show titles from “" +
            (res.j.library_section || "TV") +
            "”"
        );
        showToast("Loaded " + list.length + " show titles (cached for suggestions).", false);
        updateTopCacheStatus();
      })
      .catch(function (e) {
        setPlexStatus(String(e));
        showToast(String(e), true);
        updateTopCacheStatus();
      })
      .finally(function () {
        setPlexFetchBusy(false);
      });
  }

  function fetchMoviesFromPlex() {
    setPlexFetchBusy(true);
    return fetch("/api/plex/movies", { method: "POST" })
      .then(function (r) {
        return r.json().then(function (j) {
          return { ok: r.ok, j: j };
        });
      })
      .then(function (res) {
        if (!res.ok) {
          showToast(res.j.error || "Failed to load movies", true);
          updateTopCacheStatus();
          return;
        }
        const list = res.j.titles;
        if (!Array.isArray(list) || !list.length) {
          showToast("No movies returned from this library.", true);
          updateTopCacheStatus();
          return;
        }
        plexMovieTitles = list;
        updateMoviesDatalist();
        try {
          localStorage.setItem(
            PLEX_MOVIES_STORAGE_KEY,
            JSON.stringify({ titles: plexMovieTitles, fetchedAt: Date.now() })
          );
        } catch (e) {
          /* ignore */
        }
        showToast("Loaded " + list.length + " movie titles (cached in this browser).", false);
        updateTopCacheStatus();
      })
      .catch(function (e) {
        showToast(String(e), true);
        updateTopCacheStatus();
      })
      .finally(function () {
        setPlexFetchBusy(false);
      });
  }

  function loadTvGenresFromStorage() {
    try {
      const raw = localStorage.getItem(PLEX_TV_GENRES_STORAGE_KEY);
      if (!raw) return;
      const j = JSON.parse(raw);
      if (Array.isArray(j.genres) && j.genres.length) {
        plexTvGenres = j.genres.slice();
        updateTvGenresDatalist();
      }
    } catch (e) {
      /* ignore */
    }
  }

  function loadMovieGenresFromStorage() {
    try {
      const raw = localStorage.getItem(PLEX_MOVIE_GENRES_STORAGE_KEY);
      if (!raw) return;
      const j = JSON.parse(raw);
      if (Array.isArray(j.genres) && j.genres.length) {
        plexMovieGenres = j.genres.slice();
        updateMovieGenresDatalist();
      }
    } catch (e) {
      /* ignore */
    }
  }

  function fetchTvGenresFromPlex() {
    setPlexFetchBusy(true);
    return fetch("/api/plex/tv-genres", { method: "POST" })
      .then(function (r) {
        return r.json().then(function (j) {
          return { ok: r.ok, j: j };
        });
      })
      .then(function (res) {
        if (!res.ok) {
          showToast(res.j.error || "Failed to load TV genres", true);
          updateTopCacheStatus();
          return;
        }
        const list = res.j.genres;
        if (!Array.isArray(list) || !list.length) {
          showToast("No show genres in this library (or empty).", true);
          updateTopCacheStatus();
          return;
        }
        plexTvGenres = list;
        updateTvGenresDatalist();
        try {
          localStorage.setItem(
            PLEX_TV_GENRES_STORAGE_KEY,
            JSON.stringify({ genres: plexTvGenres, fetchedAt: Date.now() })
          );
        } catch (e) {
          /* ignore */
        }
        showToast(
          "Loaded " + list.length + " TV genre tag(s) (cached in this browser).",
          false
        );
        updateTopCacheStatus();
      })
      .catch(function (e) {
        showToast(String(e), true);
        updateTopCacheStatus();
      })
      .finally(function () {
        setPlexFetchBusy(false);
      });
  }

  function fetchMovieGenresFromPlex() {
    setPlexFetchBusy(true);
    return fetch("/api/plex/movie-genres", { method: "POST" })
      .then(function (r) {
        return r.json().then(function (j) {
          return { ok: r.ok, j: j };
        });
      })
      .then(function (res) {
        if (!res.ok) {
          showToast(res.j.error || "Failed to load movie genres", true);
          updateTopCacheStatus();
          return;
        }
        const list = res.j.genres;
        if (!Array.isArray(list) || !list.length) {
          showToast("No movie genres in this library (or empty).", true);
          updateTopCacheStatus();
          return;
        }
        plexMovieGenres = list;
        updateMovieGenresDatalist();
        try {
          localStorage.setItem(
            PLEX_MOVIE_GENRES_STORAGE_KEY,
            JSON.stringify({ genres: plexMovieGenres, fetchedAt: Date.now() })
          );
        } catch (e) {
          /* ignore */
        }
        showToast(
          "Loaded " + list.length + " movie genre tag(s) (cached in this browser).",
          false
        );
        updateTopCacheStatus();
      })
      .catch(function (e) {
        showToast(String(e), true);
        updateTopCacheStatus();
      })
      .finally(function () {
        setPlexFetchBusy(false);
      });
  }

  function applySeriesEntries(ent, sourceLabel) {
    mixEntries = [];
    seriesEntries = ent;
    formParseError = null;
    renderSeriesForm();
    syncTextareaFromSeries();
    setJsonDirty(false);
    baselineText = jsonEditor.value;
    if (sourceLabel) updateJsonMeta(sourceLabel);
    updateFileOptionKeyCount();
  }

  function tryIngestSeriesText(text) {
    const trimmed = (text || "").trim() || "{}";
    const obj = JSON.parse(trimmed);
    const ent = parseSeriesFromObject(obj);
    applySeriesEntries(ent, null);
  }

  function syncFormVariantToolbar() {
    if (jsonAddGroupBtn) {
      if (isSeriesGroups()) {
        jsonAddGroupBtn.textContent = "Add group";
      } else {
        jsonAddGroupBtn.textContent = "Add mix";
      }
    }
    if (jsonGroupFilter) {
      jsonGroupFilter.placeholder = isSeriesGroups()
        ? "Filter groups by name…"
        : "Filter entries by name…";
    }
    if (plexSeriesStatus) {
      const showPlex = viewMode === "form" && !formParseError && isSeriesGroups();
      plexSeriesStatus.style.display = showPlex ? "" : "none";
    }
  }

  function setViewMode(mode) {
    if (!supportsFormEditor()) {
      viewMode = "raw";
      if (jsonVisual) jsonVisual.classList.add("hidden");
      jsonEditor.classList.remove("hidden");
      if (jsonSeriesToolbar) jsonSeriesToolbar.classList.add("hidden");
      if (jsonViewFormBtn) jsonViewFormBtn.classList.remove("active");
      if (jsonViewRawBtn) jsonViewRawBtn.classList.add("active");
      return;
    }
    viewMode = mode;
    const form = mode === "form" && !formParseError;
    if (jsonVisual) jsonVisual.classList.toggle("hidden", !form);
    jsonEditor.classList.toggle("hidden", form);
    if (jsonSeriesToolbar) jsonSeriesToolbar.classList.toggle("hidden", !form);
    if (jsonViewFormBtn) jsonViewFormBtn.classList.toggle("active", form);
    if (jsonViewRawBtn) jsonViewRawBtn.classList.toggle("active", !form);
    if (jsonAddGroupBtn) jsonAddGroupBtn.disabled = !form;
    let nKeys = 0;
    if (isSeriesGroups()) nKeys = seriesEntries.length;
    else if (isGenreMixesFile() || isMovieMixesFile()) nKeys = mixEntries.length;
    if (jsonSortGroupsBtn) {
      jsonSortGroupsBtn.disabled = !form || nKeys < 2;
    }
    if (jsonGroupFilter) jsonGroupFilter.disabled = !form;
    syncFormVariantToolbar();
  }

  function renderTags(tagList, seriesArr, onChange) {
    tagList.innerHTML = "";
    seriesArr.forEach(function (title, idx) {
      const span = document.createElement("span");
      span.className = "tag-chip";
      span.appendChild(document.createTextNode(title + " "));
      const x = document.createElement("button");
      x.type = "button";
      x.className = "tag-remove";
      x.setAttribute("aria-label", "Remove");
      x.textContent = "×";
      x.addEventListener("click", function () {
        seriesArr.splice(idx, 1);
        renderTags(tagList, seriesArr, onChange);
        onChange();
      });
      span.appendChild(x);
      tagList.appendChild(span);
    });
  }

  function bindGroupCard(wrap, entry) {
    if (!entry.filters) {
      entry.filters = {};
    }
    const expandBtn = wrap.querySelector(".group-card-expand");
    const head = wrap.querySelector(".group-card-head");
    const body = wrap.querySelector(".group-card-body");
    const nameInput = wrap.querySelector(".group-card-name");
    const badge = wrap.querySelector(".group-card-badge");
    const removeBtn = wrap.querySelector(".group-card-remove");
    const tagList = wrap.querySelector(".tag-list");
    const tagSelect = wrap.querySelector("select.tag-select-plex");
    const tagInput = wrap.querySelector("input.tag-input-plex-custom");
    const tagAdd = wrap.querySelector(".tag-add");
    const filtersAdv = wrap.querySelector("textarea.group-filters-advanced");
    const filtersExtras = wrap.querySelector("textarea.group-filters-extras");
    const genreFilterInput = wrap.querySelector(".group-genre-filter");
    const excludedGenresInput = wrap.querySelector(".group-excluded-genres");
    const genreFilterTags = wrap.querySelector(".group-genre-filter-tags");
    const genreFilterSelect = wrap.querySelector(".group-genre-filter-select");
    const genreFilterAdd = wrap.querySelector(".group-genre-filter-add");
    const excludedGenresTags = wrap.querySelector(".group-excluded-genres-tags");
    const excludedGenresSelect = wrap.querySelector(".group-excluded-genres-select");
    const excludedGenresAdd = wrap.querySelector(".group-excluded-genres-add");
    const seasonRowsEl = wrap.querySelector(".season-filter-rows");
    const seasonAddBtn = wrap.querySelector("button.season-filter-add");
    var repopulateAfterTags = function () {};
    var genreFilterList = genreFilterValueToArray(
      entry.filters && entry.filters.genre_filter
    );
    var excludedGenreList = genreFilterValueToArray(
      entry.filters && entry.filters.excluded_genres
    );
    function syncGenreFilterHiddenInputs() {
      if (genreFilterInput) genreFilterInput.value = genreFilterList.join(", ");
      if (excludedGenresInput) excludedGenresInput.value = excludedGenreList.join(", ");
    }
    function renderSeriesGenreFilterTags() {
      if (genreFilterTags) {
        renderTags(genreFilterTags, genreFilterList, function () {
          syncGenreFilterHiddenInputs();
          if (!genreFilterList.length) {
            delete entry.filters.genre_filter;
          } else {
            entry.filters.genre_filter =
              genreFilterList.length === 1
                ? genreFilterList[0]
                : genreFilterList.slice();
          }
          populateSeriesGroupGenrePicker(
            genreFilterSelect,
            genreFilterList,
            "genre to include"
          );
          refreshBadge();
          markDirty();
        });
      }
      if (excludedGenresTags) {
        renderTags(excludedGenresTags, excludedGenreList, function () {
          syncGenreFilterHiddenInputs();
          if (!excludedGenreList.length) {
            delete entry.filters.excluded_genres;
          } else {
            entry.filters.excluded_genres =
              excludedGenreList.length === 1
                ? excludedGenreList[0]
                : excludedGenreList.slice();
          }
          populateSeriesGroupGenrePicker(
            excludedGenresSelect,
            excludedGenreList,
            "genre to exclude"
          );
          refreshBadge();
          markDirty();
        });
      }
      populateSeriesGroupGenrePicker(
        genreFilterSelect,
        genreFilterList,
        "genre to include"
      );
      populateSeriesGroupGenrePicker(
        excludedGenresSelect,
        excludedGenreList,
        "genre to exclude"
      );
      syncGenreFilterHiddenInputs();
    }
    function addGenreFilterFromSelect(isExcluded) {
      const selectEl = isExcluded ? excludedGenresSelect : genreFilterSelect;
      const target = isExcluded ? excludedGenreList : genreFilterList;
      if (!selectEl || !selectEl.value) return;
      const v = String(selectEl.value).trim();
      if (!v) return;
      if (target.indexOf(v) !== -1) {
        showToast("Already listed.", true);
        return;
      }
      target.push(v);
      if (isExcluded) {
        entry.filters.excluded_genres =
          target.length === 1 ? target[0] : target.slice();
      } else {
        entry.filters.genre_filter = target.length === 1 ? target[0] : target.slice();
      }
      renderSeriesGenreFilterTags();
      refreshBadge();
      markDirty();
    }
    function repopulateTagSelectForEntry() {
      if (!tagSelect) return;
      const prev = tagSelect.value || "";
      populatePlexShowPickerSelect(tagSelect, entry.series);
      if (prev && entry.series.indexOf(prev) === -1) {
        tagSelect.value = prev;
      }
    }
    repopulateAfterTags = function () {
      repopulateTagSelectForEntry();
    };

    if (entry.use_spotify_posters === undefined) {
      entry.use_spotify_posters = true;
    }
    const spotCb = wrap.querySelector(".group-use-spotify-poster");
    if (spotCb) {
      spotCb.checked = entry.use_spotify_posters !== false;
      spotCb.addEventListener("change", function () {
        entry.use_spotify_posters = spotCb.checked;
        markDirty();
      });
    }

    function refreshBadge() {
      const n = entry.series.length;
      const fk = entry.filters && typeof entry.filters === "object" ? Object.keys(entry.filters) : [];
      const tail = entry.use_spotify_posters === false ? " · no poster" : "";
      if (fk.length === 0) {
        badge.textContent = n + " series" + tail;
      } else if (fk.length === 1) {
        const k0 = fk[0];
        const label = k0 === "season_filter" ? "season filter" : k0;
        badge.textContent = n + " series · " + label + tail;
      } else {
        badge.textContent = n + " series · " + fk.length + " extra keys" + tail;
      }
    }
    refreshBadge();

    function markDirty() {
      syncTextareaFromSeries();
      setJsonDirty(jsonEditor.value !== baselineText);
      updateJsonMeta("Unsaved changes");
      updateFileOptionKeyCount();
    }

    function toggleExpand() {
      const open = !body.hidden;
      body.hidden = open;
      expandBtn.textContent = open ? "▶" : "▼";
      expandBtn.setAttribute("aria-expanded", open ? "false" : "true");
    }

    expandBtn.addEventListener("click", toggleExpand);
    head.addEventListener("dblclick", function (ev) {
      if (ev.target === nameInput) return;
      toggleExpand();
    });

    nameInput.addEventListener("input", function () {
      entry.name = nameInput.value;
      markDirty();
    });

    removeBtn.addEventListener("click", function () {
      if (!window.confirm('Remove group "' + entry.name + '" and all its series?')) return;
      seriesEntries = seriesEntries.filter(function (x) {
        return x._uid !== entry._uid;
      });
      wrap.remove();
      setJsonDirty(true);
      updateJsonMeta("Unsaved changes");
      updateFileOptionKeyCount();
      syncTextareaFromSeries();
    });

    function renderThisTags() {
      renderTags(tagList, entry.series, function () {
        refreshBadge();
        markDirty();
      });
      repopulateAfterTags();
    }

    function addTag() {
      var v = "";
      if (tagSelect && tagSelect.value) {
        v = String(tagSelect.value).trim();
      }
      if (!v && tagInput) {
        v = (tagInput.value || "").trim();
      }
      if (tagSelect) tagSelect.value = "";
      if (tagInput) tagInput.value = "";
      if (!v) return;
      if (entry.series.indexOf(v) !== -1) {
        showToast("Already in this group.", true);
        return;
      }
      entry.series.push(v);
      renderThisTags();
      refreshBadge();
      markDirty();
    }
    if (tagAdd) tagAdd.addEventListener("click", addTag);
    if (tagInput) {
      tagInput.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter") {
          ev.preventDefault();
          addTag();
        }
      });
    }
    repopulateTagSelectForEntry();

    if (filtersAdv) {
      if (!entry.filters) {
        entry.filters = {};
      }
      const advFilters = Object.assign({}, entry.filters);
      delete advFilters.genre_filter;
      filtersAdv.value = Object.keys(advFilters).length
        ? JSON.stringify(advFilters, null, 2)
        : "";
      filtersAdv.addEventListener("input", function () {
        const r = parseObjectJsonFromText(filtersAdv.value);
        if (r.ok) {
          const next = Object.assign({}, r.value);
          const gf = normalizeGenreFilterFromText(
            genreFilterInput ? genreFilterInput.value : ""
          );
          const ex = normalizeExcludedGenresFromText(
            excludedGenresInput ? excludedGenresInput.value : ""
          );
          if (gf != null) {
            next.genre_filter = gf;
          }
          if (ex != null) {
            next.excluded_genres = ex;
          }
          entry.filters = next;
          filtersAdv.classList.remove("invalid");
          refreshBadge();
          markDirty();
        } else {
          filtersAdv.classList.add("invalid");
        }
      });
    } else if (seasonRowsEl && filtersExtras) {
      function repopulateSeasonSelects() {
        const rowNodes = seasonRowsEl.querySelectorAll(".season-filter-row");
        for (let r = 0; r < rowNodes.length; r++) {
          const row = rowNodes[r];
          const sel = row.querySelector(".season-filter-show");
          if (sel) {
            const cur = sel.value;
            fillShowSelectFromSeries(sel, entry.series, cur);
          }
        }
      }
      function mergeStructuredFiltersToEntry() {
        if (!seasonRowsEl || !filtersExtras) return;
        const re = parseObjectJsonFromText(filtersExtras.value);
        if (!re.ok) {
          filtersExtras.classList.add("invalid");
          return;
        }
        filtersExtras.classList.remove("invalid");
        const sf = readSeasonFilterRowsFromEl(seasonRowsEl);
        const merged = Object.assign({}, re.value);
        if (Object.keys(sf).length) {
          merged.season_filter = sf;
        } else {
          delete merged.season_filter;
        }
        const gf = normalizeGenreFilterFromText(
          genreFilterInput ? genreFilterInput.value : ""
        );
        const ex = normalizeExcludedGenresFromText(
          excludedGenresInput ? excludedGenresInput.value : ""
        );
        if (gf == null) {
          delete merged.genre_filter;
        } else {
          merged.genre_filter = gf;
        }
        if (ex == null) {
          delete merged.excluded_genres;
        } else {
          merged.excluded_genres = ex;
        }
        entry.filters = merged;
        refreshBadge();
        markDirty();
      }
      function appendSeasonFilterRow(show, start, end) {
        const row = document.createElement("div");
        row.className = "season-filter-row";
        const sl = document.createElement("select");
        sl.className = "season-filter-show";
        sl.setAttribute("aria-label", "Show");
        const st = start != null && !isNaN(Number(start)) ? Number(start) : 1;
        const en = end != null && !isNaN(Number(end)) ? Number(end) : 999;
        fillShowSelectFromSeries(sl, entry.series, show);
        if (sl.value === "" && entry.series.length === 1) {
          sl.value = String(entry.series[0]);
        }
        const sIn = document.createElement("input");
        sIn.type = "number";
        sIn.className = "season-filter-start";
        sIn.min = "0";
        sIn.setAttribute("aria-label", "Start season");
        sIn.value = String(st);
        const eIn = document.createElement("input");
        eIn.type = "number";
        eIn.className = "season-filter-end";
        eIn.min = "0";
        eIn.setAttribute("aria-label", "End season");
        eIn.value = String(en);
        const sp1 = document.createElement("span");
        sp1.className = "season-filter-field-label";
        sp1.appendChild(document.createTextNode("Start"));
        const sp2 = document.createElement("span");
        sp2.className = "season-filter-field-label";
        sp2.appendChild(document.createTextNode("End"));
        const rm = document.createElement("button");
        rm.type = "button";
        rm.className = "season-filter-remove";
        rm.setAttribute("aria-label", "Remove this season range");
        rm.textContent = "×";
        row.appendChild(sl);
        row.appendChild(sp1);
        row.appendChild(sIn);
        row.appendChild(sp2);
        row.appendChild(eIn);
        row.appendChild(rm);
        function rowDirty() {
          mergeStructuredFiltersToEntry();
        }
        sl.addEventListener("change", rowDirty);
        sIn.addEventListener("input", rowDirty);
        eIn.addEventListener("input", rowDirty);
        rm.addEventListener("click", function () {
          row.remove();
          rowDirty();
        });
        seasonRowsEl.appendChild(row);
      }
      const rowsInit = seasonFilterToRows(entry.filters && entry.filters.season_filter);
      if (rowsInit.length) {
        for (let ir = 0; ir < rowsInit.length; ir++) {
          const rr = rowsInit[ir];
          appendSeasonFilterRow(rr.show, rr.start, rr.end);
        }
      }
      if (seasonAddBtn) {
        seasonAddBtn.addEventListener("click", function () {
          const pick =
            entry.series && entry.series.length
              ? entry.series[0]
              : null;
          appendSeasonFilterRow(pick, 1, 999);
          mergeStructuredFiltersToEntry();
        });
      }
      filtersExtras.addEventListener("input", function () {
        mergeStructuredFiltersToEntry();
      });
      repopulateAfterTags = repopulateSeasonSelects;
    }

    if (genreFilterAdd) {
      genreFilterAdd.addEventListener("click", function () {
        addGenreFilterFromSelect(false);
      });
    }
    if (genreFilterSelect) {
      genreFilterSelect.addEventListener("change", function () {
        addGenreFilterFromSelect(false);
      });
    }
    if (excludedGenresAdd) {
      excludedGenresAdd.addEventListener("click", function () {
        addGenreFilterFromSelect(true);
      });
    }
    if (excludedGenresSelect) {
      excludedGenresSelect.addEventListener("change", function () {
        addGenreFilterFromSelect(true);
      });
    }
    renderSeriesGenreFilterTags();

    renderThisTags();
  }

  function createGroupCard(entry) {
    const wrap = document.createElement("div");
    wrap.className = "group-card";
    wrap.dataset.uid = entry._uid;
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
    nameInput.value = entry.name;
    nameInput.setAttribute("aria-label", "Playlist group name");
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
    const lab = document.createElement("div");
    lab.className = "field-label";
    lab.textContent = "TV series (show titles as in Plex)";
    const tagList = document.createElement("div");
    tagList.className = "tag-list";
    const addRowPlex = document.createElement("div");
    addRowPlex.className = "tag-add-row";
    const tagSelect = document.createElement("select");
    tagSelect.className = "tag-select-plex";
    tagSelect.setAttribute("aria-label", "Pick a show from the Plex list");
    populatePlexShowPickerSelect(tagSelect);
    const tagAdd = document.createElement("button");
    tagAdd.type = "button";
    tagAdd.className = "tag-add";
    tagAdd.textContent = "Add";
    addRowPlex.appendChild(tagSelect);
    addRowPlex.appendChild(tagAdd);
    const orHint = document.createElement("p");
    orHint.className = "tag-plex-or-hint";
    orHint.textContent =
      "Or type a title that must match Plex exactly. The text field reuses the same list as search-as-you-type suggestions.";
    const addRowCustom = document.createElement("div");
    addRowCustom.className = "tag-add-row tag-add-row--custom";
    const tagInput = document.createElement("input");
    tagInput.type = "text";
    tagInput.className = "tag-input tag-input-plex-custom";
    tagInput.setAttribute("autocomplete", "off");
    tagInput.setAttribute("list", "plex-tv-datalist");
    tagInput.placeholder = "Type a show title, or use the dropdown above";
    addRowCustom.appendChild(tagInput);
    const spotRow = document.createElement("div");
    spotRow.className = "group-spotify-toggle";
    const spotCb = document.createElement("input");
    spotCb.type = "checkbox";
    spotCb.className = "group-use-spotify-poster";
    spotCb.setAttribute("aria-label", "Upload Spotify-style poster for this group");
    const spotLab = document.createElement("label");
    spotLab.className = "group-spotify-label";
    spotLab.appendChild(spotCb);
    spotLab.appendChild(
      document.createTextNode(
        " Set Spotify-style playlist poster (uncheck to keep existing Plex artwork)"
      )
    );
    spotRow.appendChild(spotLab);
    const genreBlock = document.createElement("div");
    genreBlock.className = "filter-block";
    const labGf = document.createElement("div");
    labGf.className = "field-label";
    labGf.textContent = "Genre filter (optional)";
    const hintGf = document.createElement("p");
    hintGf.className = "mix-movie-hint";
    hintGf.style.margin = "0 0 0.4rem 0";
    hintGf.textContent =
      "Auto-include all shows in these genres (from Plex tags). Add one or more genres from the list.";
    const genreTags = document.createElement("div");
    genreTags.className = "tag-list group-genre-filter-tags";
    const genreRow = document.createElement("div");
    genreRow.className = "tag-add-row";
    const genreSelect = document.createElement("select");
    genreSelect.className = "tag-input group-genre-filter-select";
    genreSelect.setAttribute("aria-label", "Genre filter for this group");
    const genreAdd = document.createElement("button");
    genreAdd.type = "button";
    genreAdd.className = "tag-add group-genre-filter-add";
    genreAdd.textContent = "Add";
    genreRow.append(genreSelect, genreAdd);
    const genreInput = document.createElement("input");
    genreInput.type = "hidden";
    genreInput.className = "group-genre-filter";
    const labExG = document.createElement("div");
    labExG.className = "field-label";
    labExG.style.marginTop = "0.55rem";
    labExG.textContent = "Excluded genres (optional)";
    const hintExG = document.createElement("p");
    hintExG.className = "mix-movie-hint";
    hintExG.style.margin = "0 0 0.4rem 0";
    hintExG.textContent =
      "Drop wildcard/genre-filter matches that contain these genres. Add one or more genres from the list.";
    const excludedGenresTags = document.createElement("div");
    excludedGenresTags.className = "tag-list group-excluded-genres-tags";
    const excludedGenresRow = document.createElement("div");
    excludedGenresRow.className = "tag-add-row";
    const excludedGenresSelect = document.createElement("select");
    excludedGenresSelect.className = "tag-input group-excluded-genres-select";
    excludedGenresSelect.setAttribute("aria-label", "Excluded genres for this group");
    const excludedGenresAdd = document.createElement("button");
    excludedGenresAdd.type = "button";
    excludedGenresAdd.className = "tag-add group-excluded-genres-add";
    excludedGenresAdd.textContent = "Add";
    excludedGenresRow.append(excludedGenresSelect, excludedGenresAdd);
    const excludedGenresInput = document.createElement("input");
    excludedGenresInput.type = "hidden";
    excludedGenresInput.className = "group-excluded-genres";
    genreBlock.append(
      labGf,
      hintGf,
      genreTags,
      genreRow,
      genreInput,
      labExG,
      hintExG,
      excludedGenresTags,
      excludedGenresRow,
      excludedGenresInput
    );
    const filterBlock = document.createElement("div");
    filterBlock.className = "filter-block";
    const useAdvanced = !canRepresentSeasonFilter(
      entry.filters && entry.filters.season_filter
    );
    if (useAdvanced) {
      const note = document.createElement("p");
      note.className = "filter-advanced-note";
      note.textContent =
        "season_filter uses a list, global value, or another form the form view cannot show — edit as JSON, or switch to per-show start/end in raw JSON to use the picker again.";
      const labF = document.createElement("div");
      labF.className = "field-label";
      labF.textContent = "Group filters (JSON) — e.g. season_filter";
      const hintF = document.createElement("p");
      hintF.className = "mix-movie-hint";
      hintF.style.margin = "0 0 0.4rem 0";
      hintF.textContent =
        "All keys except series (PvPG-Series.py). One object per group.";
      const filtersTa = document.createElement("textarea");
      filtersTa.className = "group-filters-json group-filters-advanced";
      filtersTa.setAttribute("spellcheck", "false");
      filtersTa.setAttribute("aria-label", "Group filters JSON (advanced)");
      filtersTa.value = Object.keys(entry.filters || {}).length
        ? JSON.stringify(entry.filters, null, 2)
        : "";
      filterBlock.append(note, labF, hintF, filtersTa);
    } else {
      const labS = document.createElement("div");
      labS.className = "field-label";
      labS.textContent = "Season filter (per show)";
      const hintS = document.createElement("p");
      hintS.className = "mix-movie-hint";
      hintS.style.margin = "0 0 0.4rem 0";
      hintS.textContent =
        "Limit episodes to a season range per series (same titles as the list above). Leave empty to include all seasons.";
      const struct = document.createElement("div");
      struct.className = "season-filter-structured";
      const rowsEl = document.createElement("div");
      rowsEl.className = "season-filter-rows";
      struct.appendChild(rowsEl);
      const addWrap = document.createElement("div");
      addWrap.className = "season-filter-add-row";
      const addBtn = document.createElement("button");
      addBtn.type = "button";
      addBtn.className = "season-filter-add";
      addBtn.setAttribute("aria-label", "Add a season range row");
      addBtn.textContent = "Add season range";
      addWrap.appendChild(addBtn);
      struct.appendChild(addWrap);
      const labE = document.createElement("div");
      labE.className = "field-label";
      labE.style.marginTop = "0.6rem";
      labE.textContent = "Other filter keys (JSON, optional)";
      const hintE = document.createElement("p");
      hintE.className = "mix-movie-hint";
      hintE.style.margin = "0 0 0.4rem 0";
      hintE.textContent =
        "Any other keys (besides series and use_spotify_posters). Do not put season_filter, genre_filter, or excluded_genres here; use the dedicated fields above.";
      const filtersExtras = document.createElement("textarea");
      filtersExtras.className = "group-filters-json group-filters-extras";
      filtersExtras.setAttribute("spellcheck", "false");
      filtersExtras.setAttribute("aria-label", "Other group filter keys as JSON");
      const fNoSeason = filtersWithoutSeason(entry.filters);
      filtersExtras.value = Object.keys(fNoSeason).length
        ? JSON.stringify(fNoSeason, null, 2)
        : "";
      filterBlock.append(
        labS,
        hintS,
        struct,
        labE,
        hintE,
        filtersExtras
      );
    }
    body.append(
      lab,
      tagList,
      addRowPlex,
      orHint,
      addRowCustom,
      spotRow,
      genreBlock,
      filterBlock
    );
    wrap.append(head, body);
    bindGroupCard(wrap, entry);
    return wrap;
  }

  function applyGroupNameFilter() {
    const q = ((jsonGroupFilter && jsonGroupFilter.value) || "").trim().toLowerCase();
    if (!jsonVisual) return;
    jsonVisual.querySelectorAll(".group-card").forEach(function (card) {
      const nameInput = card.querySelector(".group-card-name");
      const name = (nameInput && nameInput.value) || "";
      const ok = !q || name.toLowerCase().indexOf(q) !== -1;
      card.style.display = ok ? "" : "none";
    });
  }

  function renderSeriesForm() {
    if (!jsonVisual) return;
    jsonVisual.innerHTML = "";
    const frag = document.createDocumentFragment();
    for (let i = 0; i < seriesEntries.length; i++) {
      frag.appendChild(createGroupCard(seriesEntries[i]));
    }
    jsonVisual.appendChild(frag);
    applyGroupNameFilter();
    wireDarkListboxesInContainer(jsonVisual);
    if (jsonSortGroupsBtn) {
      jsonSortGroupsBtn.disabled = viewMode !== "form" || seriesEntries.length < 2;
    }
  }

  /**
   * @param {string} text
   * @param {string} id - json file id (series_groups, …)
   * @param {{ fromDisk: boolean, exists: boolean }} source - fromDisk: from server or upload
   */
  function applyGroupJsonFromText(text, id, source) {
    const fromDisk = source && source.fromDisk;
    const exists = !!(source && source.exists);
    var t = text != null ? String(text) : "";
    if (!String(t).trim()) t = "{\n}\n";
    jsonEditor.value = t;
    if (fromDisk) {
      baselineText = t;
      jsonSelectLockedValue = jsonSelect.value;
    }
    formParseError = null;
    const diskOrNew = (exists ? "On disk — " : "New file — ") + "";
    const importPre = "Import — ";

    if (id === "series_groups") {
      try {
        tryIngestSeriesText(t);
        if (jsonViewToggle) jsonViewToggle.classList.remove("hidden");
        setViewMode("form");
        updateJsonMeta(
          (fromDisk ? diskOrNew : importPre) +
            "Form view — " +
            seriesEntries.length +
            " group(s). Double-click a header to expand." +
            (fromDisk ? "" : " Not saved to server (click Save).")
        );
      } catch (err) {
        formParseError = err;
        seriesEntries = [];
        mixEntries = [];
        if (jsonViewToggle) jsonViewToggle.classList.remove("hidden");
        setViewMode("raw");
        const errLine =
          "Cannot use form: " + err.message + " — fix JSON in raw view, then choose Form.";
        updateJsonMeta((fromDisk ? "" : importPre) + errLine, true);
        showToast(err.message, true);
      }
    } else if (id === "genre_mixes" || id === "movie_genre_mixes") {
      try {
        tryIngestMixText(t);
        if (jsonViewToggle) jsonViewToggle.classList.remove("hidden");
        setViewMode("form");
        const kind = id === "movie_genre_mixes" ? "movie mix" : "TV genre mix";
        updateJsonMeta(
          (fromDisk ? diskOrNew : importPre) +
            "Form view — " +
            mixEntries.length +
            " " +
            kind +
            "(es). Double-click a header to expand." +
            (fromDisk ? "" : " Not saved to server (click Save).")
        );
      } catch (err) {
        formParseError = err;
        seriesEntries = [];
        mixEntries = [];
        if (jsonViewToggle) jsonViewToggle.classList.remove("hidden");
        setViewMode("raw");
        const errLine =
          "Cannot use form: " + err.message + " — fix JSON in raw view, then choose Form.";
        updateJsonMeta((fromDisk ? "" : importPre) + errLine, true);
        showToast(err.message, true);
      }
    } else {
      if (jsonViewToggle) jsonViewToggle.classList.add("hidden");
      if (jsonSeriesToolbar) jsonSeriesToolbar.classList.add("hidden");
      if (jsonVisual) {
        jsonVisual.innerHTML = "";
        jsonVisual.classList.add("hidden");
      }
      jsonEditor.classList.remove("hidden");
      updateJsonMeta(
        (fromDisk ? diskOrNew : importPre) +
          "Raw JSON — " +
          (jsonSelect.options[jsonSelect.selectedIndex]
            ? jsonSelect.options[jsonSelect.selectedIndex].text
            : id) +
          (fromDisk ? "" : " — not saved to server (click Save).")
      );
    }
    setJsonDirty(!fromDisk);
    updateFileOptionKeyCount();
  }

  function downloadGroupJsonFile() {
    if (jsonLoading) return;
    const id = jsonSelect.value;
    if (!id) return;
    const text = getSavePayload();
    if (text == null) {
      showToast(
        "Cannot build JSON from the form. Fix invalid fields or switch to Raw JSON.",
        true
      );
      return;
    }
    try {
      JSON.parse(text);
    } catch (e) {
      showToast("Invalid JSON: " + e.message, true);
      return;
    }
    const opt = jsonSelect.options[jsonSelect.selectedIndex];
    const name = (opt && opt.getAttribute("data-file")) || id + ".json";
    const blob = new Blob([text], { type: "application/json;charset=utf-8" });
    const a = document.createElement("a");
    const url = URL.createObjectURL(blob);
    a.href = url;
    a.download = name;
    a.rel = "noopener";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function () {
      URL.revokeObjectURL(url);
    }, 2500);
    showToast("Downloaded " + name, false);
  }

  function promptAndUploadGroupJson() {
    if (jsonLoading) return;
    if (jsonDirty && !window.confirm("Discard unsaved changes and replace the editor with a file?")) {
      return;
    }
    if (jsonUploadInput) jsonUploadInput.click();
  }

  function onGroupJsonFileChosen(ev) {
    const input = ev.target;
    const file = input.files && input.files[0];
    if (!file) return;
    const id = jsonSelect.value;
    if (!id) {
      input.value = "";
      return;
    }
    const reader = new FileReader();
    reader.onload = function () {
      const text = String(reader.result || "");
      try {
        JSON.parse(text);
      } catch (e) {
        showToast("Invalid JSON: " + e.message, true);
        input.value = "";
        return;
      }
      applyGroupJsonFromText(text, id, { fromDisk: false, exists: true });
      if (!formParseError) {
        showToast("Imported — not saved. Click Save to write to the server.", false);
      }
      input.value = "";
    };
    reader.onerror = function () {
      showToast("Could not read file", true);
      input.value = "";
    };
    reader.readAsText(file);
  }

  function loadJsonFile() {
    const id = jsonSelect.value;
    if (!id) return;
    jsonLoading = true;
    if (jsonReloadBtn) jsonReloadBtn.disabled = true;
    if (jsonSaveBtn) jsonSaveBtn.disabled = true;
    if (jsonDownloadBtn) jsonDownloadBtn.disabled = true;
    if (jsonUploadBtn) jsonUploadBtn.disabled = true;
    setTopFetchButtonsDisabled(true);
    updateJsonMeta("Loading…");
    fetch("/api/json-groups/" + encodeURIComponent(id))
      .then(function (r) {
        return r.json().then(function (j) {
          return { ok: r.ok, j: j };
        });
      })
      .then(function (res) {
        if (!res.ok) {
          updateJsonMeta(res.j.error || "Load failed", true);
          showToast(res.j.error || "Load failed", true);
          return;
        }
        const j = res.j;
        const text = j.content != null ? String(j.content) : "";
        applyGroupJsonFromText(text, id, { fromDisk: true, exists: !!j.exists });
      })
      .catch(function (e) {
        updateJsonMeta(String(e), true);
        showToast(String(e), true);
      })
      .finally(function () {
        jsonLoading = false;
        if (jsonReloadBtn) jsonReloadBtn.disabled = false;
        if (jsonSaveBtn) jsonSaveBtn.disabled = !jsonDirty;
        if (jsonDownloadBtn) jsonDownloadBtn.disabled = false;
        if (jsonUploadBtn) jsonUploadBtn.disabled = false;
        setTopFetchButtonsDisabled(plexFetchBusy);
      });
  }

  function getSavePayload() {
    const id = jsonSelect.value;
    if (id === "series_groups" && !formParseError && viewMode === "form") {
      if (!readSeriesFilterTextareasIntoEntries()) {
        showToast("Fix invalid group filters JSON (red outline) before saving.", true);
        return null;
      }
      try {
        return JSON.stringify(serializeSeries(), null, 2) + "\n";
      } catch (e) {
        showToast(e.message, true);
        return null;
      }
    }
    if ((id === "genre_mixes" || id === "movie_genre_mixes") && !formParseError && viewMode === "form") {
      if (!readMixExtraAndMaxFromDom()) {
        showToast("Fix invalid other mix fields JSON (red outline) before saving.", true);
        return null;
      }
      try {
        return JSON.stringify(serializeMix(), null, 2) + "\n";
      } catch (e) {
        showToast(e.message, true);
        return null;
      }
    }
    return jsonEditor.value;
  }

  function saveJsonFile() {
    const id = jsonSelect.value;
    if (!id) return;
    const text = getSavePayload();
    if (text == null) return;
    try {
      JSON.parse(text);
    } catch (e) {
      showToast("Invalid JSON: " + e.message, true);
      return;
    }
    if (jsonSaveBtn) jsonSaveBtn.disabled = true;
    updateJsonMeta("Saving…");
    fetch("/api/json-groups/" + encodeURIComponent(id), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: text }),
    })
      .then(function (r) {
        return r.json().then(function (j) {
          return { ok: r.ok, j: j };
        });
      })
      .then(function (res) {
        if (!res.ok) {
          updateJsonMeta(res.j.error || "Save failed", true);
          showToast(res.j.error || "Save failed", true);
          if (jsonSaveBtn) jsonSaveBtn.disabled = !jsonDirty;
          return;
        }
        jsonEditor.value = text;
        baselineText = text;
        if (id === "series_groups" && !formParseError && viewMode === "form") {
          try {
            tryIngestSeriesText(text);
          } catch (e) {
            /* keep editor state */
          }
        }
        if ((id === "genre_mixes" || id === "movie_genre_mixes") && !formParseError && viewMode === "form") {
          try {
            tryIngestMixText(text);
          } catch (e) {
            /* keep editor state */
          }
        }
        setJsonDirty(false);
        updateFileOptionKeyCount();
        showToast("Saved", false);
        updateJsonMeta("Saved");
        if (typeof window.__pvpgRefreshScriptCardMeta === "function") {
          window.__pvpgRefreshScriptCardMeta();
        }
      })
      .catch(function (e) {
        updateJsonMeta(String(e), true);
        showToast(String(e), true);
      })
      .finally(function () {
        if (jsonSaveBtn) jsonSaveBtn.disabled = !jsonDirty;
      });
  }

  function formatJson() {
    const id = jsonSelect.value;
    if (id === "series_groups" && !formParseError) {
      if (viewMode === "form") {
        try {
          if (!readSeriesFilterTextareasIntoEntries()) {
            showToast("Fix invalid group filters JSON before format.", true);
            return;
          }
          const text = JSON.stringify(serializeSeries(), null, 2) + "\n";
          jsonEditor.value = text;
          const ent = parseSeriesFromObject(JSON.parse(text));
          applySeriesEntries(ent, "Reformatted (unsaved)");
          setJsonDirty(true);
          showToast("Reformatted", false);
        } catch (e) {
          showToast(e.message, true);
        }
        return;
      }
    }
    if ((id === "genre_mixes" || id === "movie_genre_mixes") && !formParseError) {
      if (viewMode === "form") {
        try {
          if (!readMixExtraAndMaxFromDom()) {
            showToast("Fix invalid other mix fields JSON before format.", true);
            return;
          }
          const text = JSON.stringify(serializeMix(), null, 2) + "\n";
          jsonEditor.value = text;
          const ent = parseMixFromObject(JSON.parse(text));
          applyMixEntries(ent, "Reformatted (unsaved)");
          setJsonDirty(true);
          showToast("Reformatted", false);
        } catch (e) {
          showToast(e.message, true);
        }
        return;
      }
    }
    try {
      const parsed = JSON.parse(jsonEditor.value);
      jsonEditor.value = JSON.stringify(parsed, null, 2) + "\n";
      setJsonDirty(jsonEditor.value !== baselineText);
      updateJsonMeta("Reformatted" + (jsonDirty ? " (unsaved)" : ""));
      showToast("Formatted", false);
    } catch (e) {
      showToast("Format: " + e.message, true);
    }
  }

  jsonEditor.addEventListener("input", function () {
    setJsonDirty(true);
    if (jsonSaveBtn) jsonSaveBtn.disabled = false;
    updateJsonMeta("Unsaved changes (raw)");
  });

  jsonSelect.addEventListener("change", function () {
    if (jsonDirty && !window.confirm("Discard unsaved changes and switch file?")) {
      jsonSelect.value = jsonSelectLockedValue;
      return;
    }
    jsonSelectLockedValue = jsonSelect.value;
    loadJsonFile();
  });

  if (jsonReloadBtn) {
    jsonReloadBtn.addEventListener("click", function () {
      if (jsonDirty && !window.confirm("Reload from disk and discard edits?")) return;
      loadJsonFile();
    });
  }
  if (jsonFormatBtn) jsonFormatBtn.addEventListener("click", formatJson);
  if (jsonSaveBtn) jsonSaveBtn.addEventListener("click", saveJsonFile);
  if (jsonDownloadBtn) jsonDownloadBtn.addEventListener("click", downloadGroupJsonFile);
  if (jsonUploadBtn) jsonUploadBtn.addEventListener("click", promptAndUploadGroupJson);
  if (jsonUploadInput) jsonUploadInput.addEventListener("change", onGroupJsonFileChosen);

  if (jsonViewFormBtn) {
    jsonViewFormBtn.addEventListener("click", function () {
      if (!supportsFormEditor() || viewMode === "form") return;
      try {
        if (isSeriesGroups()) {
          const ent = parseSeriesFromObject(JSON.parse(jsonEditor.value));
          formParseError = null;
          if (jsonVisual) jsonVisual.innerHTML = "";
          applySeriesEntries(ent, "Form view");
        } else if (isGenreMixesFile() || isMovieMixesFile()) {
          const ent = parseMixFromObject(JSON.parse(jsonEditor.value));
          formParseError = null;
          if (jsonVisual) jsonVisual.innerHTML = "";
          applyMixEntries(ent, "Form view");
        } else {
          return;
        }
        setViewMode("form");
        updateJsonMeta("Form view");
      } catch (e) {
        formParseError = e;
        showToast("Cannot show form: " + e.message, true);
      }
    });
  }

  if (jsonViewRawBtn) {
    jsonViewRawBtn.addEventListener("click", function () {
      if (!supportsFormEditor() || viewMode === "raw") return;
      try {
        if (isSeriesGroups()) {
          if (!readSeriesFilterTextareasIntoEntries()) {
            showToast("Fix invalid group filters JSON before switching to raw.", true);
            return;
          }
          jsonEditor.value = JSON.stringify(serializeSeries(), null, 2) + "\n";
        } else if (isGenreMixesFile() || isMovieMixesFile()) {
          if (!readMixExtraAndMaxFromDom()) {
            showToast("Fix invalid other mix fields JSON before switching to raw.", true);
            return;
          }
          jsonEditor.value = JSON.stringify(serializeMix(), null, 2) + "\n";
        } else {
          return;
        }
      } catch (e) {
        showToast(e.message, true);
        return;
      }
      setViewMode("raw");
      updateJsonMeta("Raw JSON (unsaved changes sync'd)");
    });
  }

  if (jsonAddGroupBtn) {
    jsonAddGroupBtn.addEventListener("click", function () {
      if (!supportsFormEditor() || formParseError) return;
      if (isSeriesGroups()) {
        const e = {
          _uid: uid(),
          name: "New group",
          series: [],
          filters: {},
          use_spotify_posters: true,
        };
        seriesEntries.push(e);
        if (jsonVisual) jsonVisual.appendChild(createGroupCard(e));
        syncTextareaFromSeries();
      } else if (isGenreMixesFile() || isMovieMixesFile()) {
        const e = {
          _uid: uid(),
          name: "New mix",
          genres: [],
          excluded_genres: [],
          _release: defaultRelease(),
          watched_status: "any",
          max_movies: null,
          mixExtra: {},
          use_spotify_posters: true,
        };
        mixEntries.push(e);
        if (jsonVisual) jsonVisual.appendChild(createMixCard(e));
        applyGroupNameFilter();
        syncTextareaFromMix();
        if (jsonSortGroupsBtn) {
          jsonSortGroupsBtn.disabled = mixEntries.length < 2;
        }
      } else {
        return;
      }
      setJsonDirty(true);
      updateJsonMeta("Unsaved changes");
      updateFileOptionKeyCount();
    });
  }

  if (jsonGroupFilter) {
    jsonGroupFilter.addEventListener("input", applyGroupNameFilter);
  }

  if (jsonSortGroupsBtn) {
    jsonSortGroupsBtn.addEventListener("click", function () {
      const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });
      if (isSeriesGroups()) {
        if (seriesEntries.length < 2) return;
        seriesEntries.sort(function (a, b) {
          return collator.compare(String(a.name).trim(), String(b.name).trim());
        });
        renderSeriesForm();
        syncTextareaFromSeries();
      } else if (isGenreMixesFile() || isMovieMixesFile()) {
        if (mixEntries.length < 2) return;
        mixEntries.sort(function (a, b) {
          return collator.compare(String(a.name).trim(), String(b.name).trim());
        });
        renderMixForm();
        syncTextareaFromMix();
      } else {
        return;
      }
      setJsonDirty(true);
      updateJsonMeta("Entries sorted A–Z (unsaved)");
      showToast("Sorted A–Z — save to write the file.", false);
    });
  }

  if (jsonFetchAllShows) {
    jsonFetchAllShows.addEventListener("click", function () {
      if (plexFetchBusy) return;
      fetchShowsFromPlex();
    });
  }

  if (jsonFetchAllMovies) {
    jsonFetchAllMovies.addEventListener("click", function () {
      if (plexFetchBusy) return;
      fetchMoviesFromPlex();
    });
  }

  if (jsonFetchAllTvGenres) {
    jsonFetchAllTvGenres.addEventListener("click", function () {
      if (plexFetchBusy) return;
      fetchTvGenresFromPlex();
    });
  }

  if (jsonFetchAllMovieGenres) {
    jsonFetchAllMovieGenres.addEventListener("click", function () {
      if (plexFetchBusy) return;
      fetchMovieGenresFromPlex();
    });
  }

  setJsonDirty(false);
  if (jsonSaveBtn) jsonSaveBtn.disabled = true;
  if (jsonViewToggle) jsonViewToggle.classList.add("hidden");
  if (jsonSeriesToolbar) jsonSeriesToolbar.classList.add("hidden");

  loadPlexTitlesFromStorage();
  loadMovieTitlesFromStorage();
  loadTvGenresFromStorage();
  loadMovieGenresFromStorage();
  updateTopCacheStatus();
  if (plexTitles.length) {
    setPlexStatus(
      plexTitles.length +
        " show titles in series picker (use Fetch all shows in the top bar to refresh from Plex)"
    );
  }

  window.__pvpgLoadJsonGroups = function () {
    loadJsonFile();
  };
  window.__pvpgJsonIsDirty = function () {
    return jsonDirty;
  };
  window.__pvpgJsonMarkClean = function () {
    setJsonDirty(false);
  };
})();
