demo:
	python -m workflow_demo demo --workspace .local

test:
	python -m unittest discover -s tests -v

audit:
	python scripts/publication_audit.py
