from app.data_ingestion.checksum_utils import verify_checksum

FILE_PATH = "data/raw/enron/emails.csv"
CHECKSUM_PATH = "data/raw/enron/CHECKSUM.sha256"

verify_checksum(FILE_PATH, CHECKSUM_PATH)
