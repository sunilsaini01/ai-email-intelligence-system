from app.data_ingestion.spamassassin_loader import load_spamassassin

DATA_DIR = "data/raw/spamassassin"

emails = load_spamassassin(DATA_DIR)

for i, email_record in enumerate(emails):
    print(email_record)

    if i == 2:
        break