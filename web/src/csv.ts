// The API takes up to 60,000 characters per upload; split on line ends.
const CHUNK = 50_000

/** Split a CSV into pieces under CHUNK characters, each starting with the header row. */
export function chunkCsv(text: string, size = CHUNK): string[] {
  const lines = text.replace(/\r\n/g, '\n').split('\n')
  const header = lines.shift() ?? ''
  const chunks: string[] = []
  let current: string[] = []
  let length = header.length
  for (const line of lines) {
    if (!line.trim()) continue
    if (current.length && length + line.length + 1 > size) {
      chunks.push([header, ...current].join('\n'))
      current = []
      length = header.length
    }
    current.push(line)
    length += line.length + 1
  }
  if (current.length || chunks.length === 0) chunks.push([header, ...current].join('\n'))
  return chunks
}
