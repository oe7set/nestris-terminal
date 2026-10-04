// Which text field the keyboards type into: the on-screen keyboard and, if
// one is plugged in, a physical keyboard (handleKey / handlePaste).

export type KeyboardLayout = "text" | "email" | "url" | "number";

export interface FieldTarget {
  id: string;
  get: () => string;
  set: (value: string) => void;
  layout: KeyboardLayout;
  maxLength: number;
  onEnter?: () => void;
}

class InputFocus {
  target = $state<FieldTarget | null>(null);
  // Fields on the current screen, in the order they appeared (for Tab).
  #fields: FieldTarget[] = [];

  register(field: FieldTarget): () => void {
    this.#fields = [...this.#fields.filter((f) => f.id !== field.id), field];
    return () => {
      this.#fields = this.#fields.filter((f) => f.id !== field.id);
      this.blur(field.id);
    };
  }

  focus(target: FieldTarget): void {
    this.target = target;
  }

  blur(id?: string): void {
    if (!id || this.target?.id === id) this.target = null;
  }

  type(text: string): void {
    const t = this.target;
    if (!t) return;
    const next = (t.get() + text).slice(0, t.maxLength);
    t.set(next);
  }

  backspace(): void {
    const t = this.target;
    if (t) t.set(t.get().slice(0, -1));
  }

  enter(): void {
    this.target?.onEnter?.();
  }

  /** Move to the next (or previous) field on the screen. */
  cycle(backwards = false): void {
    const fields = this.#fields;
    if (!fields.length) return;
    const index = fields.findIndex((f) => f.id === this.target?.id);
    const step = backwards ? -1 : 1;
    const next = index < 0 ? (backwards ? fields.length - 1 : 0) : (index + step + fields.length) % fields.length;
    this.target = fields[next] ?? null;
  }

  /**
   * A physical keyboard. Returns true when the key was used (the caller then
   * prevents the browser's default, e.g. Backspace = history back).
   */
  handleKey(e: KeyboardEvent): boolean {
    if (e.ctrlKey || e.altKey || e.metaKey) return false; // shortcuts, AltGr handled by the OS
    if (e.key === "Tab") {
      this.cycle(e.shiftKey);
      return true;
    }
    const t = this.target;
    if (!t) return false;
    if (e.key === "Backspace") {
      this.backspace();
    } else if (e.key === "Enter") {
      if (t.onEnter) this.enter();
      else this.blur();
    } else if (e.key === "Escape") {
      this.blur();
    } else if (e.key.length === 1) {
      // A printable character, as the OS layout produced it (incl. ä ö ü ß @).
      if (t.layout === "number" && !/[0-9.]/.test(e.key)) return true;
      this.type(e.key);
    } else {
      return false;
    }
    return true;
  }

  /** Ctrl+V / paste into the current field (line breaks dropped). */
  handlePaste(text: string): boolean {
    if (!this.target) return false;
    this.type(text.replace(/[\r\n\t]+/g, " "));
    return true;
  }
}

export const input = new InputFocus();
