from app.data_ingestion.enron_loader import load_enron_kaggle


CSV_PATH = "data/raw/enron/emails.csv"


df = load_enron_kaggle(CSV_PATH)


print("\nTOTAL RECORDS LOADED:")
print(len(df))


print("\nCOLUMNS:")
print(df.columns.tolist())


print("\nFIRST 3 RECORDS:\n")


for i in range(min(3, len(df))):

    print("=" * 80)

    print("SOURCE:", df.iloc[i]["source"])

    print("FROM:", df.iloc[i]["sender_email"])

    print("SUBJECT:", df.iloc[i]["subject_raw"])

    print("DATE:", df.iloc[i]["received_at"])

    print("TO:", df.iloc[i]["recipient_to"])

    print("BODY PREVIEW:\n")

    print(str(df.iloc[i]["body_text_raw"])[:500])