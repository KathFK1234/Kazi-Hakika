/** A link to the job ad, only for http(s) URLs (the API refuses others too). */
export function JobLink({ url, label = 'Open job ad' }: { url: string | null; label?: string }) {
  if (!url || !/^https?:\/\//i.test(url)) return null
  return (
    <a className="job-link" href={url} target="_blank" rel="noopener noreferrer">
      {label} <span aria-hidden="true">↗</span>
      <span className="visually-hidden"> (opens in a new tab)</span>
    </a>
  )
}
