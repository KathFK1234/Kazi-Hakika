// Railway infrastructure for Kazi Hakika: one web service, one daily cron
// job and one Postgres. Preview with `railway config plan`, apply with
// `railway config apply`. Variables are unmanaged: this file never sets or
// deletes them. They are set with `railway variables` (README "Deploy
// (Railway)" lists them), so no secret ever lives here.
import { defineRailway, github, postgres, project, service } from "railway/iac";

const REPO = "KathFK1234/Kazi-Hakika";
// Amsterdam: the closest Railway region to Nairobi.
const REGION = "europe-west4-drams3a";
const DOMAIN = "kazi-hakika.up.railway.app";

// Cost caps per container (README "Cost guardrails").
const LIMITS = { containers: { cpu: 0.5, memoryBytes: 512 * 1024 * 1024 } };

// Only changes that reach the image trigger a rebuild.
const WATCH = [
  "Dockerfile",
  "requirements.txt",
  "alembic.ini",
  "app/**",
  "migrations/**",
  "scripts/**",
  "web/**",
  // Vitest files never reach the image.
  "!web/**/*.test.ts",
  "!web/**/*.test.tsx",
  "!web/src/test/**",
];

// GitHub checks can't gate deploys while Actions is billing-locked; every
// push runs the full checks locally first.
const source = github(REPO, { branch: "main", checkSuites: false });
const build = { builder: "DOCKERFILE" as const, dockerfilePath: "Dockerfile", watchPatterns: WATCH };

export default defineRailway(() => {
  const db = postgres("Postgres", { region: REGION });

  const web = service("web", {
    source,
    build,
    deploy: {
      // Image default: scripts/start-web.sh (migrate as owner, then serve).
      healthcheckPath: "/health",
      healthcheckTimeout: 120,
      sleepApplication: true,
      // Restarts on failure (Railway's default policy), at most 3 times.
      restartPolicyMaxRetries: 3,
      limitOverride: LIMITS,
    },
    replicas: { [REGION]: 1 },
    networking: { serviceDomains: { [DOMAIN]: { port: 8000 } } },
  });

  const daily = service("daily", {
    source,
    build,
    deploy: {
      startCommand: "python -m app.jobs.daily",
      // 03:00 UTC is 06:00 in Nairobi. Runs, sends, exits.
      cronSchedule: "0 3 * * *",
      restartPolicyType: "NEVER",
      limitOverride: LIMITS,
    },
    replicas: { [REGION]: 1 },
  });

  // `variables` isn't in the SDK's types yet (3.17); the CLI reads it.
  return project("kazi-hakika", {
    variables: { managed: false },
    resources: [db, web, daily],
  } as never);
});
