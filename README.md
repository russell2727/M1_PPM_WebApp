# M1 Data & Analytics — In-Market Auto Shoppers Dashboard

Lead-capture web app: a dealership prospect enters name / email / dealership / ZIP, picks
New/Used and a mile radius, and gets an on-screen dashboard (KPIs, vehicle-type chart,
New vs Used donut, distance rings, map, top ZIPs) plus a branded PDF that is emailed to them.
Every submission is also appended to `leads.csv`.

Stack: Python 3.11 · Flask · pandas · ReportLab/Matplotlib (PDF) · Chart.js + Leaflet (browser) · gunicorn on Render.

---

## 1. Where the data file goes

**Put the CSVs in the `data/` folder of this repo and commit them.** That is the simplest,
correct answer for Render: the repo is cloned into the container on every deploy, so anything
committed under `data/` is on disk at `./data/` when the app boots. The app reads them once at
startup into memory and never touches them again.

```
m1-auto-dashboard/
├── data/
│   ├── in_market_auto_shoppers.csv.gz ← PPM breakdown export (gzipped CSV, 1.4 MB)
│   └── vehicle_type_lookup.csv        ← your body-style → Sedan/Truck/SUV table
```

Pick the option that matches your file size:

| Shopper file size | What to do |
|---|---|
| **< 100 MB** | Commit to `data/` in GitHub. Done. Re-push to update. |
| **100 MB – 2 GB** | Commit with **Git LFS** (`git lfs install && git lfs track "data/*.csv"`). Render pulls LFS objects on build. Or gzip it — pandas reads `.csv.gz` directly; set `SHOPPERS_FILE=in_market_auto_shoppers.csv.gz`. |
| **> 2 GB or updated weekly without a code push** | Attach a **Render Disk** (uncomment the `disk:` block in `render.yaml`, set `DATA_DIR=/var/data`), then upload with `render ssh` + `scp`, or have a cron job pull from S3 into `/var/data`. Alternatively convert to Parquet (5–10× smaller, faster load). |

`DATA_DIR`, `SHOPPERS_FILE`, and `VEHICLE_TYPE_LOOKUP_FILE` are all environment variables
(see `config.py`), so moving the files later never requires a code change.

> Memory note: pandas needs roughly 3–5× the CSV size in RAM. A 200 MB CSV wants the
> Render **Standard** (2 GB) instance. Convert to Parquet or pre-aggregate to
> `zip × condition × body_style` rows if the raw file is per-consumer.

### Expected columns (rename in `config.py → COLUMNS` to match your headers)

**in_market_auto_shoppers.csv**

| canonical | default header | notes |
|---|---|---|
| zip | `zip` | 5-digit; leading zeros are restored automatically (source: Zip Code) |
| state | `state` | optional; derived from ZIP when absent |
| msa | `msa` | optional (source: MSA Name) — drives the "Metro areas" table |
| condition | `condition` | `New` / `Used` (source: PPM Type) |
| vehicle_key | `segment` | source: PPM Segment |
| shoppers | `shopper_count` | source: Total |

**vehicle_type_lookup.csv** — the table you referenced that defines Sedan / Truck / etc.

| `segment` | `vehicle_type` |
|---|---|
| SUV | SUV |
| Mini-van | Minivan |
| Full-size | Full-Size |

Any `vehicle_key` not found in the lookup is bucketed as **Other**.

`data/in_market_auto_shoppers.csv.gz` is the **CountID 109671 PPM breakdown export**
(260,912 rows · 15.0M in-market shoppers · 10 segments · New/Used). To refresh it:

```bash
python scripts/convert_export.py path/to/CountID_XXXXX_breakdown_export.xlsx
git commit -am "refresh shopper data" && git push     # Render auto-deploys
```

ZIP → lat/long geocoding uses the `zipcodes` package (42k US ZIPs bundled, no network calls).

---

## 2. Run locally

```bash
git clone https://github.com/russell2727/M1_PPM_WebApp.git
cd M1_PPM_WebApp
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # optional: SMTP settings
python app.py                   # http://localhost:5000
```

---

## 3. Deploy to Render

1. Push the repo to GitHub (`russell2727/M1_PPM_WebApp`).
2. Render → **New → Blueprint** → select the repo. `render.yaml` provisions the web service.
3. In the service's **Environment** tab, set the secrets:
   - `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD` — SendGrid (`smtp.sendgrid.net` / `apikey` / your API key), Postmark, or Google Workspace app password.
   - `MAIL_FROM` — a sender on a domain with SPF/DKIM set up (`reports@m1-data.com`).
   - `MAIL_BCC` — where every prospect report should be copied internally.
4. Deploy. Health check: `https://<service>.onrender.com/healthz` returns row/ZIP counts.
5. Custom domain: Settings → Custom Domains → e.g. `shoppers.m1-data.com` → add the CNAME in GoDaddy.

If SMTP vars are left blank the app still works — the PDF is offered as a download link instead of emailed.

### Persistence

Render's filesystem is **ephemeral**. Generated PDFs and `leads.csv` are lost on each deploy
unless you (a) mount a Render Disk and point `OUTPUT_DIR` at it, or (b) rely on `MAIL_BCC`
to keep a copy of every lead in your inbox / HubSpot. For HubSpot, the cleanest upgrade is to
add a HubSpot Forms API call in `app._record_lead()`.

---

## 4. Google Maps keys

The dashboard uses Google Maps (JavaScript API) on screen and the Maps Static API for the
PDF map. Without keys it falls back to Leaflet + CARTO tiles automatically.

1. console.cloud.google.com → create project `m1-ppm-webapp` → **Billing** → link a billing account
   (required even on the free tier; Google's monthly free usage covers this app's volume).
2. **APIs & Services → Library** → enable **Maps JavaScript API** and **Maps Static API**.
3. **Credentials → Create credentials → API key**, twice:
   - Browser key → Application restrictions: *Websites* → add `https://<service>.onrender.com/*` and your
     custom domain; API restrictions: *Maps JavaScript API* only. → `GOOGLE_MAPS_JS_KEY`
   - Server key → Application restrictions: *None* (Render IPs rotate); API restrictions: *Maps Static API*
     only. → `GOOGLE_MAPS_STATIC_KEY`
4. Render → Environment → set both keys → Save (auto-redeploys).
5. Optional: Map Management → create a Map ID with a custom style → `GOOGLE_MAP_ID`.

## 5. Branding

- Logo: drop your PNG at `static/img/m1-logo.png` (header + PDF pick it up automatically; a text wordmark shows until then).
- Colors: edit `BRAND` in `config.py`. The browser, the charts and the PDF all read from that one dict.
- Copy: `templates/index.html` (hero + CTA), `services/pdf.py` (report footer text), `services/mailer.py` (email body).

---

## 6. Project layout

```
app.py                  Flask routes: / (form+dashboard), POST /api/report, /reports/<pdf>, /healthz
config.py               paths, column map, brand, SMTP
services/data.py        load CSVs, geocode, radius query, aggregations
services/pdf.py         ReportLab PDF with Matplotlib charts
services/mailer.py      SMTP send with PDF attachment
templates/index.html    page
static/css|js|img       styles, Chart.js + Leaflet front end, logo
data/                   shopper table + vehicle-type lookup (commit here)
render.yaml             Render Blueprint
```
