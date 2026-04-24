/**
 * Configs tab: parse .env into labeled inputs, or edit full text in raw mode.
 */
(function () {
  "use strict";

  let _items = [];
  let _baselineText = "";
  let envViewMode = "form";

  const envRaw = document.getElementById("env-raw");
  const envViewFormBtn = document.getElementById("env-view-form");
  const envViewRawBtn = document.getElementById("env-view-raw");
  const envFilter = document.getElementById("env-filter");

  function toast(msg, isErr) {
    if (typeof window.__pvpgShowToast === "function") {
      window.__pvpgShowToast(msg, isErr);
    }
  }

  function parseEnv(content) {
    const lines = String(content).split(/\n/);
    const items = [];
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i].replace(/\r$/, "");
      const trimmed = line.trim();
      if (!trimmed) {
        items.push({ t: "blank", line: line });
        continue;
      }
      if (/^\s*#/.test(line)) {
        items.push({ t: "comment", line: line });
        continue;
      }
      const eq = line.indexOf("=");
      if (eq <= 0) {
        items.push({ t: "raw", line: line });
        continue;
      }
      const beforeEq = line.slice(0, eq);
      const bm = beforeEq.match(/^(\s*)(.+)$/);
      if (!bm) {
        items.push({ t: "raw", line: line });
        continue;
      }
      const keyIndent = bm[1];
      const key = bm[2].trim();
      if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(key)) {
        items.push({ t: "raw", line: line });
        continue;
      }
      const tail = line.slice(eq + 1);
      const sm = tail.match(/^(.*?)(\s+#.*)$/);
      const value = sm ? sm[1].trimEnd() : tail;
      const suffix = sm ? sm[2] : "";
      items.push({
        t: "entry",
        key: key,
        value: value,
        suffix: suffix,
        keyIndent: keyIndent,
      });
    }
    return items;
  }

  function serializeFromDomItems(items) {
    return items
      .map(function (it, idx) {
        if (it.t === "blank" || it.t === "comment" || it.t === "raw") {
          return it.line;
        }
        const inp = document.querySelector(
          '#env-form input[data-env-idx="' + idx + '"]'
        );
        const v = inp ? inp.value : it.value;
        return it.keyIndent + it.key + "=" + v + it.suffix;
      })
      .join("\n");
  }

  function getCurrentText() {
    if (envViewMode === "raw" && envRaw) {
      return String(envRaw.value);
    }
    return serializeFromDomItems(_items);
  }

  function envDirty() {
    return getCurrentText() !== _baselineText;
  }

  function applyFilter() {
    if (envViewMode === "raw") return;
    const inp = document.getElementById("env-filter");
    const q = ((inp && inp.value) || "").trim().toLowerCase();
    document.querySelectorAll("#env-form .env-row").forEach(function (row) {
      const key = (row.getAttribute("data-env-key") || "").toLowerCase();
      if (!q || key.indexOf(q) !== -1) {
        row.classList.remove("hidden-by-filter");
      } else {
        row.classList.add("hidden-by-filter");
      }
    });
  }

  function renderForm(items) {
    const form = document.getElementById("env-form");
    if (!form) return;
    form.innerHTML = "";
    items.forEach(function (it, idx) {
      if (it.t === "comment") {
        const el = document.createElement("div");
        el.className = "env-line-comment";
        el.textContent = it.line;
        form.appendChild(el);
        return;
      }
      if (it.t === "blank") {
        const el = document.createElement("div");
        el.className = "env-line-blank";
        el.setAttribute("aria-hidden", "true");
        form.appendChild(el);
        return;
      }
      if (it.t === "raw") {
        const el = document.createElement("div");
        el.className = "env-line-raw";
        const lab = document.createElement("span");
        lab.className = "env-raw-label";
        lab.textContent = "Unparsed line";
        const pre = document.createElement("pre");
        pre.className = "env-raw-pre";
        pre.textContent = it.line;
        el.appendChild(lab);
        el.appendChild(pre);
        form.appendChild(el);
        return;
      }
      const row = document.createElement("div");
      row.className = "env-row";
      row.setAttribute("data-env-key", it.key);
      const lab = document.createElement("label");
      lab.htmlFor = "env-inp-" + idx;
      lab.textContent = it.key;
      const wrap = document.createElement("div");
      wrap.className = "env-input-wrap";
      const input = document.createElement("input");
      input.type = "text";
      input.id = "env-inp-" + idx;
      input.setAttribute("data-env-idx", String(idx));
      input.value = it.value;
      input.autocomplete = "off";
      input.spellcheck = false;
      wrap.appendChild(input);
      if (it.suffix) {
        const hint = document.createElement("span");
        hint.className = "env-inline-hint";
        hint.textContent = it.suffix.replace(/^\s+/, "");
        wrap.appendChild(hint);
      }
      row.appendChild(lab);
      row.appendChild(wrap);
      form.appendChild(row);
    });
    applyFilter();
  }

  function parseAndRender(text) {
    _items = parseEnv(text);
    renderForm(_items);
  }

  function setEnvViewMode(mode) {
    const wantRaw = mode === "raw";
    const form = document.getElementById("env-form");
    if (wantRaw) {
      if (envViewMode === "form" && envRaw) {
        envRaw.value = serializeFromDomItems(_items);
      }
    } else {
      if (envViewMode === "raw" && envRaw) {
        parseAndRender(String(envRaw.value));
      }
    }
    envViewMode = wantRaw ? "raw" : "form";
    if (form) form.classList.toggle("hidden", wantRaw);
    if (envRaw) envRaw.classList.toggle("hidden", !wantRaw);
    if (envViewFormBtn) envViewFormBtn.classList.toggle("active", !wantRaw);
    if (envViewRawBtn) envViewRawBtn.classList.toggle("active", wantRaw);
    if (envFilter) {
      envFilter.disabled = wantRaw;
      if (wantRaw) {
        envFilter.classList.add("hidden");
      } else {
        envFilter.classList.remove("hidden");
        applyFilter();
      }
    }
  }

  /** Form view chrome only (no form↔raw parse) — e.g. after load replaces content. */
  function showFormViewChrome() {
    envViewMode = "form";
    const form = document.getElementById("env-form");
    if (form) form.classList.remove("hidden");
    if (envRaw) envRaw.classList.add("hidden");
    if (envViewFormBtn) envViewFormBtn.classList.add("active");
    if (envViewRawBtn) envViewRawBtn.classList.remove("active");
    if (envFilter) {
      envFilter.disabled = false;
      envFilter.classList.remove("hidden");
    }
  }

  function syncTextareaWithBaselineText(text) {
    if (envRaw) {
      envRaw.value = String(text);
    }
  }

  async function loadEnv() {
    const meta = document.getElementById("env-meta");
    if (!meta) return;
    meta.classList.remove("warn");
    meta.textContent = "Loading…";
    showFormViewChrome();
    try {
      const r = await fetch("/api/dotenv");
      const j = await r.json();
      if (!r.ok) {
        meta.textContent = j.error || "Error";
        meta.classList.add("warn");
        return;
      }
      const text = j.content != null ? j.content : "";
      _baselineText = text;
      parseAndRender(text);
      syncTextareaWithBaselineText(text);
      const n = _items.filter(function (x) {
        return x.t === "entry";
      }).length;
      meta.textContent = j.exists
        ? ".env — " +
          n +
          " variable" +
          (n === 1 ? "" : "s") +
          ". Contains secrets; use only on a trusted machine."
        : ".env not found — Save will create it (" +
          n +
          " field" +
          (n === 1 ? "" : "s") +
          " in form / raw editor).";
    } catch (e) {
      meta.textContent = String(e);
      meta.classList.add("warn");
    }
  }

  async function saveEnv() {
    const meta = document.getElementById("env-meta");
    if (!meta) return;
    const body = getCurrentText();
    meta.classList.remove("warn");
    meta.textContent = "Saving…";
    try {
      const r = await fetch("/api/dotenv", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: body }),
      });
      const j = await r.json().catch(function () {
        return {};
      });
      if (!r.ok) {
        meta.textContent = j.error || "Save failed";
        meta.classList.add("warn");
        toast(j.error || "Save failed", true);
        return;
      }
      _baselineText = body;
      parseAndRender(body);
      syncTextareaWithBaselineText(body);
      const n = _items.filter(function (x) {
        return x.t === "entry";
      }).length;
      meta.textContent = "Saved .env (" + n + " variable" + (n === 1 ? "" : "s") + ").";
      toast(".env saved");
      if (typeof window.__pvpgRefreshScriptCardMeta === "function") {
        window.__pvpgRefreshScriptCardMeta();
      }
    } catch (e) {
      meta.textContent = String(e);
      meta.classList.add("warn");
      toast(String(e), true);
    }
  }

  function revertDiscard() {
    parseAndRender(_baselineText);
    syncTextareaWithBaselineText(_baselineText);
    showFormViewChrome();
  }

  window.__pvpgEnvIsDirty = envDirty;
  window.__pvpgLoadEnvConfigs = loadEnv;
  window.__pvpgEnvRevertDiscard = revertDiscard;

  function init() {
    document.getElementById("env-reload")?.addEventListener("click", function () {
      if (envDirty()) {
        if (!window.confirm("Reload .env from disk and discard unsaved edits?")) return;
      }
      loadEnv();
    });
    document.getElementById("env-save")?.addEventListener("click", saveEnv);
    document.getElementById("env-filter")?.addEventListener("input", applyFilter);

    envViewFormBtn?.addEventListener("click", function () {
      if (envViewMode === "form") return;
      setEnvViewMode("form");
    });
    envViewRawBtn?.addEventListener("click", function () {
      if (envViewMode === "raw") return;
      setEnvViewMode("raw");
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
