from app.security.pii_anonymizer import anonymize_email_body

sample_text = """
Hello Sunil,

My phone number is 9876543210
and my email is sunil@gmail.com

My credit card is 4532-1234-5678-9012
"""

anon_text, entities = anonymize_email_body(sample_text)

print("\nANONYMIZED TEXT:\n")
print(anon_text)

print("\nDETECTED ENTITIES:\n")
print(entities)

