import { describe, expect, it } from "vitest";
import { input, type FieldTarget } from "./input.svelte";

type TestField = FieldTarget & { value: string };

function field(id: string, opts: Partial<FieldTarget> = {}): TestField {
  const f: TestField = {
    id,
    value: "",
    layout: "text",
    maxLength: 15,
    get: (): string => f.value,
    set: (v: string) => {
      f.value = v;
    },
    ...opts,
  };
  return f;
}

function key(k: string, extra: Partial<KeyboardEventInit> = {}): KeyboardEvent {
  // Only the fields handleKey reads (vitest runs without a DOM).
  return { key: k, ctrlKey: false, altKey: false, metaKey: false, shiftKey: false, ...extra } as KeyboardEvent;
}

describe("physical keyboard", () => {
  it("types into the focused field like the on-screen keyboard", () => {
    const nick = field("nick", { maxLength: 5 });
    const off = input.register(nick);
    input.focus(nick);
    for (const k of ["J", "ü", "r", "g", "e", "n"]) expect(input.handleKey(key(k))).toBe(true);
    expect(nick.value).toBe("Jürge"); // maxLength
    input.handleKey(key("Backspace"));
    expect(nick.value).toBe("Jürg");
    expect(input.handleKey(key("v", { ctrlKey: true }))).toBe(false); // shortcuts stay with the browser
    expect(input.handleKey(key("F5"))).toBe(false);
    off();
    expect(input.target).toBeNull();
  });

  it("Enter, Escape and Tab", () => {
    let entered = 0;
    const a = field("a", { onEnter: () => entered++ });
    const b = field("b");
    const offA = input.register(a);
    const offB = input.register(b);
    expect(input.target).toBeNull();
    input.handleKey(key("Tab")); // no field yet: the first one
    expect(input.target?.id).toBe("a");
    input.handleKey(key("Enter"));
    expect(entered).toBe(1);
    input.handleKey(key("Tab"));
    expect(input.target?.id).toBe("b");
    input.handleKey(key("Tab", { shiftKey: true }));
    expect(input.target?.id).toBe("a");
    input.handleKey(key("Tab", { shiftKey: true })); // wraps around
    expect(input.target?.id).toBe("b");
    input.handleKey(key("Enter")); // no onEnter: closes the field
    expect(input.target).toBeNull();
    input.focus(a);
    input.handleKey(key("Escape"));
    expect(input.target).toBeNull();
    expect(input.handleKey(key("x"))).toBe(false); // nothing focused: not ours
    offA();
    offB();
  });

  it("number fields take digits only; paste", () => {
    const pin = field("pin", { layout: "number" });
    const off = input.register(pin);
    input.focus(pin);
    for (const k of ["1", "a", "2", "."]) input.handleKey(key(k));
    expect(pin.value).toBe("12.");
    const mail = field("mail", { maxLength: 30 });
    const offMail = input.register(mail);
    input.focus(mail);
    expect(input.handlePaste("erv@example.org\r\n")).toBe(true);
    expect(mail.value).toBe("erv@example.org ");
    off();
    offMail();
    expect(input.handlePaste("x")).toBe(false);
  });
});
