from app.feature_engineering.content_features import ContentFeatureExtractor

body = """
URGENT!!!

FREE money available.

Visit https://openai.com

Email support@gmail.com

Call +91 9876543210

Refund ₹599 immediately.

CLICK NOW!!

THANK YOU!!!!
"""

subject = "RE: URGENT REFUND!!!"

extractor = ContentFeatureExtractor()

features = extractor.extract(
    body_clean=body,
    subject_raw=subject,
    is_reply=True,
)

print(features)