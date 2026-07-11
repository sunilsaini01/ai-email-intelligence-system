from datetime import datetime

from app.feature_engineering.metadata_features import MetadataFeatureExtractor


extractor = MetadataFeatureExtractor()

features = extractor.extract(
    received_at=datetime(2026, 7, 10, 20, 30),   # Friday 8:30 PM
    sender_email="john@gmail.com",
    recipient_to=[
        "alice@company.com",
    ],
    recipient_cc=[
        "bob@company.com",
    ],
    thread_depth=2,
    is_reply=True,
    is_forward=False,
    has_attachments=True,
    attachment_count=3,
)

print(features)