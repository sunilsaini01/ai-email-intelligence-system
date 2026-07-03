from app.data_ingestion.dataset_registry import REGISTRY

print("\nAVAILABLE DATASETS:\n")

for key, dataset in REGISTRY.items():
    print("=" * 60)
    print("KEY:", key)
    print("NAME:", dataset.name)
    print("TASKS:", dataset.tasks)
    print("DOMAIN MATCH:", dataset.domain_match)
    print("TRUST LEVEL:", dataset.trust_level)
    print("LOCAL PATH:", dataset.local_path)