# Frontend UI rules

- Follow `DESIGN_SYSTEM.md`. `src/tokens.css` is the canonical typography and color hierarchy.
- Use semantic `--font-*` and `--color-*` tokens. Do not introduce component-specific font sizes, weights, or literal colors. Add or change shared roles deliberately in the token file and document the change.
- Keep the full-height sidebar and bottom composer invariant. Content and navigation scroll independently; never return to a fixed 960px page height.
- Use Untitled UI for application interface icons.
- Keep Agentation development-only. Third-party tooling owns its internal styles.
- Preserve local demo boundaries until a real backend contract is supplied. Do not introduce wallet seeds or provider credentials into browser code.
