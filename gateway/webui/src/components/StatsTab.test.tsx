/* @vitest-environment jsdom */
/*
 * Upstream's tests here covered the filesystem picker and the per-slot index
 * queue. Both are gone: on a shared platform there is no directory a person
 * should be choosing by hand, and indexing is the indexer's job rather than a
 * worker pool a browser watches. What remains is what this deployment does —
 * the project list, and where its requests go.
 *
 * That last point is the one worth pinning. Every request has to reach /mcp
 * carrying the caller's token and squad; a regression that sent one to /rpc,
 * or sent it unauthenticated, would work perfectly against a local engine and
 * bypass the whole authorization model here.
 */
import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StatsTab } from "./StatsTab";

function toolResult(payload: unknown) {
  return new Response(
    JSON.stringify({ result: { content: [{ text: JSON.stringify(payload) }] } }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}

function mockGateway(projects: { name: string; root_path?: string }[] = []) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, init });
    if (url === "/mcp") {
      const body = JSON.parse(String(init?.body ?? "{}"));
      const tool = body?.params?.name;
      if (tool === "list_projects") return toolResult({ projects });
      if (tool === "index_status") return toolResult({ nodes: 12, edges: 34 });
      return toolResult({});
    }
    return new Response("{}", { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

describe("StatsTab", () => {
  beforeEach(() => {
    sessionStorage.clear();
    sessionStorage.setItem("repo-mcp-token", "a-token");
    sessionStorage.setItem("repo-mcp-squad", "payments");
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    sessionStorage.clear();
  });

  it("lists the projects this squad has indexed", async () => {
    mockGateway([{ name: "acme-payments-api", root_path: "/srv/payments/acme-payments-api" }]);
    render(<StatsTab onSelectProject={() => {}} />);

    expect(await screen.findByText("acme-payments-api")).toBeInTheDocument();
  });

  it("asks the gateway, not the engine's own server", async () => {
    const calls = mockGateway();
    render(<StatsTab onSelectProject={() => {}} />);

    await waitFor(() => expect(calls.some((call) => call.url === "/mcp")).toBe(true));
    expect(calls.some((call) => call.url.startsWith("/rpc"))).toBe(false);
  });

  it("carries the caller's token and squad on every call", async () => {
    const calls = mockGateway();
    render(<StatsTab onSelectProject={() => {}} />);

    await waitFor(() => expect(calls.some((call) => call.url === "/mcp")).toBe(true));
    for (const call of calls.filter((entry) => entry.url === "/mcp")) {
      const headers = call.init?.headers as Record<string, string>;
      expect(headers.Authorization).toBe("Bearer a-token");
      expect(headers["X-Tenant"]).toBe("payments");
    }
  });

  it("offers no filesystem picker", async () => {
    mockGateway();
    render(<StatsTab onSelectProject={() => {}} />);

    await waitFor(() => expect(screen.queryByLabelText("Repository path")).toBeNull());
  });
});
