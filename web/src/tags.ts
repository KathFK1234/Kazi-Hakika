/** "backend, AI infra" -> ["backend", "ai-infra"]; the API checks the rest. */
export function parseTags(text: string): string[] {
  return text
    .split(',')
    .map((t) => t.trim().toLowerCase().split(/\s+/).join('-'))
    .filter(Boolean)
}
