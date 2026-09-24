/** Decode the entities `html.escape()` stored, in a single pass so a literal
 *  stored `&amp;lt;` stays `&lt;`. A fixed map, never innerHTML. */
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
  return text.replace(
    /&(?:amp|lt|gt|quot|#x27|#39|#x2F);/g,
    (m) => ENTITIES[m] ?? m,
  );
}
