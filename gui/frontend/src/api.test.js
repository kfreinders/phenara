import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "./api";

afterEach(() => vi.unstubAllGlobals());

describe("api", () => {
  it("marks mutating same-origin requests", async () => {
    const fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
    });
    vi.stubGlobal("fetch", fetch);

    await api("/api/test", { method: "post", body: "{}" });

    const options = fetch.mock.calls[0][1];
    expect(options.headers.get("X-Phenara-Request")).toBe("1");
    expect(options.headers.get("Content-Type")).toBe("application/json");
  });

  it("shows useful FastAPI validation errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 422,
        json: async () => ({ detail: [{ msg: "Value error, Invalid interval" }] }),
      }),
    );

    await expect(api("/api/test")).rejects.toThrow("Invalid interval");
  });
});
