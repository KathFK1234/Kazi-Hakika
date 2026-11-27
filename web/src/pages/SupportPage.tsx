import { Link } from 'react-router'
import { useTitle } from '../useTitle'

// The owner supplies the contact details (SPEC 3b.8). None are listed until
// they do: never invent phone numbers or organisations here.
export function SupportPage() {
  useTitle('Support')
  return (
    <article className="prose">
      <h1>Support</h1>
      <p>
        Looking for work is hard, and thinking about your career can stir up a lot. Feeling worn out, worried or low
        during a job search is common, and it isn&apos;t a sign that you&apos;re doing anything wrong.
      </p>
      <p>
        Dira is a place to reflect, not advice or therapy. If things feel heavy, please talk to someone you trust: a
        friend, family member, mentor or a health professional.
      </p>
      <h2>People who can help</h2>
      <p className="notice" role="note">
        We&apos;re checking which support services to list here, so that every contact is real and current. They will
        appear on this page soon.
      </p>
      <p>
        <Link to="/dira">Back to Dira</Link>
      </p>
    </article>
  )
}
