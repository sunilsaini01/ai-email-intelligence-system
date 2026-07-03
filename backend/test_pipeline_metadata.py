from app.data.pipeline_metadata import PipelineRun

run = PipelineRun(
    version="v1.0",
    script_name="test_pipeline_metadata.py"
)

run.log_input(
    path="data/raw/enron/emails.csv",
    checksum="dummy_checksum_123"
)

run.log_step(
    "deduplication",
    {
        "removed_duplicates": 412,
        "method": "message_id"
    }
)

run.log_step(
    "split_assignment",
    {
        "train": 1000,
        "val": 200,
        "test": 200
    }
)

run.log_output(
    path="data/processed/v1.0/train.parquet",
    record_count=1000
)

run.save("data/processed/v1.0/")