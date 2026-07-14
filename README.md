# QuantAgent

QuantAgent is a local personal recruiting-intelligence agent for quantitative
finance. It discovers recruiting pages, collects opportunities from supported
ATS providers, tracks changes, scores opportunities against `profile.yaml`, and
sends deduplicated instant alerts and daily reports.

## Requirements

- Python 3.12
- `uv`
- Chromium for browser-rendered career pages
- An SMTP account for email notifications

## Installation

```bash
git clone https://github.com/Devansh-0104/QuantAgent.git
cd QuantAgent
uv sync
uv run playwright install chromium
cp .env.example .env
```

Edit `profile.yaml` before the first sync. Configure `.env` if email alerts are
required. Secrets in `.env` are ignored by Git.

## Usage

Add a company with its official website:

```bash
uv run quantagent watch "Jane Street" --website https://www.janestreet.com
```

The website option is strongly recommended. A preconfigured company may instead
be placed in `data/companies.yaml` using this format:

```yaml
Jane Street:
  website: https://www.janestreet.com
```

Run discovery or the complete pipeline:

```bash
uv run quantagent discover "Jane Street"
uv run quantagent sync
```

Inspect registered companies and pages:

```bash
uv run quantagent list
uv run quantagent pages "Jane Street"
uv run quantagent health
```

`sync` exits with status `1` when the run is partial or failed, allowing cron and
other supervisors to detect problems. Detailed logs are written to
`logs/quantagent.log` and rotated daily with 14 backups.

## Automated daily monitoring

Use the host scheduler to execute the complete sync pipeline. For example, a
daily cron entry at 08:00 is:

```cron
0 8 * * * cd /absolute/path/to/QuantAgent && /absolute/path/to/uv run --frozen quantagent sync
```

Use absolute paths and protect the repository directory because it contains the
SQLite database, profile, notification content, and possibly `.env` credentials.

## Supported providers

Production scraping and normalization are implemented for:

- Greenhouse
- Lever
- Workday
- Ashby
- SmartRecruiters
- Pinpoint
- Generic career pages through structured-data/HTML extraction

Generic extraction is deliberately conservative. Incomplete generic scans do
not close existing opportunities; authoritative ATS feeds do.

## Testing

```bash
uv run python -m unittest discover -p 'test*.py'
uv lock --check
uv build
```

## Operational data

- Database: `data/quantagent.db`
- Profile: `profile.yaml`
- Logs: `logs/quantagent.log`
- Optional company mapping: `data/companies.yaml`

Back up `data/quantagent.db` and `profile.yaml`. Do not run overlapping sync
processes against the same database. Runtime SQLite files are intentionally not
tracked by Git because they can contain private recruiting and notification data.
