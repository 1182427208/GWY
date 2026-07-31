# Web Research MCP Integration Design

## Goal

Make web search and page verification usable from both the position-analysis flow and the autonomous chat flow while preserving PostgreSQL as the source of truth for structured position filtering. The integration must produce reusable evidence and trace data rather than returning unverified page text.

## Scope

In scope:

- Add a runtime skill at `backend/app/gwy/runtime_skills/web-research/SKILL.md`.
- Introduce one shared web-research orchestration service.
- Register web research capabilities in the existing `ToolRegistry`.
- Reuse `WebSearchService`, `WebFetchService`, and `PlaywrightMCPService` as execution backends.
- Connect the same orchestration path to autonomous chat and position analysis.
- Normalize evidence records and trace events.
- Make remote MCP tool selection schema-aware.
- Add focused unit and integration tests.

Out of scope:

- Replacing PostgreSQL position filtering with web search or RAG.
- Building a new frontend page.
- Implementing a local MCP server.
- Crawling arbitrary sites in bulk or persisting a general web index.
- Treating search snippets as authoritative evidence.

## Current Context

The repository already contains:

- `WebSearchService` for search-provider access.
- `WebFetchService` for HTTP and optional fetch-MCP retrieval.
- `PlaywrightMCPService` for remote MCP browser access with local Playwright fallback.
- `WebVerificationAgent`, already used by position analysis for query planning, search, fetch, browser fallback, and trace generation.
- `backend/app/gwy/mcp_tools/web_tools.py`, currently exposing thin wrappers that are not registered with `ToolRegistry`.
- `runtime_skills/policy-rag` and `runtime_skills/position-planning`, loaded through the runtime `load_skill` tool.

The main gap is orchestration and registration: the position-analysis path directly owns the web services, while autonomous chat cannot request a web verification tool. The MCP wrapper layer therefore has no consistent entry point or observable invocation path.

## Proposed Architecture

```text
runtime skill: web-research
            |
autonomous chat ----> ToolRegistry: verify_web_evidence
            |                         |
position analysis --> WebResearchService
                                      |
              +-----------------------+-----------------------+
              |                       |                       |
       WebSearchService       WebFetchService        PlaywrightMCPService
              |                       |                       |
       search provider       HTTP/fetch MCP       remote MCP/local Playwright
```

### Runtime Skill

`web-research/SKILL.md` will define:

- Trigger conditions: missing local history, latest official policy verification, explicit user request for web information, or insufficient local evidence.
- The required sequence: plan queries, search, deduplicate, fetch, browser fallback when needed, extract evidence, assess source quality, and record trace.
- Source priority: government and recruiting-authority domains first, official announcements and PDF attachments next, other sources only as auxiliary evidence.
- Evidence requirements: URL, final URL, title, domain, retrieval time, excerpt, evidence type, credibility, and retrieval method.
- Failure behavior: report missing evidence explicitly and never infer eligibility, dates, or score lines from an empty or failed result.
- The rule that web research supplements but never replaces structured PostgreSQL filtering.

The skill is a behavior contract. It does not contain network logic and does not replace ToolRegistry registration.

### WebResearchService

The service will be the single orchestration boundary for both callers. It will accept a research request containing the user query, position context when available, planned query hints, source constraints, result limits, and trace context. It will return normalized evidence records, source-quality decisions, failures, and trace events.

The service will:

1. Build a bounded set of targeted queries.
2. Search each query with a fixed result budget.
3. Deduplicate by canonical URL and normalized title.
4. Prefer official domains and discard unusable results early.
5. Fetch candidate pages through HTTP.
6. Use browser rendering only when HTTP content is empty, JavaScript-dependent, or structurally unusable.
7. Extract bounded excerpts around the requested evidence.
8. Mark source quality and evidence completeness.
9. Return citations suitable for reports and a trace suitable for replay/debugging.

The existing `WebVerificationAgent` should either delegate its search stage to this service or be made a graph-level caller of it. It must not keep a second, divergent implementation of the same fetch and fallback rules.

### ToolRegistry Integration

Register the following tools in the existing agent runtime:

- `search_web`: low-level search capability for controlled internal use.
- `fetch_web_page`: low-level page retrieval capability for controlled internal use.
- `read_web_page`: browser/MCP rendering capability for controlled internal use.
- `verify_web_evidence`: the primary Agent-facing composition tool.

The primary autonomous workflow should call `verify_web_evidence`, not manually chain the three low-level tools. The position-analysis runtime should use the same service directly or through the same composition boundary so both paths share normalization, limits, fallback, and tracing.

The response schema for `verify_web_evidence` should contain:

```json
{
  "evidence": [],
  "citation_count": 0,
  "insufficient_evidence": false,
  "failures": [],
  "trace": []
}
```

### Evidence Schema

Each evidence item should include at least:

```text
title
url
final_url
source_domain
published_at
retrieved_at
excerpt
evidence_type
credibility
retrieved_via
```

`published_at` may be null when it cannot be verified. `credibility` must be derived from source and extraction status, not from search ranking alone.

### Remote MCP Selection

`PlaywrightMCPService` must stop selecting a remote tool primarily by name keywords or by falling back to the first listed tool. The selection algorithm should:

1. Read the remote tool name, description, and input schema.
2. Filter for tools that describe page reading/navigation or expose a URL-like required input.
3. Prefer a schema with a required `url`, `target`, `page_url`, or equivalent field.
4. Build arguments from the selected schema.
5. Return a structured failure when no compatible tool exists.

The selected remote tool name and schema decision must be included in trace output. The local Playwright fallback remains available when the remote MCP endpoint is unset, unavailable, or incompatible.

## Safety and Reliability

- Accept only `http` and `https` URLs.
- Enforce request, page, query, and excerpt limits.
- Preserve redirect/final URL information.
- Apply domain allow/deny rules before browser access where configuration permits.
- Avoid logging credentials, authorization headers, or full page contents.
- Catch backend-specific failures at the orchestration boundary and return explicit failure metadata.
- Keep web evidence separate from structured position facts.
- Never promote a search snippet to a citation without fetching or otherwise verifying the source page.

## Trace Contract

The unified path should emit trace steps with stable names:

- `web_query_planned`
- `web_search_started`
- `web_search_completed`
- `web_page_fetch_started`
- `web_page_fetch_completed`
- `web_browser_fallback`
- `web_evidence_extracted`
- `web_verification_completed`

Each step should include status, duration when available, bounded input/output summaries, retrieval method, and failure reason when applicable. Full page text should not be placed in trace records.

## Testing Strategy

Unit tests should cover:

- Query bounding and deduplication.
- Official-domain prioritization.
- HTTP success, empty-page fallback, PDF handling, and fetch failure.
- Browser fallback selection.
- Remote MCP schema matching and incompatible-schema failure.
- Evidence normalization and missing-publication-date handling.
- URL validation and configured limits.

Integration tests should verify:

- Autonomous chat can register and invoke `verify_web_evidence`.
- Position analysis uses the shared orchestration path.
- Trace entries are generated for successful and failed retrievals.
- Web evidence is attached to reports without changing PostgreSQL position filtering behavior.

## Success Criteria

- Both entry points can invoke the same web verification capability.
- At least one end-to-end test proves that a search result becomes a normalized citation or an explicit insufficient-evidence result.
- MCP and local Playwright fallback paths are distinguishable in `retrieved_via` and trace output.
- No Agent-facing flow needs to know which backend performed the retrieval.
- Direct runtime invocation counts can be measured from existing trace records.
