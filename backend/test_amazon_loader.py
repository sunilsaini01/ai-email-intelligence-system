from app.data_ingestion.amazon_sentiment_loader import load_amazon_sentiment


CSV_PATH = (
    "data/raw/amazon_reviews/"
    "amazon_review_polarity_csv/train.csv"
)

df = load_amazon_sentiment(CSV_PATH)


print("\nTOTAL RECORDS:")
print(len(df))


print("\nCOLUMNS:")
print(df.columns.tolist())


print("\nFIRST 3 RECORDS:\n")


for i in range(min(3, len(df))):

    print("=" * 80)

    print("SOURCE:", df.iloc[i]["source"])

    print("LABEL:", df.iloc[i]["sentiment_label"])

    print("CONFIDENCE:", df.iloc[i]["sentiment_confidence"])

    print("TEXT:\n")

    print(df.iloc[i]["body_text_raw"][:500])