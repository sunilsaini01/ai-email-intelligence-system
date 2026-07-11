from app.feature_engineering.feature_models import ContentFeatures

features = ContentFeatures(
    char_count=100,
    word_count=20,
    sentence_count=2,
    avg_word_length=4.5,
    avg_sentence_length=10.0,
    uppercase_word_count=2,
    uppercase_ratio=0.10,
    exclamation_count=1,
    question_mark_count=1,
    ellipsis_count=0,
    total_punctuation_count=5,
    punctuation_density=0.25,
    has_url=False,
    url_count=0,
    has_email_address=False,
    has_phone_number=False,
    has_currency=False,
    has_numbers=True,
    number_ratio=0.15,
    spam_keyword_count=2,
    spam_keyword_ratio=0.05,
    is_reply=False,
    subject_word_count=4,
    subject_is_uppercase=False,
    subject_has_re_prefix=False,
    subject_has_fwd_prefix=False,
    subject_exclamation_count=1,
)

print(features)