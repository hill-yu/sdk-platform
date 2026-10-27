import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const cssPath = resolve(process.cwd(), 'src/styles/variables.css');

const css = readFileSync(
  cssPath,
  'utf8',
);

describe('global light theme styles', () => {
  it('uses the light color scheme', () => {
    expect(css).toContain('color-scheme: light;');
  });

  it('sets explicit light theme tokens for select controls', () => {
    expect(css).toMatch(
      /select\s*\{[^}]*background-color:\s*var\(--panel-bg\);[^}]*color:\s*var\(--text-primary\);/s,
    );
  });

  it('sets explicit light theme tokens for options and option groups', () => {
    expect(css).toMatch(
      /option\s*,\s*optgroup\s*\{[^}]*background-color:\s*var\(--panel-bg\);[^}]*color:\s*var\(--text-primary\);/s,
    );
  });

  it('keeps disabled selects readable', () => {
    expect(css).toMatch(
      /select:disabled\s*\{[^}]*background-color:\s*var\(--disabled-bg\);[^}]*color:\s*var\(--disabled-text\);/s,
    );
  });

  it('defines semantic status tokens for shared component states', () => {
    expect(css).toContain('--success-text: #15803d;');
    expect(css).toContain('--warning-text: #b45309;');
    expect(css).toContain('--error-text: #b91c1c;');
    expect(css).toContain('--focus-ring: #2563eb;');
  });
});
