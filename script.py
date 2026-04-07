import os

# Define the output file name
output_file = 'combined_project.py'
current_script = os.path.basename(__file__)


def _sanitize_merged_content(content: str) -> str:
    filtered_lines = [
        line
        for line in content.splitlines()
        if line.strip() != 'from __future__ import annotations'
    ]
    return '\n'.join(filtered_lines)

# List of files provided in your directory structure
all_files = [
    'frontend/app.py',
    'run_batch_eval_extreme.py',
    'script.py',
    'src/__init__.py',
    'src/agent/__init__.py',
    'src/agent/agent.py',
    'src/agent/prompts.py',
    'src/agent/tools.py',
    'src/api/__init__.py',
    'src/api/main.py',
    'src/api/routes/__init__.py',
    'src/api/routes/ask.py',
    'src/api/routes/contracts.py',
    'src/api/routes/metrics.py',
    'src/api/routes/query.py',
    'src/api/routes/upload.py',
    'src/api/schemas.py',
    'src/evaluation/__init__.py',
    'src/evaluation/metrics_store.py',
    'src/evaluation/ragas_evaluator.py',
    'src/evaluation/run_eval.py',
    'src/ingestion/__init__.py',
    'src/ingestion/chunker.py',
    'src/ingestion/embedder.py',
    'src/ingestion/loader.py',
    'src/monitoring/__init__.py',
    'src/monitoring/dashboard.py',
    'src/pipeline/__init__.py',
    'src/pipeline/answerer.py',
    'src/pipeline/answerer_helpers.py',
    'src/pipeline/artifact_store.py',
    'src/pipeline/chat_scope_registry.py',
    'src/pipeline/chunker.py',
    'src/pipeline/contracts_registry.py',
    'src/pipeline/embedder.py',
    'src/pipeline/parser.py',
    'src/pipeline/pipeline.py',
    'src/pipeline/retriever.py',
    'src/retrieval/__init__.py',
    'src/utils/embeddings.py',
    'tests/test_agent.py',
    'tests/test_artifact_store.py',
    'tests/test_api.py',
    'tests/test_chunker.py',
    'tests/test_ingestion_embedder.py',
    'tests/test_registry_backends.py',
    'tests/test_retrieval.py',
]

with open(output_file, 'w', encoding='utf-8') as outfile:
    outfile.write('# pyright: reportInvalidTypeForm=false\n')
    outfile.write('from __future__ import annotations\n\n')
    merged_count = 0
    for filepath in all_files:
        if filepath in {output_file, current_script}:
            continue

        if os.path.exists(filepath):
            # Write a separator/header for clarity
            outfile.write(f"\n\n{'#'*80}\n")
            outfile.write(f"# FILE: {filepath}\n")
            outfile.write(f"{'#'*80}\n\n")
            
            with open(filepath, 'r', encoding='utf-8-sig') as infile:
                content = _sanitize_merged_content(infile.read())
                outfile.write(content)
                # Ensure a newline if the file doesn't have one at the end
                if not content.endswith('\n'):
                    outfile.write('\n')
                merged_count += 1
        else:
            print(f"Warning: {filepath} not found.")

print(f"Successfully merged {merged_count} files into {output_file}")
