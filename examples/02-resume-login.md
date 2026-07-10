# Example 2 — Resume a logged-in session

Goal: log in once, save the session, then reopen the site already authenticated
without logging in again.

## Step 1 — capture the login state

```bash
domvault serve
```

1. Enter the site URL, click **Open**.
2. Log in manually in the Playwright browser window.
3. Once logged in, click **Save snapshot** (any name, e.g. `logged-in`).

This writes `saved_html/logged-in/storage_state.json` containing your cookies
and localStorage — exactly what Playwright needs to restore the session.

> `storage_state.json` only contains cookies + web storage. It does **not**
> include IndexedDB or service-worker registrations.

## Step 2 — reopen with that state (web panel)

1. In the **Restore login state (optional)** field, pick
   `saved_html/logged-in/storage_state.json`.
2. Enter the site URL, click **Open**. The browser opens **already logged in**.

## Step 3 — or do it from the CLI

```bash
domvault capture https://app.example.com/dashboard \
    --storage-state saved_html/logged-in/storage_state.json \
    --name dashboard-authed
```

The headless capture runs with your saved cookies/localStorage, so the
captured `page.html` reflects the authenticated page.
