from app.feature_engineering.spam_keywords import SPAM_KEYWORDS

print("Spam Keyword Count:")
print(len(SPAM_KEYWORDS))

print()

print("Spam Keywords:")

for keyword in sorted(SPAM_KEYWORDS):
    print(keyword)