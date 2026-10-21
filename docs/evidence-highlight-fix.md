# Visible document citation selection

Opening a citation selected its document segment, but long Markdown files remained scrolled to the beginning and the pale selected border was easy to miss.

The document viewer now scrolls the selected passage into view after its page loads. Selected text has a yellow background, a stronger amber left border and a visible “Cited passage” label. Manual selections use “Selected passage”; the linked citation identity remains distinct. The active passage exposes `aria-current="location"`, and the text stays literal React content rather than interpreted HTML.

This highlights the stored cited segment. Semantic retrieval does not provide word-level model attribution, so the UI does not invent query-word matches. PDF/OCR region overlays and original revision/citation access checks remain unchanged.

Validation: strict TypeScript and the Vite production build passed, including the Compose frontend build. The change touches only document presentation; it requires no re-ingestion or re-indexing. The deployed JavaScript and CSS were fetched and matched byte hashes of the checked production build; the scroll, label and yellow-highlight code are present. Visual browser verification remains pending because the inspected app session is signed out.
