.PHONY: install dev eval run clean

install:
	pip install -e .

dev:
	pip install -e ".[dev]"

# Run the root agent in the ADK CLI (interactive)
run:
	adk run root_agent

# Batch-evaluate against the test dataset
eval:
	adk eval root_agent evaluation.test.json

clean:
	find . -name "__pycache__" -type d -exec rm -rf {} +
	find . -name "*.pyc" -delete
