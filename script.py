import os

# Define the output file name
output_file = 'combined_project.py'

# List of files provided in your directory structure
all_files = [
    'frontend/app.py', 'src/__init__.py', 'src/agent/__init__.py', 'src/agent/agent.py', 
    'src/agent/prompts.py', 'src/agent/tools.py', 'src/api/__init__.py', 'src/api/main.py', 
    'src/api/routes/__init__.py', 'src/api/routes/ask.py', 'src/api/routes/contracts.py', 
    'src/api/routes/metrics.py', 'src/api/routes/query.py', 'src/api/routes/upload.py', 
    'src/api/schemas.py', 'src/evaluation/__init__.py', 'src/evaluation/metrics_store.py', 
    'src/evaluation/ragas_evaluator.py', 'src/evaluation/run_eval.py', 'src/ingestion/__init__.py', 
    'src/ingestion/chunker.py', 'src/ingestion/embedder.py', 'src/ingestion/loader.py', 
    'src/monitoring/__init__.py', 'src/monitoring/dashboard.py', 'src/pipeline/__init__.py', 
    'src/pipeline/answerer.py', 'src/pipeline/chunker.py', 'src/pipeline/contracts_registry.py', 
    'src/pipeline/embedder.py', 'src/pipeline/parser.py', 'src/pipeline/pipeline.py', 
    'src/pipeline/retriever.py', 'src/retrieval/__init__.py', 'src/retrieval/dense_retriever.py', 
    'src/retrieval/hybrid_retriever.py', 'src/retrieval/sparse_retriever.py', 'tests/test_agent.py', 
    'tests/test_api.py', 'tests/test_chunker.py', 'tests/test_retrieval.py'
]

with open(output_file, 'w', encoding='utf-8') as outfile:
    for filepath in all_files:
        if os.path.exists(filepath):
            # Write a separator/header for clarity
            outfile.write(f"\n\n{'#'*80}\n")
            outfile.write(f"# FILE: {filepath}\n")
            outfile.write(f"{'#'*80}\n\n")
            
            with open(filepath, 'r', encoding='utf-8') as infile:
                content = infile.read()
                outfile.write(content)
                # Ensure a newline if the file doesn't have one at the end
                if not content.endswith('\n'):
                    outfile.write('\n')
        else:
            print(f"Warning: {filepath} not found.")

print(f"Successfully merged {len(all_files)} files into {output_file}")
