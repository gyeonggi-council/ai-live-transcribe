declare module 'jest-axe' {
  export function toHaveNoViolations(): void;
  export function axe(html: Element): Promise<{ violations: unknown[] }>;
}
