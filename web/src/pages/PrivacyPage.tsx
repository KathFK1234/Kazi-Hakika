import { useTitle } from '../useTitle'
import { Link } from 'react-router'
import { useFeatures } from '../features'

export function PrivacyPage() {
  useTitle('Your data')
  const { dira } = useFeatures()
  return (
    <article className="prose">
      <h1>Your data, in plain words</h1>
      <p className="muted">
        This is a short notice while the service is being built. A full privacy policy and terms come before launch.
      </p>

      <h2>Who is responsible</h2>
      <p>
        Kazi Hakika is run by Katheu Kilonzo, who decides how your data is used and is responsible for it (the data
        controller). For any question or request about your data, or to complain, write to{' '}
        <a href="mailto:fkatheukilonzo@gmail.com">fkatheukilonzo@gmail.com</a>. You can also complain to Kenya&apos;s
        Office of the Data Protection Commissioner.
      </p>

      <h2>What we store</h2>
      <ul>
        <li>Your email address, a password hash (never the password itself) and the public handle you choose.</li>
        <li>The roles you track: title, company, link, stage, dates, salary note and your notes, plus when each stage changed.</li>
        <li>Whether your email is confirmed and whether you want reminder emails.</li>
        <li>
          Roles you share on the board: title, company, link, location, deadline and the results of the automatic checks.
          These are public, shown with your handle (never your name or email). The ad text and agency name you paste to
          run the checks are used once and not saved.
        </li>
        <li>Reports you file about board roles: the reason and your note, seen only by you and the moderators.</li>
        <li>
          In your browser: one cookie that keeps you signed in (removed when you sign out or after 14 days) and, only if
          you pick one, your light or dark theme. Nothing is used for tracking.
        </li>
      </ul>

      <h2>What we don't store</h2>
      <ul>
        <li>No CVs, phone numbers, dates of birth or ID numbers. Please don't paste them into notes.</li>
        <li>No tracking or advertising scripts. Your IP address is held only in memory for a short time to stop password guessing; it isn't saved.</li>
        <li>No AI model runs on our side.</li>
        <li>
          Nothing you paste into <Link to="/check">Is this job real?</Link>. We only keep, for 7 days, when each
          website&apos;s domain was registered, so the same link gets the same answer quickly.
        </li>
      </ul>

      <h2>Who else handles it</h2>
      <ul>
        <li>Railway hosts the app and its database on servers in Amsterdam, the Netherlands (EU).</li>
        <li>
          Resend, a service based in the United States, sends our emails (confirmation, password reset and the daily
          reminder), so it sees your email address and the email&apos;s content, and keeps its own delivery logs.
        </li>
        <li>So your data is stored and processed outside Kenya, by these two providers only.</li>
        <li>
          To check a job link, our server visits it once and asks rdap.org and the domain&apos;s registry when the
          domain was registered. Those sites see a request from our server, never your details.
        </li>
      </ul>

      {dira && (
        <>
          <h2>Career check-ins (Dira)</h2>
          <ul>
            <li>
              Only if you use them: your check-in answers (the role you&apos;re aiming for, what excited, energised or
              drained you, what you&apos;d keep or change, and optional confidence ratings), your wins, learnings and
              goals, and the tags on your roles.
            </li>
            <li>
              This is the most private data we hold. Only you can see it: it is never shown on the board, never counted
              in any statistics and never written to our logs.
            </li>
            <li>
              Check-in reminders are off unless you turn them on, and the email holds only a link, never anything you
              wrote. Patterns are simple counts from your own tracker, worked out when you open the page.
            </li>
            <li>It is in your data download, and deleting a check-in, an entry or your account removes it for good.</li>
          </ul>
        </>
      )}

      <h2>How long we keep it</h2>
      <ul>
        <li>Your account and applications stay until you delete them.</li>
        <li>An account whose email is never confirmed and which never tracks a role is deleted 30 days after sign-up.</li>
        <li>
          Board roles leave the board after their deadline (or 60 days after posting if they have none) and are deleted
          180 days after that. Your reports are deleted with your account.
        </li>
        <li>Sign-ins expire after 14 days; confirmation and reset links after 24 hours and 1 hour.</li>
      </ul>

      <h2>Your choices</h2>
      <ul>
        <li>Turn reminder emails off at any time in Settings.</li>
        <li>Download everything we hold about you as a file from Settings.</li>
        <li>Delete your account in Settings. That permanently removes your account and every application from our database straight away.</li>
        <li>
          Delete any role you shared, at any time, from My posts. When you delete your account, your board posts stay
          up as posted by deleted-user unless you choose to delete them too.
        </li>
      </ul>
      <p>
        <Link to="/">Back to the app</Link>
      </p>
    </article>
  )
}
