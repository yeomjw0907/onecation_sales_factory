# Tomorrow Handoff

## What Is Ready

- The local web console is working and loads at `http://127.0.0.1:8510`.
- Local SQLite runtime storage is active at `.runtime/operations.db`.
- Approval queue, rejection routing, asset preview, and notification logs are working.
- A `Send Test Email` button now exists inside each approval item.
- US and JP managed runs were re-tested after the international prompt rewrite.

## Latest Verified Test Runs

### US

- Run ID: `02ca37cc-2b60-4b6a-8274-88f84a0151d8`
- Company: `Universal Reprographics, Inc.`
- Output PDF:
  - `output/Universal Reprographics, Inc._제안서_2026-03-28_playwright.pdf`

### JP

- Run ID: `f9f5ebf4-c2c3-4d4f-aab9-077ae9f5d032`
- Company: `栄光情報システム株式会社 (Eikoh Joho System Co., Ltd.)`
- Output PDF:
  - `output/栄光情報システム株式会社 (Eikoh Joho System Co., Ltd.)_제안서_2026-03-28_playwright.pdf`

## What Changed

- Proposal and email prompts were rewritten for:
  - country-aware output
  - senior-sales proposal tone
  - the three core website situations:
    - `outdated_website`
    - `inconsistent_website`
    - `no_website`
  - market-specific execution plans instead of fixed SNS posting
- Gemini is currently used for proposal/email generation because Anthropic API credit is unavailable.
- Country defaults were added for:
  - `US`
  - `JP`
  - `TW`
  - `SG`
  - `CN`
  - `AE`
- Approval queue deduping was fixed so mismatched company titles do not create duplicate packages for the same company.
- The dashboard duplicate `selectbox` error was fixed.

## What Still Needs User Action

### 1. SMTP password

Current status:
- SMTP sending is blocked because `.env` still contains a placeholder value for `SMTP_PASSWORD`.

Impact:
- Alert emails do not send.
- `Send Test Email` correctly fails and logs the reason.

Required action:
- Replace `SMTP_PASSWORD` with a real app password for `yeomjw0907@onecation.co.kr`

### 2. Notion mapping

Current status:
- Notion sync is intentionally not part of the active test path.

Required action:
- Map the Notion database fields tomorrow, then re-enable Notion syncing.

## Morning Checklist

1. Open the web console.
2. Review the latest JP/US assets in `Assets` and `Approval Queue`.
3. Replace `SMTP_PASSWORD` in `.env`.
4. Click `Send Test Email` on one US package and one JP package.
5. Confirm the test emails arrive at `yeomjw0907@gmail.com`.
6. Map Notion fields and then decide whether to reconnect CRM sync.
