# WS-3 Frontend Theme / Vitest — Implementation Report

**Date:** 2026-02-26  
**Workstream:** WS-3 (group-1)  
**Status:** ✅ COMPLETE

---

## Summary

This workstream implemented:
1. A `ThemeProvider` context with dark/light mode toggle
2. A theme-toggle button in the `TopBar` component (Sun/Moon icon)
3. Bulk replacement of all hardcoded hex colours with semantic CSS variable–backed Tailwind classes
4. Vitest configuration and a baseline test suite (25 tests, all passing)
5. Production build verified (TypeScript + Vite, zero errors)

---

## Files Changed

### New Files

| File | Purpose |
|------|---------|
| `src/providers/theme-provider.tsx` | `ThemeProvider` + `useTheme` hook |
| `src/tests/setup.ts` | Vitest global setup (jest-dom matchers) |
| `src/tests/theme-provider.test.tsx` | 10 unit tests for ThemeProvider |
| `src/tests/topbar.test.tsx` | 5 unit tests for TopBar theme toggle |
| `src/tests/cn.test.ts` | 10 unit tests for `cn` and `generateNodeId` utilities |
| `vitest.config.ts` | Vitest configuration with happy-dom environment |

### Modified Files

| File | Change |
|------|--------|
| `src/styles/globals.css` | Added `--surface-base`, `--surface-raised`, `--surface-overlay`, `--surface-border` CSS variable tokens for both `:root` (light) and `.dark` themes |
| `tailwind.config.ts` | Extended `colors` with `surface.base`, `surface.raised`, `surface.overlay`, `surface.border` mapped to CSS variables |
| `src/App.tsx` | Wrapped app with `<ThemeProvider>`, replaced `bg-[#0f1117]` loading state |
| `src/layouts/AppLayout.tsx` | Replaced `bg-[#0f1117]` with `bg-surface-base` |
| `src/components/navigation/TopBar.tsx` | Added `useTheme` hook, `Sun`/`Moon` lucide icons, and theme toggle button |
| `package.json` | Updated `test` script, added `test:watch` and `test:coverage` scripts; added vitest, @testing-library/* and happy-dom dev dependencies |
| ~200 `.tsx` files | Bulk sed replacement of hardcoded hex colours (see below) |

---

## Colour Replacement Map

All replacements were performed with `sed -i` across `src/**/*.tsx`. `text-white` and `text-gray-400` were **not touched**.

| Old hardcoded class | New semantic class | Occurrences replaced |
|---------------------|-------------------|----------------------|
| `bg-[#0f1117]` | `bg-surface-base` | 170 |
| `bg-[#1a1d27]` | `bg-surface-raised` | 258 |
| `bg-[#12141e]` | `bg-surface-overlay` | 67 |
| `bg-[#2a2d37]` | `bg-surface-border` | 9 |
| `bg-[#0a0c10]` | `bg-surface-base` | 3 |
| `bg-[#141620]` | `bg-surface-base` | 2 |
| `bg-[#0d0f17]` | `bg-surface-base` | 2 |
| `bg-[#1e2130]` | `bg-surface-raised` | 1 |
| `bg-[#0e1017]` | `bg-surface-base` | 1 |
| `border-[#2a2d37]` | `border-surface-border` | 578 |
| `border-[#12141e]` | `border-surface-overlay` | 15 |
| `border-[#3a3d47]` | `border-surface-border` | 1 |

**Total replacements: ~1,107**  
**Zero hardcoded hex colours remain** (verified with grep post-replacement).

---

## CSS Variable Tokens

### Dark theme (`.dark` class on `<html>`)

```css
--surface-base:    228 13% 8%;   /* was #0f1117 */
--surface-raised:  229 20% 12%;  /* was #1a1d27 */
--surface-overlay: 230 22% 9%;   /* was #12141e */
--surface-border:  228 13% 19%;  /* was #2a2d37 */
```

### Light theme (`:root` / no `.dark` class)

```css
--surface-base:    220 20% 97%;
--surface-raised:  0 0% 100%;
--surface-overlay: 220 15% 95%;
--surface-border:  214.3 31.8% 88%;
```

---

## ThemeProvider Details

- **Storage:** `localStorage` key `archon-theme`
- **Default:** OS preference (`prefers-color-scheme`), falls back to `dark`
- **DOM:** Applies `dark` or `light` class to `document.documentElement`
- **Persistence:** Survives page reload via localStorage
- **API:** `useTheme()` → `{ theme, toggleTheme, setTheme }`

---

## Vitest Configuration

```
environment: happy-dom
setupFiles: src/tests/setup.ts
include: src/**/*.{test,spec}.{ts,tsx}
coverage: v8 provider
```

New packages added to `devDependencies`:
- `vitest@^3.0.0`
- `@testing-library/react@^16.3.0`
- `@testing-library/dom@^10.4.0`
- `@testing-library/user-event@^14.5.2`
- `@testing-library/jest-dom@^6.6.3`
- `@vitest/coverage-v8@^3.0.0`
- `happy-dom@^16.0.0`

---

## Test Results

```
 ✓ src/tests/cn.test.ts              (10 tests)
 ✓ src/tests/theme-provider.test.tsx (10 tests)
 ✓ src/tests/topbar.test.tsx         ( 5 tests)

 Test Files  3 passed (3)
      Tests  25 passed (25)
   Duration  1.30s
```

### Test Coverage

| Test File | What's Covered |
|-----------|---------------|
| `theme-provider.test.tsx` | Default theme, defaultTheme prop, DOM class application, toggle dark→light, toggle light→dark, setTheme, localStorage persistence, localStorage read on mount, useTheme error outside provider |
| `topbar.test.tsx` | Theme toggle button presence, correct aria-label per theme, toggle interaction, user initials, hamburger menu callback |
| `cn.test.ts` | Class merging, Tailwind conflict dedup, falsy values, object syntax, empty input, arrays, text-white preservation, text-gray-400 preservation, generateNodeId format, uniqueness |

---

## Build Verification

```
$ npm run build
> tsc -b && vite build

✓ 2614 modules transformed.
dist/index.html                     0.54 kB │ gzip:   0.35 kB
dist/assets/index-uHcULAlu.css     75.58 kB │ gzip:  12.67 kB
dist/assets/index-Biz8nq-t.js   1,584.17 kB │ gzip: 413.51 kB

✓ built in 4.24s
```

TypeScript: ✅ zero errors  
Vite build: ✅ success  
Note: The large bundle warning is pre-existing (entire app in one chunk) and unrelated to WS-3.

---

## How to Use

```bash
# Run tests
cd frontend && npm test

# Watch mode
npm run test:watch

# Coverage report
npm run test:coverage

# Build
npm run build
```

### Theme Toggle

The Sun/Moon button appears in the top-right area of the TopBar, between the notification bell and the user avatar. Click it to switch between dark and light mode. The preference is persisted to `localStorage`.

### Adding New Components

Use the semantic surface classes instead of hardcoded hex values:

```tsx
// ✅ Correct — theme-aware
<div className="bg-surface-base border border-surface-border">

// ❌ Wrong — hardcoded, breaks light theme
<div className="bg-[#0f1117] border border-[#2a2d37]">
```
