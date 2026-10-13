# Connecting your Google Workspace

The agent reads one tracker Sheet and one or more meeting-notes Docs through a **service
account**: a robot Google identity that can read *only* the files you explicitly share with it,
and only with read-only scopes.

## 1. Create the service account (once, ~10 minutes)

1. Open <https://console.cloud.google.com/> and create a project (free).
2. **APIs & Services → Library:** enable **Google Sheets API** and **Google Docs API**.
3. **IAM & Admin → Service Accounts → Create service account.** Name it e.g.
   `risk-agent-reader`. Grant it **no roles**; it needs only the files you share.
4. Open the service account, then **Keys → Add key → Create new key → JSON**. Store the file
   **outside any git repository**, e.g. `~/.secrets/risk-agent-reader.json`.

   If your organisation blocks key creation, use a personal Google account, or switch the
   connector to OAuth user sign-in.

## 2. Share your files with it

1. Create a Google Sheet. **File → Import → Upload**, and pick [`demo/tracker.csv`](../demo/tracker.csv)
   (or use your own tracker with the same columns).
2. Create a Google Doc and paste in [`demo/meeting-notes.md`](../demo/meeting-notes.md). Use
   *Heading* styles for section titles so the agent can cite sections.
3. **Share** both with the service account's email (`...@...iam.gserviceaccount.com`) as
   **Viewer**.

## 3. Configure and check

The IDs are the long strings in each file's URL, between `/d/` and `/edit`.

```bash
export GOOGLE_APPLICATION_CREDENTIALS=~/.secrets/risk-agent-reader.json
export RISK_AGENT_BACKEND=google
export RISK_AGENT_SHEET_IDS=<sheet id>
export RISK_AGENT_DOC_IDS=<doc id>

python -m risk_agent risks          # reads your live Sheet, no Gemini needed
python -m risk_agent search "PAY-4"  # reads your live Doc
```

On Windows, use `setx NAME "value"` in a new terminal instead of `export`.

If a file isn't shared with the service account, you'll see "not found or is not shared with
the agent's service account (HTTP 403/404)".

## 4. Talk to it

```bash
export GEMINI_API_KEY=<key from https://aistudio.google.com/apikey>
adk web
```

The IDs in `RISK_AGENT_SHEET_IDS` and `RISK_AGENT_DOC_IDS` are the agent's whole world: any
other file ID is refused before a tool runs.

## Columns the tracker understands

| Field | Accepted headers | Notes |
|---|---|---|
| ID | ID, Task ID, Key, Ticket | required |
| Task | Task, Title, Summary, Name | required |
| Status | Status, State | required. Not started / In progress / Blocked / Done, plus common synonyms |
| Due | Due, Due date, Deadline, Target date | a real date cell, or `YYYY-MM-DD` |
| Depends on | Depends on, Dependencies, Blocked by, Prerequisites | IDs separated by commas |
| Owner, Workstream, Last update | ... | optional |
