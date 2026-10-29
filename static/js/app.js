(function () {
  const $ = (s, el = document) => el.querySelector(s);
  const fmt = (n) => Number(n || 0).toLocaleString();
  const C = window.M1_COLORS, B = window.M1_BRAND;
  $("#yr").textContent = new Date().getFullYear();

  Chart.defaults.font.family = "Inter, system-ui, sans-serif";
  Chart.defaults.color = B.gray;
  let charts = {}, map, layer;

  const form = $("#lead-form");
  const btn = $("#submit-btn");

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    clearErrors();
    const fd = new FormData(form);
    const body = {
      name: fd.get("name"), email: fd.get("email"), dealership: fd.get("dealership"),
      zip: fd.get("zip"), radius: fd.get("radius"),
      condition: fd.getAll("condition"), vehicle_type: fd.getAll("vehicle_type"),
    };
    btn.disabled = true; btn.innerHTML = "Building your report…";
    try {
      const r = await fetch("/api/report", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      let j;
      try { j = await r.json(); } catch { j = { ok: false, errors: { zip: `Server returned ${r.status} ${r.statusText} — check Render logs.` } }; }
      if (!j.ok) { showErrors(j.errors || { zip: "Something went wrong." }); return; }
      try { render(j, body); } catch (err) { console.error(err); showErrors({ zip: "Display error: " + err.message + " (your PDF is still available)" }); $("#results").hidden = false; $("#pdf-link").href = j.pdf_url; }
    } catch (err) {
      showErrors({ zip: "Network error: " + (err && err.message ? err.message : "request failed") });
    } finally {
      btn.disabled = false; btn.innerHTML = 'Show my market <span class="arrow">→</span>';
    }
  });

  function clearErrors() {
    form.querySelectorAll("label.invalid").forEach((l) => { l.classList.remove("invalid"); l.querySelector(".err").textContent = ""; });
  }
  function showErrors(errors) {
    for (const [k, msg] of Object.entries(errors)) {
      const input = form.querySelector(`[name="${k}"]`);
      if (!input) continue;
      const label = input.closest("label");
      label.classList.add("invalid"); label.querySelector(".err").textContent = msg;
    }
  }

  function render(j, body) {
    const r = j.result, c = r.center, bc = r.by_condition;
    $("#results").hidden = false;
    $("#r-title").textContent = `${fmt(r.total_shoppers)} in-market shoppers within ${r.radius_mi} miles of ${body.dealership}`;
    $("#r-sub").textContent = `${c.city}, ${c.state} ${c.zip} · ${(body.condition.length ? body.condition.join(" & ") : "New & Used")} · ${r.zip_count} ZIP codes`;
    $("#pdf-link").href = j.pdf_url;
    $("#email-note").textContent = j.emailed ? `A copy was emailed to ${body.email}.` : "";
    $("#k-total").textContent = fmt(r.total_shoppers);
    $("#k-new").textContent = fmt(bc.New);
    $("#k-used").textContent = fmt(bc.Used);
    $("#k-zips").textContent = fmt(r.zip_count);

    // --- stacked bar by vehicle type
    const types = Object.keys(r.by_type_condition);
    mk("type", "bar", {
      labels: types,
      datasets: ["New", "Used"].map((cond, i) => ({ label: cond, data: types.map((t) => r.by_type_condition[t][cond] || 0), backgroundColor: C[i], borderRadius: 4 })),
    }, { scales: { x: { stacked: true, grid: { display: false } }, y: { stacked: true, grid: { color: "#F3F4F6" }, ticks: { callback: fmt } } }, plugins: { legend: { position: "bottom" } } });

    // --- donut new vs used
    mk("cond", "doughnut", {
      labels: Object.keys(bc), datasets: [{ data: Object.values(bc), backgroundColor: C, borderWidth: 0 }],
    }, { cutout: "68%", plugins: { legend: { position: "bottom" } } });

    // --- rings
    const rings = Object.keys(r.by_ring);
    mk("ring", "bar", {
      labels: rings.map((k) => k + " mi"), datasets: [{ data: Object.values(r.by_ring), backgroundColor: B.teal, borderRadius: 4, maxBarThickness: 48 }],
    }, { plugins: { legend: { display: false } }, scales: { x: { grid: { display: false } }, y: { grid: { color: "#F3F4F6" }, ticks: { callback: fmt } } } });

    // --- map (never fatal: charts and tables render even if tiles/Leaflet fail)
    try { drawMap(r, c, body); } catch (e) { console.error("map", e); }

    // --- table
    const tb = $("#t-zips tbody"); tb.innerHTML = "";
    r.top_zips.forEach((z) => {
      tb.insertAdjacentHTML("beforeend", `<tr><td>${z.zip}</td><td>${z.city || ""}</td><td>${z.state || ""}</td><td class="r">${z.distance_mi}</td><td class="r">${fmt(z.shoppers)}</td></tr>`);
    });

    const msa = Object.entries(r.by_msa || {});
    $("#msa-card").hidden = !msa.length;
    const tm = $("#t-msa tbody"); tm.innerHTML = "";
    msa.forEach(([m, v]) => tm.insertAdjacentHTML("beforeend", `<tr><td>${m}</td><td class="r">${fmt(v)}</td><td class="r">${(100 * v / Math.max(r.total_shoppers, 1)).toFixed(1)}%</td></tr>`));

    $("#results").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function drawMap(r, c, body) {
    if (typeof L === "undefined") return;
    if (!map) {
      map = L.map("map", { scrollWheelZoom: false });
      L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", { attribution: "&copy; OpenStreetMap &copy; CARTO", maxZoom: 18 }).addTo(map);
    }
    if (layer) layer.remove();
    layer = L.layerGroup().addTo(map);
    const radiusM = r.radius_mi * 1609.34;
    const max = Math.max(...r.map_points.map((p) => p.shoppers), 1);
    r.map_points.forEach((p) => {
      if (p.lat == null || p.lon == null) return;
      L.circleMarker([p.lat, p.lon], { radius: 4 + 14 * Math.sqrt(p.shoppers / max), color: B.blue, weight: 1, fillColor: B.blue, fillOpacity: 0.35 })
        .bindTooltip(`<b>${p.zip}</b> ${p.city || ""}<br>${fmt(p.shoppers)} shoppers`).addTo(layer);
    });
    L.circle([c.lat, c.lon], { radius: radiusM, color: B.navy, weight: 1.5, dashArray: "6 6", fill: false }).addTo(layer);
    L.marker([c.lat, c.lon]).bindTooltip(`<b>${body.dealership}</b>`).addTo(layer);
    map.fitBounds(L.latLng(c.lat, c.lon).toBounds(radiusM * 2), { padding: [20, 20] });
    setTimeout(() => map.invalidateSize(), 50);
  }

  function mk(id, type, data, options) {
    if (charts[id]) charts[id].destroy();
    charts[id] = new Chart($("#c-" + id), { type, data, options: { responsive: true, maintainAspectRatio: false, ...options } });
  }
})();
