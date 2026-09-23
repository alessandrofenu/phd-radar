# PhD Radar

Every 4 hours, GitHub scans ~55 European sources for maths PhD positions, scores each
posting against two research profiles, and publishes a password-protected dashboard on
GitHub Pages. The listings are encrypted (AES-256) before they leave GitHub's servers,
so the website and the repository only ever contain unreadable data without the password.

| File | What it is | Edit it? |
|---|---|---|
| `sources.yaml` | every site that is checked | **yes** – add/remove sources here |
| `profiles.yaml` | keywords, researcher names and weights for each person | **yes** – tune matching here |
| `site/index.html` | the dashboard | no |
| `radar/` | the scanner (Python) | no |
| `.github/workflows/radar.yml` | the 4-hour schedule | no |

## One-time setup (about 10 minutes, all in the browser)

1. **Create the repository.** On GitHub: **+ → New repository**, name it e.g. `phd-radar`,
   choose **Public** (free Pages and unlimited Actions minutes; the data is encrypted),
   tick nothing else, **Create repository**.

2. **Upload the files.** On the new repository page click **uploading an existing file**,
   then drag in everything from this folder: `sources.yaml`, `profiles.yaml`,
   `requirements.txt`, `README.md`, `.gitignore`, and the folders `radar` and `site`.
   Click **Commit changes**.

3. **Add the workflow file.** Folders starting with a dot are often skipped by drag and
   drop, so create this one by hand: **Add file → Create new file**, type the name
   `.github/workflows/radar.yml` (the slashes create the folders), paste the contents of
   that file from this folder, **Commit changes**.

4. **Choose the password.** **Settings → Secrets and variables → Actions → New repository
   secret**. Name: `RADAR_PASSWORD`, value: a long passphrase you will both type on the
   dashboard (e.g. four random words). **Add secret**.

5. **Turn on Pages.** **Settings → Pages → Build and deployment → Source: GitHub Actions**.

6. **First run.** **Actions** tab → if asked, click *I understand my workflows, enable them* →
   **PhD Radar** → **Run workflow** → **Run workflow**. It takes about 5 minutes.

7. **Open the dashboard** at `https://<your-username>.github.io/phd-radar/`, enter the
   password, tick *Remember on this device*. Bookmark it on both phones.

From then on it runs by itself every 4 hours, and also right after you edit
`sources.yaml` or `profiles.yaml`. If a run fails, GitHub emails you.

## Using the dashboard

- **Alessandro / Girlfriend tabs** show postings scoring at least *min score* for that
  person (slider; 6 ≈ "mentions something clearly relevant"). Lower it to see more.
- **All maths PhDs** lists every maths doctoral posting found, whatever the topic.
- **Schools & pages** shows the watched graduate-school and group pages; when one changes,
  it is marked UPDATED and the new lines are listed.
- **Sources** shows which sites worked in the last run.
- ★ / ✓ / ✕ marks and the NEW badges are stored in each browser only.

## Changing things

- **Add a source:** add an entry to `sources.yaml` (instructions at the top of the file) or
  ask Claude "add this source: <url>". Commit, and a run starts automatically.
- **Change keywords:** edit `profiles.yaml`. Postings already rejected are not re-checked
  unless you run the workflow manually with **Re-check postings rejected earlier** ticked.
- **Change the password:** update the `RADAR_PASSWORD` secret, then run the workflow
  manually with **Start from empty data** ticked (old data can't be decrypted any more).
- **Rename the girlfriend tab:** `name:` under `her:` in `profiles.yaml`.

## Running locally (optional)

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m radar test "EURAXESS"          # try one source, print what it keeps
.venv/bin/python -m radar check                    # try every source, print a health table
RADAR_PASSWORD=secret .venv/bin/python -m radar run --state-file local/state.enc --out _site
python -m http.server -d _site 8000               # then open http://localhost:8000
```

## Limits worth knowing

- Sites that need a real browser (JavaScript-only search pages) or block bots
  (FindAPhD, Academic Positions, ScholarshipDB, European Women in Mathematics) are not
  scanned. Their postings usually also appear on EURAXESS, jobs.ac.uk or the EMS portal.
- Italian PhD calls come from the ministry's national list (bandi.mur.gov.it) and the
  watched pages of SISSA, SNS, Pisa and Tor Vergata; most Italian calls open in spring–summer.
- Keyword matching is literal: a posting in "geometric topology" won't match "knot theory"
  unless it says so. Add synonyms to `profiles.yaml` as you notice gaps.
