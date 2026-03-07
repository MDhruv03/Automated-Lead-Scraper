# LeadPulse

LeadPulse is a simple lead discovery tool.  
Enter an **industry and location**, and it finds companies, crawls their websites, extracts contact emails/phones, filters the results, and exports the leads to Excel.

## Run Locally

```bash
uv sync
uv pip install en-core-web-sm@https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.7.1/en_core_web_sm-3.7.1-py3-none-any.whl
uv run uvicorn app.main:app --reload

Open **http://localhost:8000** → Search page → enter industry & location → hit Start.

### Worker Mode (optional)

For production / Render, the worker runs as a separate process that polls for jobs:

```bash
# Set WORKER_TOKEN and WORKER_SERVER_URL, then:
uv run python worker.py
```

## What It Does

1. Discover companies
2. Crawl company websites
3. Extract emails and phone numbers
4. Validate and filter results
5. Export leads to Excel
___
On a side note, I have implemented the crawler on my local system, so it is less likely to be blocked by search engines because it runs on a residential internet connection. Running it on a cloud server could increase the chances of it being blocked, since datacenter IPs are more easily identified and restricted by search engines.
