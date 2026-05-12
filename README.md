# Meal Planning

> This is a public template repo. The author's personal instance lives in a separate private repo; only the automation lives here. Click **Use this template** to spin up your own private copy.

Automated weekly dinner planning, powered by Claude Code running in GitHub Actions.

## What it does

- **Every Saturday at 8am ET:** A GitHub Action invokes Claude with access to this repo. Claude reads the meal history, generates 7 dinners for Mon–Sun, verifies recipe URLs, commits the plan, and a follow-up step emails it to the configured recipients via Resend.
- **Every day at 7am ET:** A GitHub Action (no Claude) reads the current week's plan, finds today's dinner, and emails a short reminder to the configured recipients.

## Architecture

```
GitHub Actions (Sat 8am)  →  Claude generates plan  →  commits to repo  →  Python script sends email
GitHub Actions (daily 7am)  →  Python script reads plan  →  sends email
```

The daily reminder is intentionally Claude-free — parsing one file and sending a templated message doesn't need an LLM, and running plain Python is faster, cheaper, and more reliable.

## Files

| Path | Purpose |
|---|---|
| `meal-history.md` | Running log of dinners. You and your partner add ratings + notes during the week. |
| `current-week.md` | The active 7-day plan. Overwritten every Saturday. |
| `notes.md` | Forward-looking notes for the next plan (camping trips, school events, ingredients to use up). Edit anytime; Saturday's run reads it and prunes used entries. |
| `family-context.md` | Standing household preferences: ages, dietary constraints, dislikes, kid blockers, equipment. Edit when something changes. |
| `config.yml` | Email recipients, timezone. |
| `prompts/weekly-plan.md` | The prompt Claude runs on Saturday. |
| `scripts/send_weekly_plan.py` | Reads `current-week.md`, sends weekly plan email. |
| `scripts/send_daily_reminder.py` | Reads `current-week.md`, sends today's reminder. |
| `.github/workflows/weekly-plan.yml` | Sat 8am cron → invoke Claude → run send script. |
| `.github/workflows/daily-reminder.yml` | Daily 7am cron → run send script. |

## Initial setup

### 1. Create the repo

Create a **private** GitHub repo (e.g., `yourname/meal-planning`) and push this directory.

### 2. Generate a Claude Code OAuth token

The weekly planning run authenticates as your Claude account (Max subscription), not via a pay-per-token API key. Generate a long-lived token:

```bash
claude /status          # confirm you're logged in as the Max account
claude setup-token      # opens a browser, prints an sk-ant-oat01-... token
```

Copy the printed token — you won't be able to see it again. Usage counts against your Max plan's allotment rather than being billed per token. (If you'd rather use a pay-per-token API key, swap `claude_code_oauth_token:` for `anthropic_api_key:` in `.github/workflows/weekly-plan.yml` and use an `ANTHROPIC_API_KEY` secret instead.)

### 3. Get a Resend API key

Sign up at https://resend.com (free tier: 100 emails/day, 3000/month). Get an API key from the dashboard.

Optionally, verify a domain you own so emails send from `meals@yourdomain.com` instead of the default. For a family of two recipients, the default `onboarding@resend.dev` sender is fine to start.

### 4. Add GitHub secrets

In your repo → Settings → Secrets and variables → Actions → New repository secret. Add:

- `CLAUDE_CODE_OAUTH_TOKEN` — the token from `claude setup-token`
- `RESEND_API_KEY` — your Resend key

### 5. Edit `config.yml`

Fill in real email addresses. Defaults in the file are placeholders.

### 6. Seed `meal-history.md` (optional)

If you've got a few recent meals in mind, add them so the first week's plan has some history to avoid repeating. Otherwise Claude treats history as empty and builds up from there.

### 7. Test manually before waiting for cron

Both workflows have `workflow_dispatch` enabled, so you can trigger them by hand from the Actions tab. Run `weekly-plan` first. Verify the email arrives and the files are committed. Then run `daily-reminder` and verify that arrives.

### 8. Let it ride

The cron schedules are already set. Saturdays at 8am ET, daily at 7am ET.

## Bring! integration (optional)

After the weekly plan is generated, the shopping list can be pushed to a shared [Bring!](https://www.getbring.com/) list so groceries curated by voice ("Alexa, add milk to Bring!") and groceries from the meal plan end up in one place.

**Setup:**

1. Create a Bring! account (or use an existing one). If you signed up with Google/Apple/Facebook, set a password via Profile → More settings → Change password.
2. In the GitHub repo, add two secrets:
   - `BRING_EMAIL` — the email on your Bring! account
   - `BRING_PASSWORD` — the password you just set
3. Add this block to `config.yml`:

   ```yaml
   bring:
     list_name: "Groceries"   # must match a list name in your Bring! account
   ```

The integration is opt-in by presence of the `bring:` block. If absent, the push step is a no-op.

**Behavior:**

- `push_to_bring.py` runs after URL validation. It parses the `## Shopping list` section of `current-week.md`, dedupes against items already on the list (active or recently purchased), and adds the rest.
- `bring_state.json` records what MealPlanner added. On re-fire for an already-planned week, `regenerate_guard.py` removes any of those items that are still unchecked on the list — purchased items are never resurrected.
- Bring! failures (auth, network, etc.) never fail the workflow. Email stays the source of truth.

## Weekly request emails (optional)

A Friday-morning email asks "what do you want for next week?" with a 3-section template. Reply on your phone, and Saturday's planner ingests it.

**Setup:**

1. Enable 2FA on the Google account you'll receive/reply from (Settings → Security).
2. Generate a Google app password (Settings → Security → 2-Step Verification → App passwords). It's 16 characters.
3. In the GitHub repo, add a secret:
   - `GMAIL_APP_PASSWORD` — the 16-char app password from step 2
4. Uncomment the `requests:` block in `config.yml` and set `gmail_user` to the account from step 1.
5. Manually trigger the `Friday Request Prompt` workflow from the Actions tab. Confirm the email arrives in your inbox.
6. Reply with content in any of the three sections. Send.
7. Manually trigger the `Weekly Meal Plan` workflow. Confirm:
   - The "Fetch next-week requests from inbox" step logs that it found your reply.
   - The committed `current-week.md` shows your requests acknowledged in the Plan notes.
   - Your reply is marked read in Gmail.

Only after that end-to-end test passes does the Friday cron become "real" for the household. The cron fires every Friday at 8am ET regardless.

**Reply format:**

The Friday email body is a template. Type under each heading on your phone:

```
## Must have / Must avoid
- no fish this week
- tacos one night

## Soft preferences
- lean Italian

## Use up
- arborio rice in the pantry
```

- **Must have / Must avoid** are treated as hard constraints. Conflicts with the 30-day no-repeat rule or family-context constraints get resolved in favor of your request; the override is called out in the Plan notes section of the email.
- **Soft preferences** bias the week but aren't absolute.
- **Use up** biases the planner toward dishes that incorporate those ingredients, ideally early in the week.

Multiple replies (e.g. you and your partner both reply) are merged per section with traceability comments.

**Behavior:**

- The Saturday workflow connects to Gmail via IMAP, fetches unread messages whose subject contains the magic tag `[meal-plan request: <upcoming-Monday>]`, validates the sender against the `allowlist` (defaults to `email_recipients`), strips quoted-reply content, splits the body by the three known headings, and writes `requests-inbox.md`.
- The Claude prompt reads that file and applies its sections during planning.
- After the plan is written, Claude deletes `requests-inbox.md` (it's gitignored, so a missed deletion doesn't leak into git history).
- Any failure in the inbound path is caught and logged. The weekly run proceeds without requests, falling back to `notes.md` + family-context behavior — same as today.

## Week-to-week habit

The only thing you need to do is **fill in ratings and notes in `meal-history.md`** during or after each week. GitHub's mobile web editor works fine for this — open the file, hit the pencil icon, type, commit. Without this, Claude can't identify mainstays or learn what's been a miss.

If anything unusual is coming up next week — travel, an event, an ingredient you want to use up — drop a bullet in `notes.md` before Saturday morning. The planner will adjust the week and clear the entry once it's used.

## Debugging

- **Workflow failed:** check the Actions tab → failed run → logs. Most common cause: missing secret or malformed `config.yml`.
- **Email didn't arrive:** check Resend's dashboard for delivery logs.
- **Claude suggested something I just ate:** check that `meal-history.md` has the recent meal with a date within 30 days. If yes, re-run the workflow and check logs.
- **Claude hallucinated a bad recipe URL:** the prompt tells it to verify, but LLMs still occasionally miss. If it happens often, tighten the prompt's verification step.

## Costs (rough monthly)

- Claude: weekly planning run authenticates with a Claude Max OAuth token, so usage counts against the existing Max allotment — **no additional Anthropic charge**. One run/week is a tiny fraction of Max's weekly cap.
- Resend: free tier covers this easily.
- GitHub Actions: free tier for public repos, 2000 minutes/month for private — this uses maybe 20 minutes/month.
- Total: **$0/month** on top of the Max subscription you already pay for.

## When to retire this

If after 3–4 months you never read the emails or always override the plan, kill it. You can disable workflows without deleting the repo (Settings → Actions → General → Disable).
