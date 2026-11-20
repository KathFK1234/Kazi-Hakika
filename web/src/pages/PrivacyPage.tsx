import { useTitle } from '../useTitle'
import { Link } from 'react-router'

export function PrivacyPage() {
  useTitle('Your data')
  return (
    <article className="prose">
      <h1>Your data, in plain words</h1>
      <p className="muted">
        This is a short notice while the service is being built. A full privacy policy and terms come before launch.
      </p>

      <h2>What we store</h2>
      <ul>
        <li>Your email address, a password hash (never the password itself) and the public handle you choose.</li>
        <li>The roles you track: title, company, link, stage, dates, salary note and your notes, plus when each stage changed.</li>
        <li>Whether your email is confirmed and whether you want reminder emails.</li>
      </ul>

      <h2>What we don't store</h2>
      <ul>
        <li>No CVs, phone numbers, dates of birth or ID numbers. Please don't paste them into notes.</li>
        <li>No tracking or advertising scripts. Your IP address is held only in memory for a short time to stop password guessing; it isn't saved.</li>
        <li>No AI model runs on our side.</li>
      </ul>

      <h2>Who else handles it</h2>
      <ul>
        <li>Railway hosts the app and its database.</li>
        <li>Resend sends our emails (confirmation, password reset and the daily reminder), so it sees your email address and the email's content, and keeps its own delivery logs.</li>
      </ul>

      <h2>How long we keep it</h2>
      <ul>
        <li>Your account and applications stay until you delete them.</li>
        <li>An account whose email is never confirmed and which never tracks a role is deleted 30 days after sign-up.</li>
        <li>Sign-ins expire after 14 days; confirmation and reset links after 24 hours and 1 hour.</li>
      </ul>

      <h2>Your choices</h2>
      <ul>
        <li>Turn reminder emails off at any time in Settings.</li>
        <li>Download everything we hold about you as a file from Settings.</li>
        <li>Delete your account in Settings. That permanently removes your account and every application from our database straight away.</li>
      </ul>
      <p>
        <Link to="/">Back to the app</Link>
      </p>
    </article>
  )
}
