import { beforeEach, describe, expect, it } from "vitest";
import { useAtlas } from "../../src/app/store";

describe("session store", () => {
  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
  });
  it("keeps the token in sessionStorage only", () => {
    useAtlas.getState().setSession("tok123", null);
    expect(sessionStorage.getItem("atlas.token")).toBe("tok123");
    expect(JSON.stringify(localStorage)).not.toContain("tok123");
    useAtlas.getState().setSession(null, null);
    expect(sessionStorage.getItem("atlas.token")).toBeNull();
  });
  it("tracks recent projects most-recent-first without duplicates", () => {
    const s = useAtlas.getState();
    s.setProject("a");
    s.setProject("b");
    s.setProject("a");
    expect(useAtlas.getState().recentProjects).toEqual(["a", "b"]);
  });
  it("caps open tabs", () => {
    for (let i = 0; i < 12; i++) useAtlas.getState().openTab(`/p${i}`, `P${i}`);
    expect(useAtlas.getState().tabs.length).toBe(8);
  });
});
