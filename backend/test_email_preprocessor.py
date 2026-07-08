from app.preprocessing.email_preprocessor import (
    EmailPreprocessor,
    PreprocessingConfig,
    SPAM_CONFIG,
    SENTIMENT_CONFIG,
    SUMMARY_CONFIG,
)
config = PreprocessingConfig()
preprocessor = EmailPreprocessor(config)

sample = """
<html>
<body>
Hello JOHN,

Visit https://openai.com

Thanks!

--
Sunil Kumar
AI Engineer
</body>
</html>
"""

result = preprocessor.process(sample)

print("Original:\n")
print(sample)

print("\nProcessed:\n")
print(result)

print("\n===== Task Specific Configurations =====")

spam = EmailPreprocessor(SPAM_CONFIG)
sentiment = EmailPreprocessor(SENTIMENT_CONFIG)
summary = EmailPreprocessor(SUMMARY_CONFIG)

print("Spam Config      :", spam.process(sample))
print("Sentiment Config :", sentiment.process(sample))
print("Summary Config   :", summary.process(sample))