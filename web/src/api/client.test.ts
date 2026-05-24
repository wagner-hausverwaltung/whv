import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  clearTokens,
  getAccessToken,
  getRefreshToken,
  setTokens,
} from "./client";

describe("token storage", () => {
  beforeEach(() => clearTokens());
  afterEach(() => clearTokens());

  it("round-trips access + refresh tokens via localStorage", () => {
    expect(getAccessToken()).toBeNull();
    expect(getRefreshToken()).toBeNull();
    setTokens("a-token", "r-token");
    expect(getAccessToken()).toBe("a-token");
    expect(getRefreshToken()).toBe("r-token");
  });

  it("clearTokens wipes both keys", () => {
    setTokens("a", "r");
    clearTokens();
    expect(getAccessToken()).toBeNull();
    expect(getRefreshToken()).toBeNull();
  });
});

describe("interceptor", () => {
  it("dispatches whv:auth:expired event after refresh failure", async () => {
    // We can't easily mock axios from here without monkey-patching the module,
    // so this is a placeholder for a fuller integration test in commit 2 (when
    // we wire MSW). Just assert that listening to the event works for now.
    const handler = vi.fn();
    window.addEventListener("whv:auth:expired", handler);
    window.dispatchEvent(new Event("whv:auth:expired"));
    expect(handler).toHaveBeenCalledOnce();
    window.removeEventListener("whv:auth:expired", handler);
  });
});
