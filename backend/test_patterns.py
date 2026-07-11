from app.feature_engineering.patterns import (
    URL_PATTERN,
    EMAIL_PATTERN,
    PHONE_PATTERN,
    CURRENCY_PATTERN,
)

text = """
Visit https://openai.com

Email: test@gmail.com

Phone: +91 9876543210

Price: ₹599
"""

print("URLs")
print(URL_PATTERN.findall(text))

print()

print("Emails")
print(EMAIL_PATTERN.findall(text))

print()

print("Phones")
print(PHONE_PATTERN.findall(text))

print()

print("Currencies")
print(CURRENCY_PATTERN.findall(text))