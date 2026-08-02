/* @vitest-environment jsdom */
/*
 * The connector form, and the two things about it that are easy to break.
 *
 * A check must run against what is on screen and must not save anything:
 * finding out the token is wrong is the entire point, and a check that first
 * persisted a broken connector would defeat it. And a token typed into this
 * form has to be stored before the check that uses it, or the check reports
 * "no access token" for a token the administrator just supplied.
 *
 * Both are ordering properties, which is why they are pinned by the order of
 * the requests rather than by what ends up on screen.
 */
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AdminTab } from "./AdminTab";

const CONFIG = {
  generation: 3,
  tenants: [{ name: "payments", tool_profile: "analysis", structural_only: false, enabled: true, ldap_groups: [], projects: [] }],
  roles: {},
  connectors: [],
  settings: {},
  secrets: [{ name: "connector.acme-github.token" }],
  admins: [],
};

const CHECK_OK = {
  ok: true, reason: "", discovered: 41, matched: 34, skipped: 2,
  truncated: false, sample: ["acme/payments-api"], excluded: ["acme/hr-portal"],
};

function mockAdmin(check: unknown = CHECK_OK) {
  const calls: { method: string; url: string; body: unknown }[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({
      method: init?.method ?? "GET",
      url,
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    });
    if (url === "/admin/config") return json(CONFIG);
    if (url === "/admin/connectors/check") return json(check);
    return json({ status: "ok" });
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

const json = (payload: unknown) =>
  new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });

async function openTheConnectorForm() {
  render(<AdminTab />);
  await waitFor(() => screen.getByText("Connectors"));
  fireEvent.click(screen.getByText("Connectors"));
  fireEvent.click(screen.getByText("Add a connector"));
}

describe("the connector form", () => {
  beforeEach(() => {
    sessionStorage.setItem("repo-mcp-admin", "a-session");
  });

  afterEach(() => {
    cleanup();
    sessionStorage.clear();
    vi.unstubAllGlobals();
  });

  it("checks what is on screen and saves nothing", async () => {
    const calls = mockAdmin();
    await openTheConnectorForm();

    fireEvent.change(screen.getByPlaceholderText("acme"), { target: { value: "typed-org" } });
    fireEvent.click(screen.getByText("Check"));

    await waitFor(() => screen.getByText(/34 of 41/));

    const check = calls.find((call) => call.url === "/admin/connectors/check");
    expect(check?.method).toBe("POST");
    /* The value typed a moment ago, not one that had to be saved first. */
    expect((check?.body as { settings: Record<string, string> }).settings.org).toBe("typed-org");
    /* Nothing was written: no connector, no secret. */
    expect(calls.some((call) => call.method === "PUT")).toBe(false);
  });

  it("reports a refusal in the platform's own words", async () => {
    mockAdmin({ ...CHECK_OK, ok: false, matched: 0, reason: "no such organisation, or the token cannot see it" });
    await openTheConnectorForm();

    fireEvent.click(screen.getByText("Check"));

    await waitFor(() => screen.getByText(/no such organisation/));
  });

  it("stores a token typed here before the check that needs it", async () => {
    const calls = mockAdmin();
    await openTheConnectorForm();

    fireEvent.click(screen.getByText("store a new token here"));
    fireEvent.change(screen.getByPlaceholderText("connector.acme-github.token"), {
      target: { value: "connector.new.token" },
    });
    fireEvent.change(screen.getByPlaceholderText("paste the token"), {
      target: { value: "ghp_secret" },
    });
    fireEvent.click(screen.getByText("Check"));

    await waitFor(() => screen.getByText(/34 of 41/));

    const order = calls.map((call) => `${call.method} ${call.url}`);
    const stored = order.indexOf("PUT /admin/secrets/connector.new.token");
    const checked = order.indexOf("POST /admin/connectors/check");
    expect(stored).toBeGreaterThan(-1);
    expect(stored).toBeLessThan(checked);
  });
});
