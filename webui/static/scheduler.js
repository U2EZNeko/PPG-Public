/**
 * Scheduler tab: edit ppg_schedule.json (jobs, intervals, fixed times).
 */
(function () {
  "use strict";

  let _doc = { version: 1, jobs: [] };
  let _baseline = "";
  /** Matches SCHEDULE_UI_SCRIPT_IDS in webui/app.py; used until GET /api/schedule returns. */
  const FALLBACK_SCRIPTS = [
    { id: "daily", label: "PPG-Daily.py" },
    { id: "weekly", label: "PPG-Weekly.py" },
    { id: "moods", label: "PPG-Moods.py" },
    { id: "genres", label: "PPG-Genres.py" },
    { id: "fetch_liked", label: "fetch-liked-artists.py" },
    { id: "liked_artists", label: "PPG-LikedArtists.py" },
    { id: "liked_artists_collection", label: "PPG-LikedArtistsCollection.py" },
  ];
  let _scripts = FALLBACK_SCRIPTS.slice();
  let _jobStatus = [];
  let viewMode = "form";

  const jobsEl = document.getElementById("schedule-jobs");
  const rawEl = document.getElementById("schedule-raw");
  const metaEl = document.getElementById("schedule-meta");
  const daemonStatusEl = document.getElementById("schedule-daemon-status");
  let statusPollTimer = null;
  let runLogPollTimer = null;
  const viewFormBtn = document.getElementById("schedule-view-form");
  const viewRawBtn = document.getElementById("schedule-view-raw");

  const WEEKDAYS = [
    ["mon", "Monday"],
    ["tue", "Tuesday"],
    ["wed", "Wednesday"],
    ["thu", "Thursday"],
    ["fri", "Friday"],
    ["sat", "Saturday"],
    ["sun", "Sunday"],
  ];

  const SCHEDULE_TYPES = [
    ["interval", "Every N minutes"],
    ["hourly", "Hourly"],
    ["daily", "Daily at time"],
    ["weekly", "Weekly"],
    ["cron", "Cron expression"],
  ];

  function toast(msg, isErr) {
    if (typeof window.__ppgShowToast === "function") {
      window.__ppgShowToast(msg, isErr);
    }
  }

  function parseJsonResponse(r) {
    const ct = (r.headers.get("content-type") || "").toLowerCase();
    if (ct.indexOf("application/json") === -1) {
      return r.text().then(function (text) {
        const snippet = (text || "").replace(/\s+/g, " ").trim().slice(0, 120);
        const hint =
          r.status === 404 || r.status === 405
            ? " Restart the PPG web UI so /api/schedule is available."
            : "";
        throw new Error(
          "Server returned " +
            r.status +
            " (" +
            (ct || "non-JSON") +
            "), not JSON." +
            hint +
            (snippet ? " " + snippet : "")
        );
      });
    }
    return r.json().then(function (data) {
      if (!r.ok) {
        throw new Error(
          (data && (data.error || data.message)) || r.statusText || "Request failed"
        );
      }
      return data;
    });
  }

  function esc(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/"/g, "&quot;");
  }

  function serializeDoc() {
    return JSON.stringify(_doc, null, 4);
  }

  function isDirty() {
    return serializeDoc() !== _baseline;
  }

  function statusForJob(id) {
    return _jobStatus.find(function (r) {
      return r.id === id;
    });
  }

  function jobShowsRunLog(st) {
    if (st.running) return true;
    if (st.last_exit_code === 0 || st.last_exit_code === "0") return false;
    return !!st.has_log;
  }

  function anyJobRunning() {
    return _jobStatus.some(function (r) {
      return !!r.running;
    });
  }

  function anyJobLogPolling() {
    return anyJobRunning();
  }

  function anyJobShowsRunLog() {
    return _jobStatus.some(jobShowsRunLog);
  }

  function buildScheduleFromCard(card) {
    const type = card.querySelector(".sched-type")?.value || "daily";
    const sch = { type: type };
    if (type === "interval") {
      sch.every_minutes = parseInt(
        card.querySelector(".sched-interval-min")?.value || "60",
        10
      );
    } else if (type === "hourly") {
      sch.at_minute = parseInt(
        card.querySelector(".sched-hourly-minute")?.value || "0",
        10
      );
    } else if (type === "daily") {
      sch.at = fromTimeInput(card.querySelector(".sched-daily-at")?.value);
      if (card.querySelector(".sched-first-run-tomorrow")?.checked) {
        sch.first_run_tomorrow = true;
      }
    } else if (type === "weekly") {
      sch.weekday = card.querySelector(".sched-weekday")?.value || "mon";
      sch.at = fromTimeInput(card.querySelector(".sched-weekly-at")?.value);
    } else if (type === "cron") {
      sch.expression =
        card.querySelector(".sched-cron-expr")?.value || "0 * * * *";
    }
    return sch;
  }

  function collectJobsFromForm() {
    const jobs = [];
    jobsEl.querySelectorAll(".schedule-job").forEach(function (card) {
      const id = (card.querySelector(".sched-id")?.value || "").trim();
      if (!id) return;
      const script = card.querySelector(".sched-script")?.value || "sorted";
      const enabled = !!card.querySelector(".sched-enabled")?.checked;
      jobs.push({
        id: id,
        script: script,
        enabled: enabled,
        schedule: buildScheduleFromCard(card),
      });
    });
    return jobs;
  }

  function syncDocFromForm() {
    _doc.jobs = collectJobsFromForm();
  }

  function syncDocFromRaw() {
    try {
      const parsed = JSON.parse(rawEl.value);
      if (!parsed || typeof parsed !== "object") throw new Error("Not an object");
      _doc = {
        version: parsed.version != null ? parsed.version : 1,
        jobs: Array.isArray(parsed.jobs) ? parsed.jobs : [],
      };
    } catch (e) {
      throw e;
    }
  }

  function parseTime24(val) {
    const m = String(val || "").trim().match(/^(\d{1,2}):(\d{2})$/);
    if (!m) return null;
    const h = parseInt(m[1], 10);
    const min = parseInt(m[2], 10);
    if (h < 0 || h > 23 || min < 0 || min > 59) return null;
    return (
      String(h).padStart(2, "0") + ":" + String(min).padStart(2, "0")
    );
  }

  function use24h() {
    if (typeof window.__ppgUse24hTime === "function") {
      return !!window.__ppgUse24hTime();
    }
    return true;
  }

  function time24InputHtml(className, at) {
    const v = esc(toTimeInput(at));
    return (
      '<label>Time <input type="text" class="' +
      esc(className) +
      ' sched-at-24" inputmode="numeric" autocomplete="off" spellcheck="false" ' +
      'placeholder="HH:MM" pattern="([01][0-9]|2[0-3]):[0-5][0-9]" maxlength="5" ' +
      'title="24-hour time (00:00–23:59)" value="' +
      v +
      '" /></label>'
    );
  }

  function timeInputHtml(className, at) {
    if (use24h()) return time24InputHtml(className, at);
    return (
      '<label>Time <input type="time" class="' +
      esc(className) +
      '" value="' +
      esc(toTimeInput(at)) +
      '" /></label>'
    );
  }

  function formatDisplayTime(str) {
    if (typeof window.__ppgFormatScheduleTime === "function") {
      return window.__ppgFormatScheduleTime(str);
    }
    return str;
  }

  function scheduleFieldsHtml(sch) {
    const type = (sch && sch.type) || "daily";
    let inner = "";
    inner +=
      '<label class="sched-field-label">Schedule type<select class="sched-type">';
    SCHEDULE_TYPES.forEach(function (pair) {
      inner +=
        '<option value="' +
        esc(pair[0]) +
        '"' +
        (pair[0] === type ? " selected" : "") +
        ">" +
        esc(pair[1]) +
        "</option>";
    });
    inner += "</select></label>";
    inner += '<div class="sched-fields-body">';
    inner +=
      '<div class="sched-fields sched-fields-interval' +
      (type === "interval" ? "" : " hidden") +
      '"><label>Every <input type="number" class="sched-interval-min" min="1" max="10080" value="' +
      esc(String(sch.every_minutes || sch.minutes || 60)) +
      '" /> minutes</label></div>';
    inner +=
      '<div class="sched-fields sched-fields-hourly' +
      (type === "hourly" ? "" : " hidden") +
      '"><label>At minute <input type="number" class="sched-hourly-minute" min="0" max="59" value="' +
      esc(String(sch.at_minute != null ? sch.at_minute : sch.minute != null ? sch.minute : 0)) +
      '" /> (0–59)</label></div>';
    inner +=
      '<div class="sched-fields sched-fields-daily' +
      (type === "daily" ? "" : " hidden") +
      '">' +
      timeInputHtml("sched-daily-at", sch.at || sch.time || "03:00") +
      '<label class="sched-first-run-tomorrow-wrap">' +
      '<input type="checkbox" class="sched-first-run-tomorrow"' +
      (sch.first_run_tomorrow ? " checked" : "") +
      " />" +
      " First run tomorrow if today's time has already passed</label>" +
      "</div>";
    inner +=
      '<div class="sched-fields sched-fields-weekly' +
      (type === "weekly" ? "" : " hidden") +
      '"><label>Weekday <select class="sched-weekday">';
    WEEKDAYS.forEach(function (pair) {
      const sel =
        String(sch.weekday || sch.day || "mon").toLowerCase() === pair[0]
          ? " selected"
          : "";
      inner +=
        '<option value="' + pair[0] + '"' + sel + ">" + esc(pair[1]) + "</option>";
    });
    inner +=
      "</select></label>" +
      timeInputHtml("sched-weekly-at", sch.at || sch.time || "03:00") +
      "</div>";
    inner +=
      '<div class="sched-fields sched-fields-cron' +
      (type === "cron" ? "" : " hidden") +
      '"><label>Cron <input type="text" class="sched-cron-expr" placeholder="0 * * * *" value="' +
      esc(sch.expression || sch.cron || "") +
      '" /></label><span class="sched-hint">Five fields (minute hour dom month dow). Needs croniter on the server.</span></div>';
    inner += "</div>";
    return inner;
  }

  function toTimeInput(at) {
    const m = String(at || "03:00").match(/^(\d{1,2}):(\d{2})$/);
    if (!m) return "03:00";
    return (
      String(parseInt(m[1], 10)).padStart(2, "0") +
      ":" +
      String(parseInt(m[2], 10)).padStart(2, "0")
    );
  }

  function fromTimeInput(val) {
    return parseTime24(val) || "03:00";
  }

  function normalizeTimeInput(inp) {
    if (!inp) return;
    if (inp.type === "time") {
      if (inp.value) inp.value = fromTimeInput(inp.value);
      return;
    }
    const norm = parseTime24(inp.value);
    if (norm) inp.value = norm;
  }

  function scriptIdForSelect(scriptId) {
    return String(scriptId || "").trim();
  }

  function scriptsForUi() {
    return _scripts.length ? _scripts : FALLBACK_SCRIPTS;
  }

  function jobCardHtml(job, idx) {
    const st = statusForJob(job.id) || {};
    const selectedScript = scriptIdForSelect(job.script);
    const scriptOpts = scriptsForUi()
      .map(function (s) {
        return (
          '<option value="' +
          esc(s.id) +
          '"' +
          (s.id === selectedScript ? " selected" : "") +
          ">" +
          esc(s.label) +
          "</option>"
        );
      })
      .join("");
    let statusLine = "";
    let runLogHtml = "";
    const showLog = jobShowsRunLog(st);
    if (st.running) {
      statusLine = "Running";
      if (st.last_started) {
        statusLine += " since " + esc(formatDisplayTime(st.last_started));
      }
    } else if (st.due_now) {
      statusLine += "Due now";
    } else if (st.next_run) {
      statusLine += "Next: " + esc(formatDisplayTime(st.next_run));
    } else if (job.enabled === false) {
      statusLine += "Next: — (disabled)";
    }
    if (!st.running && st.last_finished) {
      statusLine +=
        (statusLine ? " · " : "") +
        "Last: " +
        esc(formatDisplayTime(st.last_finished)) +
        (st.last_exit_code != null ? " (exit " + st.last_exit_code + ")" : "");
    }
    if (showLog) {
      runLogHtml =
        '<pre class="sched-run-log" data-job-id="' +
        esc(job.id) +
        '" aria-live="polite">Loading output…</pre>';
    }
    return (
      '<article class="schedule-job" data-idx="' +
      idx +
      '">' +
      '<div class="schedule-job-head">' +
      '<label>Job id <input type="text" class="sched-id" value="' +
      esc(job.id) +
      '" autocomplete="off" /></label>' +
      '<label class="sched-enabled-wrap"><input type="checkbox" class="sched-enabled"' +
      (job.enabled !== false ? " checked" : "") +
      " /> Enabled</label>" +
      '<button type="button" class="sched-remove danger" title="Remove job">Remove</button>' +
      "</div>" +
      '<label>Script <select class="sched-script">' +
      scriptOpts +
      "</select></label>" +
      scheduleFieldsHtml(job.schedule || { type: "daily", at: "03:00" }) +
      (statusLine
        ? '<p class="schedule-job-status' +
          (st.running ? " schedule-job-status--running" : "") +
          '">' +
          statusLine +
          "</p>"
        : "") +
      runLogHtml +
      "</article>"
    );
  }

  function renderForm() {
    if (!jobsEl) return;
    if (!_doc.jobs.length) {
      jobsEl.innerHTML =
        '<p class="schedule-empty">No jobs yet. Click <strong>Add job</strong> or switch to Raw JSON.</p>';
      return;
    }
    jobsEl.innerHTML = _doc.jobs
      .map(function (job, i) {
        return jobCardHtml(job, i);
      })
      .join("");
    bindJobCards();
    refreshRunningJobUi();
  }

  function refreshRunningJobUi() {
    if (anyJobLogPolling()) startRunLogPoll();
    else {
      stopRunLogPoll();
      if (anyJobShowsRunLog()) updateRunLogPanels();
    }
  }

  function updateScheduleTypeVisibility(card) {
    const type = card.querySelector(".sched-type")?.value || "daily";
    card.querySelectorAll(".sched-fields").forEach(function (el) {
      el.classList.add("hidden");
    });
    const show = card.querySelector(".sched-fields-" + type);
    if (show) show.classList.remove("hidden");
  }

  function bindJobCards() {
    jobsEl.querySelectorAll(".schedule-job").forEach(function (card) {
      card.querySelector(".sched-type")?.addEventListener("change", function () {
        updateScheduleTypeVisibility(card);
        syncDocFromForm();
      });
      card.querySelectorAll("input, select").forEach(function (inp) {
        inp.addEventListener("change", function () {
          if (
            inp.classList.contains("sched-daily-at") ||
            inp.classList.contains("sched-weekly-at")
          ) {
            normalizeTimeInput(inp);
          }
          syncDocFromForm();
        });
        if (
          inp.classList.contains("sched-daily-at") ||
          inp.classList.contains("sched-weekly-at")
        ) {
          inp.addEventListener("blur", function () {
            normalizeTimeInput(inp);
          });
        }
      });
      card.querySelector(".sched-remove")?.addEventListener("click", function () {
        card.remove();
        syncDocFromForm();
        renderForm();
      });
    });
  }

  function setView(mode) {
    viewMode = mode;
    const formOn = mode === "form";
    if (viewFormBtn) viewFormBtn.classList.toggle("active", formOn);
    if (viewRawBtn) viewRawBtn.classList.toggle("active", !formOn);
    if (jobsEl) jobsEl.classList.toggle("hidden", !formOn);
    if (rawEl) {
      rawEl.classList.toggle("hidden", formOn);
      if (!formOn) rawEl.value = serializeDoc();
    }
  }

  function updateRunLogPanels() {
    if (!jobsEl) return;
    jobsEl.querySelectorAll(".sched-run-log").forEach(function (pre) {
      const card = pre.closest(".schedule-job");
      const jobId =
        (card && card.querySelector(".sched-id")?.value?.trim()) ||
        pre.getAttribute("data-job-id");
      if (!jobId) return;
      fetch("/api/schedule/run-log/" + encodeURIComponent(jobId) + "?tail=120")
        .then(function (r) {
          return r.json().then(function (data) {
            if (!r.ok) throw new Error(data.error || r.statusText);
            return data;
          });
        })
        .then(function (data) {
          const lines = data.lines || [];
          if (lines.length) {
            pre.textContent = lines.join("\n");
          } else if (data.running) {
            pre.textContent = data.exists
              ? "(waiting for output — scripts may be quiet until they hit Plex or a playlist step)"
              : "(no log file yet — restart the ppg-scheduler service so job output is mirrored to webui/data/scheduler_runs/)";
          } else {
            pre.textContent = "(no mirrored log for this job yet)";
          }
          pre.scrollTop = pre.scrollHeight;
        })
        .catch(function (err) {
          pre.textContent =
            "(could not load run log" +
            (err && err.message ? ": " + err.message : "") +
            ")";
        });
    });
  }

  function stopRunLogPoll() {
    if (runLogPollTimer) {
      clearInterval(runLogPollTimer);
      runLogPollTimer = null;
    }
  }

  function startRunLogPoll() {
    updateRunLogPanels();
    if (runLogPollTimer) return;
    runLogPollTimer = setInterval(function () {
      updateRunLogPanels();
      fetch("/api/schedule")
        .then(function (r) {
          return r.json().then(function (data) {
            if (!r.ok) throw new Error(data.error || r.statusText);
            return data;
          });
        })
        .then(function (data) {
          _jobStatus = Array.isArray(data.job_status) ? data.job_status : [];
          if (!anyJobLogPolling()) {
            stopRunLogPoll();
            applyPayload(data);
          }
        })
        .catch(function () {});
    }, 2000);
  }

  function applyPayload(data) {
    _scripts =
      Array.isArray(data.scripts) && data.scripts.length
        ? data.scripts
        : FALLBACK_SCRIPTS.slice();
    _jobStatus = Array.isArray(data.job_status) ? data.job_status : [];
    _doc = {
      version: data.version != null ? data.version : 1,
      jobs: Array.isArray(data.jobs) ? data.jobs : [],
    };
    _baseline = serializeDoc();
    if (metaEl) {
      let meta = data.file ? "File: " + data.file : "";
      if (data.error) meta += (meta ? " · " : "") + "⚠ " + data.error;
      else if (!data.exists) meta += (meta ? " · " : "") + "Not created yet — save to create.";
      metaEl.textContent = meta;
    }
    if (viewMode === "form") renderForm();
    else if (rawEl) rawEl.value = serializeDoc();
    else refreshRunningJobUi();
  }

  function renderDaemonStatus(data) {
    if (!daemonStatusEl) return;
    daemonStatusEl.classList.remove(
      "schedule-daemon-status--running",
      "schedule-daemon-status--stopped",
      "schedule-daemon-status--unknown"
    );
    const running = data && data.running;
    if (running === true) {
      daemonStatusEl.classList.add("schedule-daemon-status--running");
      daemonStatusEl.textContent = "Scheduler running";
    } else if (running === false) {
      daemonStatusEl.classList.add("schedule-daemon-status--stopped");
      daemonStatusEl.textContent = "Scheduler stopped";
    } else {
      daemonStatusEl.classList.add("schedule-daemon-status--unknown");
      daemonStatusEl.textContent = "Scheduler status unknown";
    }
    daemonStatusEl.title = (data && data.detail) || "";
  }

  function refreshDaemonStatus() {
    return fetch("/api/scheduler/status")
      .then(function (r) {
        return r.json().then(function (data) {
          if (!r.ok) throw new Error(data.error || r.statusText);
          return data;
        });
      })
      .then(renderDaemonStatus)
      .catch(function () {
        renderDaemonStatus({ running: null, detail: "Could not reach status API" });
      });
  }

  function startStatusPoll() {
    if (statusPollTimer) clearInterval(statusPollTimer);
    refreshDaemonStatus();
    statusPollTimer = setInterval(refreshDaemonStatus, 15000);
  }

  function stopStatusPoll() {
    if (statusPollTimer) {
      clearInterval(statusPollTimer);
      statusPollTimer = null;
    }
    stopRunLogPoll();
  }

  function loadSchedule() {
    return fetch("/api/schedule")
      .then(parseJsonResponse)
      .then(function (data) {
        applyPayload(data);
      })
      .catch(function (e) {
        _scripts = FALLBACK_SCRIPTS.slice();
        toast("Failed to load schedule: " + e.message, true);
        if (viewMode === "form") renderForm();
      });
  }

  function saveSchedule() {
    try {
      if (viewMode === "raw") {
        syncDocFromRaw();
      } else {
        syncDocFromForm();
        _doc.jobs.forEach(function (job) {
          const card = Array.from(jobsEl.querySelectorAll(".schedule-job")).find(
            function (c) {
              return c.querySelector(".sched-id")?.value.trim() === job.id;
            }
          );
          if (card) {
            const sch = job.schedule;
            if (sch.type === "daily" && card.querySelector(".sched-daily-at")) {
              sch.at = fromTimeInput(card.querySelector(".sched-daily-at").value);
            }
            if (sch.type === "weekly" && card.querySelector(".sched-weekly-at")) {
              sch.at = fromTimeInput(card.querySelector(".sched-weekly-at").value);
            }
          }
        });
      }
    } catch (e) {
      toast("Invalid JSON: " + e.message, true);
      return Promise.resolve();
    }
    return fetch("/api/schedule", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(_doc),
    })
      .then(parseJsonResponse)
      .then(function (data) {
        if (data.warning) toast(data.warning, true);
        applyPayload(data);
        toast("Schedule saved.");
      })
      .catch(function (e) {
        toast("Save failed: " + e.message, true);
      });
  }

  function addJob() {
    syncDocFromForm();
    const n = _doc.jobs.length + 1;
    _doc.jobs.push({
      id: "job-" + n,
      script: "daily",
      enabled: true,
      schedule: { type: "hourly", at_minute: 0 },
    });
    renderForm();
    setView("form");
  }

  if (viewFormBtn) {
    viewFormBtn.addEventListener("click", function () {
      if (viewMode === "raw") {
        try {
          syncDocFromRaw();
        } catch (e) {
          toast("Fix JSON before switching to form: " + e.message, true);
          return;
        }
      }
      setView("form");
      renderForm();
    });
  }
  if (viewRawBtn) {
    viewRawBtn.addEventListener("click", function () {
      syncDocFromForm();
      setView("raw");
    });
  }

  const reloadBtn = document.getElementById("schedule-reload");
  if (reloadBtn) {
    reloadBtn.addEventListener("click", function () {
      if (isDirty() && !window.confirm("Discard unsaved schedule changes?")) return;
      loadSchedule();
      refreshDaemonStatus();
    });
  }
  const saveBtn = document.getElementById("schedule-save");
  if (saveBtn) saveBtn.addEventListener("click", saveSchedule);
  const addBtn = document.getElementById("schedule-add-job");
  if (addBtn) addBtn.addEventListener("click", addJob);

  window.__ppgLoadSchedule = function () {
    startStatusPoll();
    return loadSchedule();
  };
  window.__ppgSchedulerTabHidden = stopStatusPoll;
  window.__ppgScheduleIsDirty = isDirty;
  window.__ppgScheduleMarkClean = function () {
    _baseline = serializeDoc();
  };
  window.__ppgScheduleRevert = function () {
    try {
      _doc = JSON.parse(_baseline);
    } catch (e) {
      _doc = { version: 1, jobs: [] };
    }
    renderForm();
    if (rawEl) rawEl.value = _baseline;
  };

  window.addEventListener("ppg-time-format-change", function () {
    if (viewMode !== "form" || !jobsEl || !_doc.jobs.length) return;
    syncDocFromForm();
    renderForm();
  });
})();
