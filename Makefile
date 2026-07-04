.PHONY: data validate test clean-interim

data:
	@echo "Step 1/5: Verifying checksums..."
	python backend/scripts/data/verify_checksums.py

	@echo "Step 2/5: Ingesting datasets..."
	python backend/scripts/data/ingest.py

	@echo "Step 3/5: Preprocessing..."
	python backend/scripts/data/preprocess.py

	@echo "Step 4/5: Assigning splits..."
	python backend/scripts/data/assign_splits.py

	@echo "Step 5/5: Building artifacts..."
	python backend/scripts/data/build_artifacts.py

	@echo "Pipeline complete."

validate:
	python backend/scripts/data/validate.py

test:
	python -m pytest tests/data/ -v

clean-interim:
	rmdir /s /q data\interim
	@echo "Interim cleared."

