from app.data_ingestion.sms_loader import load_sms_spam


CSV_PATH = "data/raw/sms_spam/spam.csv"


df = load_sms_spam(CSV_PATH)


print("\nTOTAL RECORDS:")
print(len(df))


print("\nCOLUMNS:")
print(df.columns.tolist())


print("\nFIRST 5 RECORDS:\n")


for i in range(min(5, len(df))):

    print("=" * 80)

    print("SOURCE:", df.iloc[i]["source"])

    print("LABEL:", df.iloc[i]["spam_label"])

    print("IS EMAIL:", df.iloc[i]["is_email"])

    print("TEXT:\n")

    print(df.iloc[i]["body_text_raw"][:300])