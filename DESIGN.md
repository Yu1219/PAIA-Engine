# PAIA Workbench UI

Preserve the existing research workbench: its Japanese copy, annotation semantics, green identity, portable/offline assets and input → settings → results workflow.

## Visual system

- Warm pale background, white work surfaces, deep green navigation. Teal marks primary actions and selection. Warning and error colors have distinct meanings.
- Local system sans fonts. No CDN or downloaded font is needed to operate the app.
- Base 16px rem. Controls and data use 13–14px on desktop; supporting text is at least 12px. Mobile text inputs use 16px. Headings have a restrained fixed scale.
- Spacing uses 4/8/12/16/20/24/32/40px. Work surfaces use a 12px radius and a single border. Controls use 7px.
- Line icons use a 24×24 viewBox, 1.7px stroke and rounded ends. The P monogram remains the brand.
- Controls are at least 42px high on desktop and 44px on narrow screens. Keep visible focus rings and tabular data numerals.
- On narrow screens navigation moves above the content, input steps stack, filters form a grid and tables scroll within their container. Detail dialogs keep heading and save/close actions visible while content scrolls.
- Short transitions indicate state. Respect reduced-motion preferences. No page entrance choreography.

## Verification

Walk input, offline sample, all-attribute results, combined filters, empty matches, details, CSV save, project save and error recovery at desktop, intermediate and phone widths. Check keyboard focus and modal dismissal. Real browser inspection supplements the automated state tests.
