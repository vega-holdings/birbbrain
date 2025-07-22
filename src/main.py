import csv
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List

import requests
from bs4 import BeautifulSoup
from readability import Document
from dotenv import load_dotenv
import yaml

# Load configuration from .env and config.yaml
load_dotenv()

CONFIG_PATH = os.getenv("BIRBBRAIN_CONFIG", "config.yaml")
with open(CONFIG_PATH, "r") as f:
    CONFIG = yaml.safe_load(f)

TWITTER_CSV = CONFIG.get("csv_path", "tweets.csv")
OUTPUT_DIR = Path(CONFIG.get("output_dir", "obsidian_vault"))
PROCESSED_LOG = OUTPUT_DIR / "processed.log"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

# Ensure output subdirectories exist
(OUTPUT_DIR / "Tweets").mkdir(parents=True, exist_ok=True)
(OUTPUT_DIR / "Media" / "Images").mkdir(parents=True, exist_ok=True)
(OUTPUT_DIR / "Media" / "Videos").mkdir(parents=True, exist_ok=True)
(OUTPUT_DIR / "GitHub").mkdir(parents=True, exist_ok=True)
(OUTPUT_DIR / "Substack").mkdir(parents=True, exist_ok=True)
(OUTPUT_DIR / "arXiv").mkdir(parents=True, exist_ok=True)


def load_processed() -> set:
    if PROCESSED_LOG.exists():
        return set(PROCESSED_LOG.read_text().splitlines())
    return set()


def log_processed(tweet_id: str):
    with PROCESSED_LOG.open("a") as f:
        f.write(tweet_id + "\n")


@dataclass
class Tweet:
    url: str
    author: str
    date: str
    timestamp: str


# Utilities

def sanitize_filename(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9-_ ]", "", text)[:50].strip()


def fetch_thread(url: str) -> List[dict]:
    """Fetch thread data using snscrape."""
    import snscrape.modules.twitter as sntwitter

    tweet_id = url.split("/")[-1].split("?")[0]
    scraper = sntwitter.TwitterTweetScraper(tweet_id, mode=sntwitter.TweetScrapeMode.SINGLE)
    tweets = []
    for t in scraper.get_items():
        conversation_id = t.conversationId
        break
    thread_scraper = sntwitter.TwitterSearchScraper(f"conversation_id:{conversation_id}")
    for t in thread_scraper.get_items():
        tweets.append({
            "id": t.id,
            "content": t.content,
            "author": t.user.username,
            "date": t.date,
            "url": f"https://twitter.com/{t.user.username}/status/{t.id}",
            "media": t.media,
        })
    tweets.sort(key=lambda x: x["date"])
    return tweets


def download_media(media, out_dir: Path):
    paths = []
    if not media:
        return paths
    for item in media:
        if hasattr(item, "fullUrl"):
            url = item.fullUrl
            ext = Path(url).suffix
            kind = "Images" if ext.lower() in {".jpg", ".jpeg", ".png", ".gif"} else "Videos"
            fname = sanitize_filename(Path(url).stem) + ext
            dest = out_dir / kind / fname
            if not dest.exists():
                r = requests.get(url)
                dest.write_bytes(r.content)
            paths.append(dest.relative_to(out_dir.parent))
    return paths


def extract_github(repo_url: str, out_dir: Path):
    api_url = repo_url.replace("https://github.com/", "https://api.github.com/repos/")
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    r = requests.get(api_url, headers=headers)
    if r.status_code != 200:
        return None
    data = r.json()
    readme_r = requests.get(api_url + "/readme", headers=headers, params={"accept": "application/vnd.github.raw"})
    readme_text = readme_r.text if readme_r.status_code == 200 else ""
    md_path = out_dir / f"{data['name']}.md"
    with md_path.open("w") as f:
        f.write(f"# {data['full_name']}\n\n")
        f.write(f"Stars: {data['stargazers_count']} | Forks: {data['forks_count']}\n\n")
        f.write(readme_text)
    return md_path


def extract_article(url: str, out_dir: Path) -> Path:
    r = requests.get(url)
    doc = Document(r.text)
    soup = BeautifulSoup(doc.summary(), "html.parser")
    title = soup.title.string if soup.title else "article"
    text = soup.get_text()
    fname = sanitize_filename(title) + ".md"
    path = out_dir / fname
    with path.open("w") as f:
        f.write(f"# {title}\n\n")
        f.write(text)
    return path


def extract_arxiv(url: str, out_dir: Path) -> Path:
    arxiv_id = url.split("/")[-1]
    api_url = f"http://export.arxiv.org/api/query?id_list={arxiv_id}"
    r = requests.get(api_url)
    soup = BeautifulSoup(r.text, "xml")
    entry = soup.find("entry")
    if not entry:
        return None
    title = entry.title.text.strip().replace("\n", " ")
    abstract = entry.summary.text.strip()
    pdf_url = entry.id.text.replace("abs", "pdf") + ".pdf"
    pdf_name = f"{sanitize_filename(title)} - {arxiv_id}.pdf"
    pdf_path = out_dir / pdf_name
    if not pdf_path.exists():
        pdf_data = requests.get(pdf_url).content
        pdf_path.write_bytes(pdf_data)
    md_path = out_dir / f"{sanitize_filename(title)} - {arxiv_id}.md"
    with md_path.open("w") as f:
        f.write(f"# {title}\n\n")
        f.write(f"**Categories:** {entry.find('category')['term']}\n\n")
        f.write(f"**PDF:** [[{pdf_name}]]\n\n")
        f.write(abstract)
    return md_path


def process_links(text: str, out_md: Path, vault_dir: Path):
    links = re.findall(r"https?://\S+", text)
    for link in links:
        if "github.com" in link:
            md = extract_github(link, vault_dir / "GitHub")
            if md:
                out_md.write_text(out_md.read_text() + f"\n\nGitHub: [[{md.relative_to(vault_dir)}]]")
        elif any(domain in link for domain in ["substack.com", "medium.com"]):
            md = extract_article(link, vault_dir / "Substack")
            out_md.write_text(out_md.read_text() + f"\n\nArticle: [[{md.relative_to(vault_dir)}]]")
        elif "arxiv.org" in link:
            md = extract_arxiv(link, vault_dir / "arXiv")
            if md:
                out_md.write_text(out_md.read_text() + f"\n\nPaper: [[{md.relative_to(vault_dir)}]]")
        else:
            (vault_dir / "unprocessed_links.txt").open("a").write(link + "\n")


def process_tweet(tweet: Tweet, processed: set):
    tweet_id = tweet.url.split("/")[-1]
    if tweet_id in processed:
        return
    thread = fetch_thread(tweet.url)
    if not thread:
        return
    summary = sanitize_filename(thread[0]['content'].split('\n')[0])
    md_name = f"{tweet.date} - {tweet.author} - {summary}.md"
    md_path = OUTPUT_DIR / "Tweets" / md_name
    with md_path.open("w") as f:
        f.write(f"# Thread by {tweet.author}\n")
        for t in thread:
            media_paths = download_media(t.get('media'), OUTPUT_DIR)
            f.write(f"\n### {t['author']} - {t['date']}\n")
            f.write(t['content'] + "\n")
            for p in media_paths:
                f.write(f"![[{p}]]\n")
    process_links(md_path.read_text(), md_path, OUTPUT_DIR)
    log_processed(tweet_id)


def main():
    processed = load_processed()
    with open(TWITTER_CSV, newline="") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            tweet = Tweet(
                url=row.get("Tweet URL"),
                author=row.get("Author"),
                date=row.get("Date"),
                timestamp=row.get("Timestamp", ""),
            )
            process_tweet(tweet, processed)


if __name__ == "__main__":
    main()
