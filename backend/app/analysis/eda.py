import pandas as pd
import matplotlib.pyplot as plt


def plot_class_distribution(
    df: pd.DataFrame,
    label_col: str,
    title: str
) -> None:

    counts = df[label_col].value_counts()

    pct = counts / len(df) * 100

    fig, ax = plt.subplots(
        figsize=(8, 4)
    )

    bars = ax.bar(
        counts.index,
        counts.values
    )

    ax.set_title(
        f"{title}\n(n={len(df):,})"
    )

    ax.set_ylabel("Count")

    for bar, p in zip(bars, pct):

        ax.text(
            bar.get_x() + bar.get_width()/2,
            bar.get_height() + 0.1,
            f"{p:.1f}%",
            ha="center"
        )

    plt.tight_layout()

    plt.savefig(
        f"data/validation/{label_col}_distribution.png",
        dpi=150
    )

    plt.show()


def analyze_text_length(
    df: pd.DataFrame
) -> None:

    df["word_count"] = (
        df["body_clean"]
        .str
        .split()
        .str
        .len()
    )

    print("\nWORD COUNT STATS:\n")

    print(
        df["word_count"]
        .describe()
    )

    df["word_count"].hist(
        bins=30,
        figsize=(10, 4)
    )

    plt.title(
        "Word Count Distribution"
    )

    plt.xlabel("Words")

    plt.savefig(
        "data/validation/word_count_distribution.png",
        dpi=150
    )

    plt.show()


def analyze_nulls(
    df: pd.DataFrame
) -> None:

    null_summary = pd.DataFrame({

        "null_count":
        df.isnull().sum(),

        "null_pct":
        (
            df.isnull().sum()
            / len(df) * 100
        ).round(2)

    })

    null_summary = null_summary.sort_values(
        "null_pct",
        ascending=False
    )

    print("\nNULL ANALYSIS:\n")

    print(
        null_summary[
            null_summary["null_pct"] > 0
        ]
    )


def analyze_source_distribution(
    df: pd.DataFrame
) -> None:

    print("\nSOURCE DISTRIBUTION:\n")

    print(
        (
            df["data_source"]
            .value_counts(normalize=True)
            .round(3) * 100
        )
    )