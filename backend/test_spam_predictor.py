from app.inference.spam_predictor import SpamPredictor


def main():

    predictor = SpamPredictor(
    "trainer_test.joblib"
)

    email = {
        "body_clean": "Congratulations! You won a free iPhone. Click here now.",
    }

    print("=" * 50)
    print("SINGLE PREDICTION")
    print("=" * 50)

    result = predictor.predict(email)

    print(result)

    print()

    emails = [
        {
            "body_clean": "Congratulations! Claim your prize now.",
        },
        {
            "body_clean": "Let's schedule a meeting tomorrow.",
        },
        {
            "body_clean": "Limited time offer! Buy now!",
        },
    ]

    print("=" * 50)
    print("BATCH PREDICTION")
    print("=" * 50)

    results = predictor.predict_batch(emails)

    for i, prediction in enumerate(results, start=1):
        print(f"\nEmail {i}")
        print(prediction)


if __name__ == "__main__":
    main()