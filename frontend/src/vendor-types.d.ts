// Temporary minimal typings. @types/react and @types/react-dom are not in the
// ADR-0001 baseline (needs-human request in task T-003). Delete this file once
// they are approved and installed. react-router ships its own types.
declare module "react/jsx-runtime" {
  export const jsx: unknown;
  export const jsxs: unknown;
  export const Fragment: unknown;
  export namespace JSX {
    type Element = unknown;
    interface IntrinsicElements {
      [tag: string]: Record<string, unknown>;
    }
  }
}

declare module "react" {
  export function StrictMode(props: { children?: unknown }): unknown;
  export interface FormEvent<T = Element> {
    preventDefault(): void;
    currentTarget: T;
  }
  export function useState<S>(
    initial: S | (() => S),
  ): [S, (value: S | ((prev: S) => S)) => void];
}

declare module "react-dom/client" {
  export function createRoot(container: Element): { render(node: unknown): void };
}
