# PadelIQ web MVP

A self-contained interactive prototype for a padel video-analysis product.

## Run it

Open `index.html` directly in a modern browser, or serve this folder locally:

```sh
python3 -m http.server 8000
```

Then visit `http://localhost:8000`.

## Included

- Responsive player dashboard
- Public marketing homepage and subscription pricing
- Supabase email/password account creation, persistent sign-in and emailed password reset
- English, Spanish, Greek, German, Dutch, French and Italian interface selector
- Local player profile
- Video file selection and player identification
- Simulated background-analysis workflow
- Per-shot performance scores
- Interactive position heatmap filters
- Match history and long-term progress
- Browser persistence using `localStorage`

The prototype deliberately does not upload or process the selected video. Accounts now use Supabase authentication; match data and profiles still use local browser storage. Those remaining boundaries can later be replaced with authenticated Supabase storage, database tables, a job queue, and Python computer-vision workers.

Before public launch, set the deployed Vercel URL as the Site URL and an allowed Redirect URL in Supabase Authentication settings so confirmation and password-reset links return to the application.
