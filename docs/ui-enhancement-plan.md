# VideoMind UI enhancement plan

Date: 21 October 2026. Status: proposed and drafted for the `feat/ui-enhancements` branch.

## 1. Objective and scope

This plan outlines the visual and architectural interface enhancements for the VideoMind multimodal intelligence platform. The work builds upon the product UX foundation established in [product-ux-plan.md](product-ux-plan.md), upgrading the user interface from a prototype look to a production-grade, executive multimodal intelligence workstation.

The primary goals are:

- Introduce a cohesive modern design system featuring an executive slate dark palette, a clean light palette, and emerald and electric cyan accents.
- Implement an omnibar search interface with inline keyboard shortcuts, search mode toggles (text versus visual image matching), and quick modality filter chips.
- Elevate the side-by-side Evidence Inspector with interactive timeline range highlighting for video and audio, word-level synchronized Whisper transcript seeking, and coordinate-based bounding box visualization for OCR document pages.
- Refine navigation and app shell ergonomics with live worker readiness pulse indicators and compact metadata badges.
- Preserve all existing backend API contracts, access control guarantees, immutable locators, and automated test suites.

## 2. Design system and visual foundation

The visual foundation uses pure CSS variables and utility classes in [frontend/src/app/styles.css](../frontend/src/app/styles.css) without requiring heavy third-party CSS frameworks.

### Color tokens

- Base background: `#0c1015` (dark) / `#f8fafc` (light)
- Elevated surfaces: `#141b24`, `#1a2330`, `#222d3d`
- Borders: Subtle `rgba(255, 255, 255, 0.08)`, medium `rgba(255, 255, 255, 0.14)`
- Primary accent: Emerald `#10b981` (primary action, high confidence score, verified match indicator)
- Secondary accents: Cyan `#06b6d4` (speech transcript / temporal media), amber `#f59e0b` (document OCR / bounding boxes), purple `#8b5cf6` (audio intervals)
- Typography: Outfit for headers, Inter for interface elements and body text, JetBrains Mono for locators and timecodes

### Elevation and micro-interactions

- Subtle glassmorphic backdrops on headers and sticky navigation bars (`backdrop-filter: blur(12px)`).
- Pill-shaped modality badges with colored accents indicating match confidence and representation type.
- Active card elevation with glowing border accents and smooth transition effects (`0.2s ease`).
- Accessible keyboard focus rings retaining high contrast and WCAG AA compliance.

## 3. Functional area enhancements

### Navigation and application shell

- Brand block: Gradient logo icon with clear application title and tagline.
- Main navigation: Re-styled navigation items with count badges and active indicators.
- System health card: Live pulsating status dot indicating local Docker, Celery worker, and pgvector readiness.
- Top contextual bar: Streamlined workspace selector and account profile pill.

### Search workbench and omnibar

- Centralized search omnibar with integrated search icon, hotkey indicator (`Ctrl + K`), and primary search trigger.
- Mode switcher: Toggle between Natural Language Query and Visual Image Query.
- Quick modality filter chips (`All`, `Video`, `Documents`, `Audio`, `High Confidence`) for rapid facet switching.
- Enhanced search result cards:
  - Match confidence percentage pill calculated from ranking scores.
  - Modality badges with distinct styling for Extracted Text, Scanned OCR, Speech Transcript, and Visual Matches.
  - Inline snippet highlighting using styled `<mark>` elements.
  - Clear inspection affordance ("Inspect Evidence") directly triggering the inspector workbench.

### Evidence inspector

- Video and audio playback:
  - Video player mockup container with playback controls.
  - Interactive timeline rail with progress indicator and highlighted evidence range segment.
  - Synchronized Whisper speech transcript with word-level click targets that support seeking to exact timestamps.
  - Immutable locator banner with one-click citation link copying and feedback toast.
- Document and scanned page inspection:
  - Document sheet preview container with coordinate bounding box highlight overlays for OCR extractions.
  - Extracted text passage pane with confidence metrics and passage selection highlights.

## 4. Phase-by-phase implementation

### Phase 1: Design tokens and base styles

- Add typography imports to [frontend/index.html](../frontend/index.html).
- Update [frontend/src/app/styles.css](../frontend/src/app/styles.css) with CSS variables for dark and light modes, typography, elevation shadows, glassmorphic utilities, and badges.

### Phase 2: Shell and navigation components

- Update [frontend/src/app/App.tsx](../frontend/src/app/App.tsx) with the new sidebar layout, system health card, and top header bar.

### Phase 3: Search omnibar and result cards

- Update [frontend/src/features/search/Search.tsx](../frontend/src/features/search/Search.tsx) with the omnibar layout, modality chips, and redesigned result cards.

### Phase 4: Evidence inspection components

- Update [frontend/src/features/evidence/MediaViewer.tsx](../frontend/src/features/evidence/MediaViewer.tsx) to support timeline highlights and interactive word-level transcript seeking.
- Update [frontend/src/features/evidence/DocumentViewer.tsx](../frontend/src/features/evidence/DocumentViewer.tsx) for enhanced bounding box presentation.

### Phase 5: Verification and testing

- Run `pnpm --dir frontend build` to verify strict TypeScript and Vite compilation.
- Run `pnpm --dir frontend test:ui` to ensure no accessibility or navigation regressions.
- Verify responsiveness across desktop (1500px), tablet (1100px), and mobile (700px) viewports.

## 5. Constraints and invariants

- Do not alter backend API request/response contracts.
- Maintain workspace authorization and role validation on all evidence links.
- Retain accessibility landmarks (`<aside>`, `<main>`, `<header>`, `role="alert"`, `aria-label`).
- Keep all local processing running on Linux CPU installation without introducing cloud dependencies.
