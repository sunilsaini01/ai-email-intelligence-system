from app.data_ingestion.bbc_summary_loader import (
    load_bbc_news_summary
)


DATASET_PATH = (
    "data/raw/cnn_dailymail/"
    "BBC News Summary"
)


df = load_bbc_news_summary(DATASET_PATH)


print("\nTOTAL RECORDS:")
print(len(df))


print("\nCOLUMNS:")
print(df.columns.tolist())


print("\nFIRST 3 RECORDS:\n")


for i in range(min(3, len(df))):

    print("=" * 80)

    print("CATEGORY:", df.iloc[i]["category"])

    print("SOURCE:", df.iloc[i]["source"])

    print("IS EMAIL:", df.iloc[i]["is_email"])

    print("\nARTICLE:\n")

    print(df.iloc[i]["body_text_raw"][:500])

    print("\nSUMMARY:\n")

    print(df.iloc[i]["summary_reference"][:300])