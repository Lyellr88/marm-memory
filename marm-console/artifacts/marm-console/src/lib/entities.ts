/** Decode the HTML entities MARM stores in memory content.
 *
 *  `sanitize_content` HTML-escapes on the way IN, so the stored value carries
 *  `&#x27;` and `&quot;` rather than the characters the writer typed. Every
 *  consumer here treats that value as plain text -- JSX escapes it again -- so
 *  the reader sees the entity itself, and an edit round-trip re-escapes it
 *  (`&#x27;` -> `&amp;#x27;`), corrupting the memory a little more each save.
 *
 *  Decoding at the boundary fixes both: text reads as written, and an edit
 *  sends back what the server can escape exactly once.
 *
 *  Uses an explicit map rather than innerHTML: assigning untrusted content to
 *  innerHTML to decode it is the injection this escaping exists to prevent.
 */
const ENTITIES: Record<string, string> = {
  '&amp;': '&',
  '&lt;': '<',
  '&gt;': '>',
  '&quot;': '"',
  '&#x27;': "'",
  '&#39;': "'",
  '&#x2F;': '/',
};

export function decodeEntities(text: string | null | undefined): string {
  if (!text) return '';
  // `&amp;` last would double-decode `&amp;lt;` into `<`; the single pass with
  // an alternation regex visits each entity once, so nested escapes survive as
  // the literal text they represent.
  return text.replace(
    /&(?:amp|lt|gt|quot|#x27|#39|#x2F);/g,
    (m) => ENTITIES[m] ?? m,
  );
}
