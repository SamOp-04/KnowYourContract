.PHONY: install ingest api frontend dashboard run test eval deploy

install:
	pip install -r requirements.txt

ingest:
	python -m src.ingestion.loader
	python -m src.ingestion.chunker
	python -m src.ingestion.embedder

api:
	uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000

frontend:
	streamlit run frontend/app.py --server.address 0.0.0.0 --server.port 8501

dashboard:
	streamlit run src/monitoring/dashboard.py --server.address 0.0.0.0 --server.port 8502

run:
	docker compose up --build

test:
	pytest -q

eval:
	python -m src.evaluation.run_eval --sample-size 100

deploy:
	cd infra/terraform && terraform init && terraform apply
