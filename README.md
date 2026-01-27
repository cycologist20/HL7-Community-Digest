# HL7 Community Intelligence System

Automated monitoring and daily digest system for HL7 standards community activities.

## Overview

This system monitors HL7 Confluence pages and Zulip chat channels, generating daily digest emails to help ASTP standards team members stay current with community discussions without manually checking multiple sources.

## Features

- **Confluence Scraping:** Automatically scrapes specified HL7 Confluence pages for meeting minutes
- **Zulip Monitoring:** Monitors chat.fhir.org channels for discussions (Phase 2)
- **AI Summarization:** Generates concise summaries of community activity (Phase 2)
- **Daily Digest:** Sends formatted email digest every weekday at 9 AM ET

## Quick Start

### Prerequisites

- Python 3.11+
- AWS CLI configured with appropriate credentials
- AWS SES verified sender domain/email

### Local Development Setup (PowerShell)

```powershell
# Clone repository
git clone https://github.com/cycologist20/HL7-Community-Digest.git
cd HL7-Community-Digest

# Create virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Copy environment template and configure
Copy-Item .env.example .env
# Edit .env with your credentials

# Run tests
pytest

# Test locally
python scripts/local_test.py
```

### Running the Digest Locally

```powershell
# Generate and send digest
python scripts/local_test.py --send-email

# Generate without sending (dry run)
python scripts/local_test.py --dry-run
```

## Project Structure

```
hl7-community-digest/
├── src/                    # Source code
│   ├── scrapers/          # Data collection modules
│   ├── processors/        # Content processing
│   ├── formatters/        # Digest formatting
│   └── delivery/          # Email delivery
├── lambda/                 # AWS Lambda handlers
├── infrastructure/         # IaC templates
├── tests/                  # Test suite
└── scripts/               # Utility scripts
```

## Configuration

See `.env.example` for required environment variables.

Source pages and channels are configured in `config/sources.yaml`.

## Documentation

- [Claude Project Instructions](CLAUDE_PROJECT_INSTRUCTIONS.md) - Development guidelines
- [Architecture](docs/architecture.md) - System design (coming soon)

## Roadmap

- **Phase 1 (Feb 10):** Confluence scraping + basic email digest
- **Phase 2 (Feb 28):** AI summarization + Zulip integration
- **Phase 3 (Mar 28):** Production deployment with monitoring

## License

Internal use only - ASTP AI Implementation Project
