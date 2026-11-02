(function () {
  const $ = (s, el = document) => el.querySelector(s);
  const fmt = (n) => Number(n || 0).toLocaleString();
  const C = window.M1_COLORS, B = window.M1_BRAND;
  $("#yr").textContent = new Date().getFullYear();

  Chart.defaults.font.family = "Inter, system-ui, sans-serif";
  Chart.defaults.color = B.gray;
  let charts = {}, map, layer, gOverlays = [];

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
    $("#map-link").hidden = !j.map_url; if (j.map_url) $("#map-link").href = j.map_url;
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
    if (window.M1_GMAPS && window.google && google.maps) return drawGoogleMap(r, c, body);
    if (typeof L === "undefined") return;
    $("#map-title").textContent = `${fmt(r.total_shoppers)} in-market shoppers within ${r.radius_mi} miles of ${body.dealership}`;
    $("#map-sub").textContent = `${c.city}, ${c.state} ${c.zip} · ${r.zip_count} ZIP codes · top ${Math.min(r.map_points.length, 500)} shown`;
    if (!map) {
      map = L.map("map", { scrollWheelZoom: false });
      L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", { attribution: "&copy; OpenStreetMap &copy; CARTO", maxZoom: 18 }).addTo(map);
    }
    if (layer) layer.remove();
    layer = L.layerGroup().addTo(map);
    const radiusM = r.radius_mi * 1609.34;
    const pts = r.map_points.filter((p) => p.lat != null && p.lon != null);
    const max = Math.max(...pts.map((p) => p.shoppers), 1);

    // shaded search area + ring
    L.circle([c.lat, c.lon], { radius: radiusM, color: B.navy, weight: 2, dashArray: "8 6", fillColor: B.blue, fillOpacity: 0.06 }).addTo(layer);

    // shopper bubbles, scaled by sqrt(volume); labels on the biggest
    pts.forEach((p, i) => {
      const rad = 6 + 26 * Math.sqrt(p.shoppers / max);
      L.circleMarker([p.lat, p.lon], { radius: rad, color: B.blue, weight: 1.5, fillColor: B.blue, fillOpacity: 0.38 })
        .bindTooltip(`<b>${p.zip}</b> ${p.city || ""}<br>${fmt(p.shoppers)} in-market shoppers`).addTo(layer);
      if (i < 10 && rad > 14) {
        L.marker([p.lat, p.lon], { icon: L.divIcon({ className: "", html: `<div class="bubble-label">${p.zip}<br>${fmt(p.shoppers)}</div>`, iconSize: [60, 24], iconAnchor: [30, 12] }), interactive: false }).addTo(layer);
      }
    });

    // dealership pin + label
    L.marker([c.lat, c.lon], { icon: L.divIcon({ className: "", html: '<div class="dealer-pin"></div>', iconSize: [22, 22], iconAnchor: [11, 22] }), zIndexOffset: 1000 })
      .bindTooltip(`<b>${body.dealership}</b><br>${c.city}, ${c.state} ${c.zip}`).addTo(layer);
    L.marker([c.lat, c.lon], { icon: L.divIcon({ className: "", html: `<div class="dealer-label">${body.dealership}</div>`, iconSize: [0, 0], iconAnchor: [-14, 30] }), interactive: false, zIndexOffset: 1000 }).addTo(layer);

    map.fitBounds(L.latLng(c.lat, c.lon).toBounds(radiusM * 2.3), { padding: [10, 10] });
    setTimeout(() => map.invalidateSize(), 50);
  }

  async function drawGoogleMap(r, c, body) {
    const { Map, Circle, InfoWindow } = await google.maps.importLibrary("maps");
    const { AdvancedMarkerElement } = await google.maps.importLibrary("marker");
    const center = { lat: c.lat, lng: c.lon };
    const radiusM = r.radius_mi * 1609.34;
    const useAdvanced = !!window.M1_GMAPS.mapId;
    if (!map) {
      map = new Map($("#map"), {
        center, zoom: 11, mapId: window.M1_GMAPS.mapId || undefined,
        mapTypeControl: false, streetViewControl: false, fullscreenControl: true,
        gestureHandling: "cooperative", clickableIcons: false,
        styles: useAdvanced ? undefined : [{ featureType: "poi", stylers: [{ visibility: "off" }] }, { featureType: "transit", stylers: [{ visibility: "off" }] }],
      });
    }
    gOverlays.forEach((o) => o.setMap(null)); gOverlays = [];
    const info = new InfoWindow();

    // search radius
    gOverlays.push(new Circle({ map, center, radius: radiusM, strokeColor: B.navy, strokeOpacity: 0.9, strokeWeight: 2, fillColor: B.blue, fillOpacity: 0.07, clickable: false }));

    // shopper bubbles — Circle with radius in meters scaled by sqrt(volume) relative to the search radius
    const pts = r.map_points.filter((p) => p.lat != null && p.lon != null);
    const max = Math.max(...pts.map((p) => p.shoppers), 1);
    pts.forEach((p) => {
      const rad = radiusM * (0.03 + 0.14 * Math.sqrt(p.shoppers / max));
      const circ = new Circle({ map, center: { lat: p.lat, lng: p.lon }, radius: rad, strokeColor: B.blue, strokeWeight: 1.5, strokeOpacity: 0.9, fillColor: B.blue, fillOpacity: 0.38 });
      circ.addListener("click", () => { info.setContent(`<b>${p.zip}</b> ${p.city || ""}<br>${fmt(p.shoppers)} in-market shoppers`); info.setPosition({ lat: p.lat, lng: p.lon }); info.open(map); });
      gOverlays.push(circ);
    });
    pts.slice(0, 10).forEach((p) => {
      const el = document.createElement("div"); el.className = "bubble-label"; el.innerHTML = `${p.zip}<br>${fmt(p.shoppers)}`;
      gOverlays.push(useAdvanced
        ? new AdvancedMarkerElement({ map, position: { lat: p.lat, lng: p.lon }, content: el, zIndex: 5 })
        : new google.maps.Marker({ map, position: { lat: p.lat, lng: p.lon }, label: { text: `${p.zip} · ${fmt(p.shoppers)}`, color: B.navy, fontSize: "11px", fontWeight: "700" }, icon: { path: google.maps.SymbolPath.CIRCLE, scale: 0 }, clickable: false }));
    });

    // dealership pin + label
    const pin = document.createElement("div"); pin.innerHTML = `<div class="dealer-label">${body.dealership}</div>`;
    gOverlays.push(useAdvanced
      ? new AdvancedMarkerElement({ map, position: center, title: body.dealership, zIndex: 1000 })
      : new google.maps.Marker({ map, position: center, title: body.dealership, zIndex: 1000, icon: { path: "M12 0C7 0 3 4 3 9c0 7 9 15 9 15s9-8 9-15c0-5-4-9-9-9z", fillColor: B.orange, fillOpacity: 1, strokeColor: B.navy, strokeWeight: 2, scale: 1.6, anchor: new google.maps.Point(12, 24) } }));
    gOverlays.push(useAdvanced
      ? new AdvancedMarkerElement({ map, position: center, content: pin, zIndex: 1001 })
      : new google.maps.Marker({ map, position: center, label: { text: body.dealership, color: B.navy, fontSize: "13px", fontWeight: "700", className: "gm-dealer-label" }, icon: { path: google.maps.SymbolPath.CIRCLE, scale: 0 }, clickable: false, zIndex: 1001 }));

    map.fitBounds(new google.maps.Circle({ center, radius: radiusM * 1.15 }).getBounds());
  }

  function mk(id, type, data, options) {
    if (charts[id]) charts[id].destroy();
    charts[id] = new Chart($("#c-" + id), { type, data, options: { responsive: true, maintainAspectRatio: false, ...options } });
  }
})();
