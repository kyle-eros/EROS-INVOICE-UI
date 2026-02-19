# Visual QA Checklist

## Brand Consistency
- [ ] EROS wordmark appears with consistent casing/spacing on `/` and `/admin`.
- [ ] Tokenized palette is used consistently for text, borders, surfaces, and accents.
- [ ] Typography hierarchy is consistent: display serif for headings, sans-serif for body copy.

## Accessibility (WCAG AA Core)
- [ ] Primary text and interactive controls meet AA contrast expectations.
- [ ] Keyboard navigation reaches skip link, links, forms, and table content in logical order.
- [ ] Focus-visible rings are present and distinguishable.
- [ ] Table semantics remain valid (`caption`, `thead`, `th scope="col"`).
- [ ] Error state uses `role="alert"` and is understandable without color-only cues.

## Responsive Behavior
- [ ] No horizontal overflow at 320px width.
- [ ] Hero and card layouts reflow correctly at tablet widths (~768px).
- [ ] Desktop layout keeps clear hierarchy and balanced spacing.
- [ ] Data tables remain readable with horizontal scroll shell on narrow screens.

## Admin State Handling
- [ ] Normal task/reminder/admin data state renders correctly.
- [ ] Empty task list shows intended empty state.
- [ ] Reminder API failure shows alert panel/error text.
- [ ] Queue metric card reflects error and non-error state correctly.
- [ ] Creator Balances Owed section renders Jan full invoice + Feb current owed columns correctly for the focus year.
- [ ] Creator Balances Owed section shows non-USD exclusion note when applicable.

## Creator Portal States
- [ ] `/portal` summary card shows January full invoice totals and February current owed totals for the focus year.
- [ ] `/portal` invoice table is filtered to January/February focus-year rows only.
- [ ] Invoice table status badge matches backend status (`open`, `partial`, `overdue`, `escalated`, `paid`).
- [ ] Currency column renders correctly and Amount Paid + Balance Due values use the invoice currency.
- [ ] Open/overdue invoice rows show a `Click here to confirm payment submitted` action, and submitted rows show a non-clickable submitted state.
- [ ] No stale claims about “marking invoices paid” appear anywhere in portal/home copy.

## Invoice Detail + PDF Experience
- [ ] `/portal/invoices/[invoiceId]` renders invoice summary tiles (status, totals, reminders) without layout break.
- [ ] `Open in new tab` and `Download PDF` controls both work.
- [ ] Embedded PDF loads in desktop Chrome/Safari and remains usable on mobile.
- [ ] If embedded viewer fails, fallback guidance is visible.
- [ ] PDF header shows invoice id, issue date, due date, and current status.
- [ ] PDF totals clearly show invoice total, amount paid, and balance due.

## Conversation Inbox States
- [ ] Empty conversation inbox state renders clear operator message.
- [ ] Conversation API failure state renders clear error text.
- [ ] Populated inbox renders thread rows with creator/contact fallback.
- [ ] Thread status labels are readable (`open`, `human_handoff`, etc.).
- [ ] Long message previews truncate/wrap cleanly without layout break.

## Motion + Reduced Motion
- [ ] Reveal/hover transitions are subtle and intentional.
- [ ] `prefers-reduced-motion: reduce` disables non-essential animation.

## Regression Checks
- [ ] `npm run status` shows no active guarded dev process before build/start checks.
- [ ] `npm run clean` succeeds when stale `.next` artifacts exist.
- [ ] `npm run lint` passes in `frontend/`.
- [ ] `npm run build` passes in `frontend/`.
- [ ] `./scripts/check_baseline.sh` passes at repo root.
- [ ] `npm audit --audit-level=high` reports no high/critical vulnerabilities.
