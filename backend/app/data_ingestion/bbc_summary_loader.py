from pathlib import Path

import pandas as pd


def load_bbc_news_summary(
    dataset_dir: str
) -> pd.DataFrame:

    articles_root = (
        Path(dataset_dir)
        / "News Articles"
    )

    summaries_root = (
        Path(dataset_dir)
        / "Summaries"
    )

    records = []

    categories = [
        "business",
        "entertainment",
        "politics",
        "sport",
        "tech"
    ]

    for category in categories:

        article_dir = articles_root / category

        summary_dir = summaries_root / category

        if not article_dir.exists():
            continue

        for article_path in article_dir.glob("*.txt"):

            try:

                summary_path = (
                    summary_dir / article_path.name
                )

                if not summary_path.exists():
                    continue

                article_text = article_path.read_text(
                    encoding="latin-1",
                    errors="replace"
                )

                summary_text = summary_path.read_text(
                    encoding="latin-1",
                    errors="replace"
                )

                records.append({

                    "source": "bbc_news_summary",

                    "category": category,

                    "body_text_raw": article_text,

                    "summary_reference": summary_text,

                    "is_email": False
                })

            except Exception as e:

                print(
                    f"[WARN] Failed: {article_path} -> {e}"
                )

                continue

    return pd.DataFrame(records)