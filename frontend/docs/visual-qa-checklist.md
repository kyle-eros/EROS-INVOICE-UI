# Visual QA Checklist

## Brand Consistency
- [ ] EROS wordmark appears with consistent casing, spacing, and accent treatment on both `/` and `/admin`.
- [ ] Tokenized palette is used consistently for text, borders, surfaces, and accents.
- [ ] Typography hierarchy is consistent: display serif for headings, sans-serif for body copy.

## Accessibility (WCAG AA Core)
- [ ] Primary text and interactive controls meet AA contrast expectations.
- [ ] Keyboard navigation reaches skip link, links, and all table content in logical order.
- [ ] Focus-visible rings are present and clearly distinguishable.
- [ ] Table semantics remain valid (`caption`, `thead`, `th scope="col"`).
- [ ] Error state uses `role="alert"` and is understandable without color-only cues.

## Responsive Behavior
- [ ] No horizontal page overflow at 320px viewport width.
- [ ] Hero content and card layouts reflow correctly on tablet widths (~768px).
- [ ] Desktop composition keeps clear hierarchy and balanced whitespace.
- [ ] Table remains readable on narrow screens via horizontal overflow shell.

## State Handling
- [ ] Normal data state renders complete table and status badges.
- [ ] Empty task list renders the designed empty state with action link.
- [ ] API failure renders the designed alert panel with retry affordance.
- [ ] Queue metric card reflects error vs non-error state correctly.

## Motion and Reduced Motion
- [ ] Reveal/hover transitions feel subtle and intentional.
- [ ] `prefers-reduced-motion: reduce` disables non-essential animation.

## Regression Checks
- [ ] `npm run status` reports no active guarded dev process before running build/start checks.
- [ ] `npm run clean` succeeds when stale `.next` artifacts need to be reset.
- [ ] `npm run lint` passes in `frontend/`.
- [ ] `npm run build` passes in `frontend/`.
- [ ] `./scripts/check_baseline.sh` passes at repository root.
- [ ] `npm audit --audit-level=high` reports no high/critical vulnerabilities.
