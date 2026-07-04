from sklearn.metrics import cohen_kappa_score

annotator_1 = ["spam", "ham", "spam", "ham", "spam"]
annotator_2 = ["spam", "ham", "ham", "ham", "spam"]

kappa = cohen_kappa_score(annotator_1, annotator_2)

print(f"Cohen's Kappa: {kappa:.3f}")

if kappa < 0.60:
    print("WARNING: Low agreement")
else:
    print("Agreement acceptable")