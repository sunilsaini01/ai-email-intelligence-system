from sentence_transformers import SentenceTransformer

print("Loading model...")

model = SentenceTransformer("all-MiniLM-L6-v2")

texts = [
    "I want a refund for my order.",
    "Please reimburse my payment.",
    "The weather is nice today."
]

print("\nGenerating embeddings...\n")

embeddings = model.encode(
    texts,
    normalize_embeddings=True,
)

print("Embedding Shape:", embeddings.shape)

print("\nDimension of one embedding:")
print(len(embeddings[0]))

print("\nFirst 10 values of first embedding:")
print(embeddings[0][:10])