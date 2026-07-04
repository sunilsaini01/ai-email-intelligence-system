from app.preprocessing.email_preprocessing import (
    preprocess_email_body
)

sample_email = """
<div>Hello John,</div>

Thanks for your email.

On Monday Sarah wrote:
> Please review the document

--
Best regards,
Sunil Kumar
"""

result = preprocess_email_body(sample_email)

print("\nBODY CLEAN:\n")
print(result["body_clean"])

print("\nBODY NO QUOTES:\n")
print(result["body_no_quotes"])

print("\nBODY ANONYMIZED:\n")
print(result["body_anonymized"])