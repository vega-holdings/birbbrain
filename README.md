# birbbrain

Twitter bookmark extractor to Obsidian.

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Copy `.env.example` to `.env` and fill in values as needed.
3. Adjust `config.yaml` paths if desired.

## Running

Place your exported CSV from Google Sheets as specified in `config.yaml` (default `tweets.csv`).
Run:
```bash
python -m src.main
```

The script will create an `obsidian_vault` directory with tweets and extracted content.

Sample output is provided in `obsidian_vault/`.
