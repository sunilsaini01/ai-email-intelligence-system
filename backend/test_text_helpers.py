from app.preprocessing.text_helpers import *

print("\nSafe Decode")
print(safe_decode(b"Hello World"))

print("\nHTML")
print(strip_html("<h1>Hello</h1><p>World</p>"))

print("\nQuoted Reply")
print(remove_quoted_replies(
"""
Thanks

On Mon, John wrote:
>Hello
"""
))

print("\nSignature")
print(remove_signature(
"""
Hello

--
John
Engineer
"""
))

print("\nURL")
print(normalize_urls(
"Visit https://openai.com today"
))

print("\nWhitespace")
print(normalize_whitespace(
"Hello\n\n\nWorld"
))

print("\nLowercase")
print(lowercase("HELLO WORLD"))

print("\nLemma")
print(lemmatize(
"running studies cars"
))

print("\nStopwords")
print(remove_stopwords(
"I do not want to cancel this order"
))