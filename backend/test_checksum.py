from app.data_ingestion.checksum_utils import save_checksum

FILE_PATH = "data/raw/enron/emails.csv"
OUTPUT_PATH = "data/raw/enron/CHECKSUM.sha256"

save_checksum(FILE_PATH, OUTPUT_PATH)
