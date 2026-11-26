import { Link } from 'react-router'
import { useTitle } from '../useTitle'

// What signed-out visitors see at /. Only claim what works today; anything
// planned sits under "Coming next".

const PREVIEW = [
  { stage: 'Saved', cards: [{ role: 'Frontend engineer', company: 'Fintech startup', due: 'Due in 5 days' }] },
  {
    stage: 'Applied',
    cards: [
      { role: 'Backend developer', company: 'Telco', due: 'Due tomorrow' },
      { role: 'Data analyst', company: 'Bank', due: 'Applied 3 days ago' },
    ],
  },
  { stage: 'Interview', cards: [{ role: 'QA engineer', company: 'Logistics firm', due: 'Interview on Friday' }] },
]

export function LandingPage() {
  useTitle('Job application tracker')
  return (
    <div className="landing">
      <section className="hero" aria-labelledby="hero-title">
        <div className="hero-text">
          <p className="eyebrow">
            <span lang="sw">Kazi hakika</span> means “verified work” in Kiswahili
          </p>
          <h1 id="hero-title">Keep every job application in one place</h1>
          <p className="lead">
            A free tracker for the roles you apply to, built first for tech job seekers in Kenya. Save each role, move it
            through your stages, and get a reminder before the deadline closes.
          </p>
          <div className="cta">
            <Link className="button primary" to="/signup">
              Create a free account
            </Link>
            <Link className="button" to="/login">
              Sign in
            </Link>
          </div>
          <p className="hint">Free to use. No CV upload, no phone number, no ads.</p>
        </div>

        <div className="preview" aria-hidden="true">
          {PREVIEW.map((column) => (
            <div className="preview-column" key={column.stage}>
              <p className="preview-stage">{column.stage}</p>
              {column.cards.map((card) => (
                <div className="preview-card" key={card.role}>
                  <p className="preview-role">{card.role}</p>
                  <p className="preview-meta">{card.company}</p>
                  <p className="preview-meta">{card.due}</p>
                </div>
              ))}
            </div>
          ))}
        </div>
      </section>

      <section aria-labelledby="today-title">
        <h2 id="today-title">What you can do today</h2>
        <ul className="feature-grid">
          <li>
            <h3>Track every role</h3>
            <p>
              Title, company, job link, deadline, salary note and your own notes. See them as a board by stage or as a
              list sorted by deadline. Drag cards on a computer, or use the Move menu on your phone.
            </p>
          </li>
          <li>
            <h3>Stay ahead of deadlines</h3>
            <p>
              A “due in the next 7 days” panel, and an optional morning email listing deadlines in the next 3 days. One
              email a day at most, and you can turn it off.
            </p>
          </li>
          <li>
            <h3>Keep your data yours</h3>
            <p>
              Only you can see your applications. Download everything as a file whenever you like, and delete your
              account for good in one step.
            </p>
          </li>
        </ul>
      </section>

      <section aria-labelledby="next-title">
        <h2 id="next-title">Coming next</h2>
        <p className="muted">Being built now; not available yet.</p>
        <ul className="next-list">
          <li>
            <strong>“Is this job real?”</strong> Paste a job ad or link and get plain warnings about fees, personal email
            addresses, WhatsApp-only contact and unlicensed overseas recruiters. No account needed.
          </li>
          <li>
            <strong>A shared board of roles</strong> other job seekers found, each run through the same automatic checks.
          </li>
          <li>
            <strong>Your own AI assistant, connected.</strong> Let Claude or ChatGPT read your tracker and help you
            prepare. It coaches; it never applies for you.
          </li>
          <li>
            <strong>Dira, your career compass.</strong> Optional check-ins on where you want your career to go, and how
            that changes over time.
          </li>
        </ul>
      </section>

      <section aria-labelledby="promise-title">
        <h2 id="promise-title">Our promises</h2>
        <ul className="promise-list">
          <li>We never apply for jobs or contact employers on your behalf.</li>
          <li>We never promise you a job. We help you stay organised and spot fake ads.</li>
          <li>We hold your tracker only: no CVs, phone numbers, ID numbers or tracking scripts.</li>
          <li>Free to use, run on a small budget with hard limits on cost.</li>
        </ul>
        <p>
          <Link to="/privacy">How we handle your data</Link>
        </p>
      </section>

      <section className="closing" aria-labelledby="closing-title">
        <h2 id="closing-title">Start with the roles you're already chasing</h2>
        <Link className="button primary" to="/signup">
          Create a free account
        </Link>
      </section>
    </div>
  )
}
