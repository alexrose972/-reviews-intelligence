# Browser Scan runner

Railway scans from a datacenter IP with headless Chromium, so premium DTC sites
(Cloudflare / PerimeterX / DataDome) block it — those scans come back **blocked**
with no score. The Browser Scan runner finishes those scans from a **real, local
Chrome** (residential IP, genuine fingerprint), which the WAFs don't block.

You run it on your Mac. It polls the app for blocked/queued scans, audits them in
your browser, and posts the results back. The app scores them and updates the UI
exactly as if Railway had done it.

## One-time setup

```bash
git clone https://github.com/alexrose972/-reviews-intelligence
cd -reviews-intelligence
pip install -r requirements.txt
python -m playwright install chromium   # only needed for the launch-Chrome mode
```

## Run it

```bash
export API_BASE_URL=https://reviews-intelligence-production.up.railway.app
export BROWSER_WEBHOOK_SECRET=...        # the same value set on Railway
python -m backend.chrome_runner
```

Leave it running. When someone clicks **Run Browser Scan** on a blocked scan (or a
scan is auto-queued), the runner picks it up within a few seconds, a Chrome window
opens and drives itself through the site, and the brief fills in.

## Strongest mode: attach to your own Chrome (optional)

Using your already-logged-in Chrome profile is the hardest to block. Quit Chrome,
then:

```bash
# macOS
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222

# in another terminal
export CHROME_CDP_URL=http://localhost:9222
export API_BASE_URL=...
export BROWSER_WEBHOOK_SECRET=...
python -m backend.chrome_runner
```

## Optional

| Env var | Effect |
|---|---|
| `CHROME_CDP_URL` | Attach to a Chrome you started yourself (real profile). Omit to let the runner launch a fresh Chrome. |
| `GOOGLE_PAGESPEED_API_KEY` | Enables the Page Speed dimension (otherwise scored as "not collected"). |
| `RUNNER_POLL_SECONDS` | How often to poll for work (default 8). |

## How it fits together

```
Railway scan blocked ──► job queued ──► [your Mac] python -m backend.chrome_runner
                                              │  POST /api/chrome-jobs/next   (claim)
                                              │  drives real Chrome on your IP
                                              └► POST /api/browser-data/{id}  (results)
                                                         │
                                                 app scores + updates UI
```

If the runner crashes mid-scan, the app requeues the job after its timeout (up to
`max_attempts`), so just restart the runner.
