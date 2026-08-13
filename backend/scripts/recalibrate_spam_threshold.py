"""
Recalibrate the spam decision threshold using real, out-of-domain business
email (Enron) as evidence, not a guess.

Why this exists: scripts/train_spam_model.py picks `decision_threshold`
(artifacts/spam_baseline_metrics.json) by optimizing recall on a held-out
split of the SAME SpamAssassin corpus the model trains on. Nothing in that
process ever measures how the model behaves on email that looks nothing
like SpamAssassin's ham class (SpamAssassin's ham is mailing-list-era
2000s content, not modern ordinary business correspondence). Live testing
against the running API confirmed the consequence directly: at the
deployed threshold (0.06), every ordinary business email tried ("Are you
free for lunch tomorrow?", an invoice notice, meeting notes) was flagged
as spam with 79-93% confidence.

UPDATE: train_spam_model.py now mixes a sample of real Enron business email
into training itself (see that file's split_enron_corpus()), which is the
real fix for the model's underlying discrimination -- this script's job is
now to verify that fix against a held-out Enron slice the model never
trained on, not to compensate for a model that never saw business email at
all. It measures:
  1. Recall on SpamAssassin's own held-out test set (reproducing the exact
     same deterministic split train_spam_model.py used) at a range of
     candidate thresholds -- same as before, nothing new here.
  2. False-positive rate on data/interim/enron_holdout_eval.parquet -- the
     Enron slice train_spam_model.py deliberately withheld from training
     (see that file's ENRON_HOLDOUT_SIZE) -- at the same candidate
     thresholds.

Picks the highest threshold that keeps SpamAssassin recall >= 0.95 (a
deliberately relaxed floor from the original 0.99 target -- see the
trade-off note in main() for why 0.99 is not achievable alongside a sane
Enron false-positive rate with this model, and rewrites
spam_baseline_metrics.json with the new value plus the Enron evidence,
so the choice is auditable, not silent.

Run from the repo root:
    PYTHONPATH=backend python backend/scripts/recalibrate_spam_threshold.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import recall_score

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data_ingestion.spamassassin_loader import load_spamassassin
from app.preprocessing.email_preprocessor import SPAM_CONFIG, EmailPreprocessor
from app.training.artifact_manager import ArtifactManager
from app.training.logger import get_logger
from scripts.train_spam_model import ENRON_HOLDOUT_PATH, RAW_DATA_DIR, split_dataset

logger = get_logger()

RECALL_FLOOR = 0.95
CANDIDATE_THRESHOLDS = [0.02, 0.06, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95]


def load_spamassassin_test_split(preprocessor: EmailPreprocessor) -> pd.DataFrame:
    """Reproduces train_spam_model.py's exact split (same random_state=42,
    same stratify) so 'recall on the test set' means the same test set the
    original metrics were computed on -- not a fresh random subset."""
    records = list(load_spamassassin(RAW_DATA_DIR))
    df = pd.DataFrame(records)
    df = df[df["body_text_raw"].str.len() > 0].reset_index(drop=True)
    df["body_clean"] = preprocessor.process_batch(df["body_text_raw"].tolist())
    df = df[df["body_clean"].str.len() > 0].reset_index(drop=True)
    df["label"] = (df["spam_label"] == "spam").astype(int)
    _, _, test_df = split_dataset(df)
    return test_df


def load_enron_holdout(preprocessor: EmailPreprocessor) -> pd.DataFrame:
    # Loads the exact slice train_spam_model.py's split_enron_corpus()
    # deliberately withheld from training -- NOT a fresh sample from the
    # full CSV. Sampling independently here (even with a different seed)
    # would only make overlap with the training mix *unlikely*, not
    # impossible; loading the file training itself wrote out makes the two
    # sets disjoint by construction, not by probability.
    if not Path(ENRON_HOLDOUT_PATH).exists():
        raise FileNotFoundError(
            f"{ENRON_HOLDOUT_PATH} not found -- run train_spam_model.py first, "
            "it writes this held-out slice as a side effect of training."
        )
    logger.info("Loading held-out Enron slice from %s", ENRON_HOLDOUT_PATH)
    df = pd.read_parquet(ENRON_HOLDOUT_PATH)
    df["body_clean"] = preprocessor.process_batch(df["body_text_raw"].tolist())
    df = df[df["body_clean"].str.len() > 0].reset_index(drop=True)
    logger.info("Enron holdout evaluation set: %d emails (all genuinely ham)", len(df))
    return df


def main():
    import json

    metrics_path = Path("artifacts/spam_baseline_metrics.json")
    old_data = json.loads(metrics_path.read_text(encoding="utf-8"))
    old_threshold = float(old_data["decision_threshold"])  # whatever train_spam_model.py's own naive calibration picked, not a hardcoded guess

    artifact_manager = ArtifactManager()
    model = artifact_manager.load_model("spam_baseline.joblib")
    preprocessor = EmailPreprocessor(SPAM_CONFIG)

    sa_test = load_spamassassin_test_split(preprocessor)
    sa_proba = model.predict_proba(sa_test["body_clean"].tolist())[:, 1]

    enron = load_enron_holdout(preprocessor)
    enron_proba = model.predict_proba(enron["body_clean"].tolist())[:, 1]

    thresholds_to_check = sorted(set(CANDIDATE_THRESHOLDS) | {old_threshold})

    print("\n================ THRESHOLD RECALIBRATION EVIDENCE ================\n")
    print(f"model_version={old_data.get('model_version')}  old_threshold={old_threshold}")
    print(f"{'threshold':>10} {'SA recall':>12} {'Enron FPR':>12}")
    rows = []
    old_enron_fpr = None
    for t in thresholds_to_check:
        sa_preds = (sa_proba >= t).astype(int)
        sa_recall = recall_score(sa_test["label"].tolist(), sa_preds)
        enron_fpr = float(np.mean(enron_proba >= t))  # every Enron email is ham, so any >=t is a false positive
        rows.append((t, sa_recall, enron_fpr))
        if t == old_threshold:
            old_enron_fpr = enron_fpr
        marker = "  <- current" if t == old_threshold else ""
        print(f"{t:>10.4f} {sa_recall:>12.4f} {enron_fpr:>12.4f}{marker}")

    # Highest threshold that still clears the recall floor -- same "recall
    # first, ties broken toward lower false-positive-rate" policy the
    # original calibration used, just against a floor that's achievable
    # alongside a sane Enron FPR instead of the original 0.99 (which, per
    # the table above, is only reachable at threshold <= ~0.1 -- exactly
    # the regime causing the false-positive problem in the first place).
    eligible = [r for r in rows if r[1] >= RECALL_FLOOR]
    if not eligible:
        print(f"\n[WARN] No candidate threshold clears the {RECALL_FLOOR} recall floor. Keeping existing threshold.")
        return
    chosen = max(eligible, key=lambda r: r[0])
    new_threshold, sa_recall, enron_fpr = chosen

    old_sa_recall = next((r for t, r, _ in rows if t == old_threshold), None)

    print(
        f"\nChosen threshold: {new_threshold:.4f} "
        f"(SpamAssassin recall={sa_recall:.4f}, Enron false-positive rate={enron_fpr:.4f})"
    )
    print(
        f"Trade-off, stated plainly: this trades the current threshold's {old_sa_recall:.4f} "
        f"SpamAssassin-domain recall for {sa_recall:.4f}, in exchange for changing the "
        f"real-business-email false-positive rate from {old_enron_fpr:.4f} (at the current "
        f"threshold {old_threshold}) to {enron_fpr:.4f}. Whether that trade is right depends on "
        "which failure mode costs more in production -- a missed spam email vs. a quarantined "
        "legitimate one -- a business decision, not a modeling one."
    )

    data = dict(old_data)
    data["decision_threshold"] = round(float(new_threshold), 4)
    # `meets_target` was computed at training time against the OLD threshold's
    # recall (0.9944 >= the original 0.99 target). Leaving it untouched after
    # changing the threshold would silently misrepresent the deployed model's
    # actual recall -- this recalibration deliberately relaxes the recall
    # floor to RECALL_FLOOR in exchange for a sane real-world false-positive
    # rate (see the trade-off note above), so both the target and whether it's
    # met need to reflect that new, explicit choice.
    data["recall_target"] = RECALL_FLOOR
    data["meets_target"] = bool(sa_recall >= RECALL_FLOOR)
    data["threshold_recalibration"] = {
        "method": "scripts/recalibrate_spam_threshold.py -- evaluated against real, "
        "out-of-domain Enron business email, not just SpamAssassin's own held-out split",
        "recall_floor": RECALL_FLOOR,
        "spamassassin_test_recall_at_new_threshold": round(float(sa_recall), 4),
        "enron_holdout_sample_size": len(enron),
        "enron_false_positive_rate_at_new_threshold": round(float(enron_fpr), 4),
        "previous_threshold": old_threshold,
        "enron_false_positive_rate_at_previous_threshold": round(float(old_enron_fpr), 4),
        "candidate_thresholds_evaluated": [
            {"threshold": t, "spamassassin_recall": round(r, 4), "enron_fpr": round(f, 4)}
            for t, r, f in rows
        ],
    }
    metrics_path.write_text(json.dumps(data, indent=4), encoding="utf-8")
    print(f"\n[OK] artifacts/spam_baseline_metrics.json updated -- decision_threshold={new_threshold:.2f}")


if __name__ == "__main__":
    main()
