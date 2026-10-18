import { describe, expect, it } from "vitest";
import { strings } from "./strings";

function collect(value: unknown, out: string[] = []): string[] {
  if (typeof value === "string") out.push(value);
  else if (value && typeof value === "object") {
    for (const v of Object.values(value)) collect(v, out);
  }
  return out;
}

describe("strings", () => {
  it("has non-empty text for every entry", () => {
    const all = collect(strings);
    expect(all.length).toBeGreaterThan(0);
    for (const s of all) expect(s.trim().length).toBeGreaterThan(0);
  });

  it("labels the three sign-in fields", () => {
    expect(strings.signIn.branchCode).toBeTruthy();
    expect(strings.signIn.rollNumber).toBeTruthy();
    expect(strings.signIn.password).toBeTruthy();
  });
});
