import { describe, expect, it } from "vitest";
import { AxiosError, AxiosHeaders } from "axios";
import {
  MIN_PASSWORD_LENGTH,
  PASSWORD_TOO_SHORT,
  isValidationError,
  passwordError,
} from "@/lib/password";

function axiosError(status: number): AxiosError {
  const err = new AxiosError("boom");
  err.response = {
    status,
    statusText: "",
    data: {},
    headers: new AxiosHeaders(),
    config: { headers: new AxiosHeaders() },
  };
  return err;
}

describe("password rule", () => {
  it("matches the backend minimum of 10", () => {
    // Field(min_length=10) in backend/app/schemas/auth.py — if that ever
    // changes, this constant has to move with it.
    expect(MIN_PASSWORD_LENGTH).toBe(10);
  });

  it("rejects a password the API would 422 on", () => {
    expect(passwordError("neunzeich", "neunzeich")).toBe(PASSWORD_TOO_SHORT);
    expect(passwordError("123456789", "123456789")).toBe(PASSWORD_TOO_SHORT);
  });

  it("accepts a long enough matching password", () => {
    expect(passwordError("Hausgeld2026!", "Hausgeld2026!")).toBeNull();
    expect(passwordError("zehnzeiche", "zehnzeiche")).toBeNull();
  });

  it("reports a mismatch before the length", () => {
    expect(passwordError("Hausgeld2026!", "Hausgeld2027!")).toBe(
      "Passwörter stimmen nicht überein.",
    );
  });

  it("treats only 422 as a validation failure", () => {
    expect(isValidationError(axiosError(422))).toBe(true);
    expect(isValidationError(axiosError(400))).toBe(false);
    expect(isValidationError(axiosError(404))).toBe(false);
    expect(isValidationError(new Error("network"))).toBe(false);
  });
});
