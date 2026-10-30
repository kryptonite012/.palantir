import { afterEach, describe, expect, it } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { FeedbackHost, askConfirm, askText, toast, useFeedback } from "../../src/components/feedback";

describe("in-app feedback", () => {
  afterEach(() => { cleanup(); useFeedback.getState().close(); });
  it("caps the toast stack", () => {
    for (let i = 0; i < 6; i++) toast.info(`t${i}`);
    expect(useFeedback.getState().toasts.map((t) => t.text)).toEqual(["t3", "t4", "t5"]);
  });

  it("askText resolves with the typed value and enforces mustEqual", async () => {
    render(<FeedbackHost />);
    let result: Promise<string | null>;
    act(() => { result = askText({ title: "Delete dataset?", mustEqual: "people", danger: true, confirmText: "Delete" }); });
    const button = await screen.findByRole("button", { name: "Delete" });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "people" } });
    expect((button as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(button);
    await expect(result!).resolves.toBe("people");
  });

  it("askConfirm resolves false on cancel", async () => {
    render(<FeedbackHost />);
    let result: Promise<boolean>;
    act(() => { result = askConfirm({ title: "Run?" }); });
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    await expect(result!).resolves.toBe(false);
  });
});
