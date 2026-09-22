import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const cssPath = resolve(process.cwd(), 'src/styles/variables.css');

const css = readFileSync(
  cssPath,
  'utf8',
);

describe('global dark select styles', () => {
  it('keeps the dark color scheme', () => {
    expect(css).toContain('color-scheme: dark;');
  });

  it('sets an explicit dark theme for select controls', () => {
    expect(css).toMatch(
      /select\s*\{[^}]*background-color:\s*var\(--panel-bg\);[^}]*color:\s*var\(--text-primary\);/s,
    );
  });

  it('sets an explicit dark theme for options and option groups', () => {
    expect(css).toMatch(
      /option\s*,\s*optgroup\s*\{[^}]*background-color:\s*var\(--bg-secondary\);[^}]*color:\s*var\(--text-primary\);/s,
    );
  });

  it('keeps disabled selects readable', () => {
    expect(css).toMatch(
      /select:disabled\s*\{[^}]*background-color:\s*var\(--bg-secondary\);[^}]*color:\s*var\(--text-muted\);/s,
    );
  });

  it('does not use light or system colors for the select theme', () => {
    expect(css).not.toMatch(
      /(?:background-color|color):\s*(?:white|#fff(?:fff)?|Canvas|CanvasText)\s*;/i,
    );
  });
});
