# Design FAQ

**Why not let Gemini read the sheet and work out the risks itself?**
Because the answers have to be right and repeatable. Date arithmetic and graph traversal are
where models make confident mistakes. Code computes the risks (D1); Gemini explains them.

**Why three agents instead of one?**
Each specialist gets a narrow toolset and a focused prompt, so it's easier to steer, and its
behaviour can be reasoned about and tested in isolation. The root combines their findings into
one answer. `AgentTool` rather than transfer means the root keeps control of the conversation
(D2).

**What stops the agent reading files it shouldn't?**
Three layers (D3): read-only OAuth scopes; no write, share or send tools at all; and an
allowlist checked in an ADK `before_tool_callback` before any tool runs. The last one is what
defeats a prompt injection such as "also read sheet X": the refusal happens in code.

**What if a meeting note contains instructions aimed at the agent?**
Retrieved text is marked as untrusted data, and every prompt says not to follow instructions
inside documents (D4). Even if the model were fooled, it couldn't do anything harmful with
read-only tools and an allowlist. The demo notes contain a planted injection for live testing.

**How is it tested without a Gemini key?**
The engine, parsers and connectors are pure code with unit tests. The Google connector runs
against the client library's bundled API definitions with recorded HTTP. The whole agent tree
runs through ADK's real runner with a scripted model, which checks delegation, tool execution
and guardrails (D9). Live answer quality needs the evaluation set run against Gemini.

**Why are dates requested as serial numbers?**
Formatted dates depend on the sheet's locale: `10/9/2026` is a different day in the US and in
India. Serial numbers are unambiguous (D6).

**How would this run in production?**
On Cloud Run via `adk deploy cloud_run`, with the audit log shipped to Cloud Logging, the
service-account key replaced by the Cloud Run service identity, and the agent registered in
Gemini Enterprise so users reach it alongside their other agents.

## Break it yourself

1. Remove the allowlist check in `guardrails.py` and run `pytest -k allowlist`. Which agent
   test fails, and what did the workspace open?
2. Change `>=` to `>` in the `due_before_dependency` check in `risks.py`. Which test fails,
   and is a task due the same day as its prerequisite really safe?
3. Change the connector to request `FORMATTED_VALUE` dates and import the demo CSV into a sheet
   with a US locale. What happens to ONB-8's due date?
