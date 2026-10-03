// Which text field the on-screen keyboard currently types into.

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
}

export const input = new InputFocus();
